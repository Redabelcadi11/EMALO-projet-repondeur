#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TOP_LEVEL_KEYS = {
    "schema", "dataset_id", "created_at", "row_count", "rows"
}
ALLOWED_ROW_KEYS = {"audio", "transcription_sha256"}
FORBIDDEN_KEY_PARTS = {
    "truth", "erp", "order_number", "article", "product", "client_code",
    "commande_reelle", "copilote",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def validate_manifest(payload: dict[str, Any]) -> list[dict[str, str]]:
    if payload.get("schema") != "emalo-evaluation-input/v1":
        raise ValueError("Schema de manifeste invalide.")
    unexpected = set(payload) - ALLOWED_TOP_LEVEL_KEYS
    if unexpected:
        raise ValueError(f"Champs interdits dans le manifeste: {sorted(unexpected)}")
    rows = payload.get("rows")
    if not isinstance(rows, list) or int(payload.get("row_count") or -1) != len(rows):
        raise ValueError("Nombre de lignes de manifeste incoherent.")
    validated: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Chaque ligne de manifeste doit etre un objet.")
        unexpected = set(row) - ALLOWED_ROW_KEYS
        forbidden = any(
            part in str(key).casefold()
            for key in row
            for part in FORBIDDEN_KEY_PARTS
        )
        if unexpected or forbidden:
            raise ValueError(f"Ligne contenant des donnees cible interdites: {unexpected}")
        audio = str(row.get("audio") or "")
        digest = str(row.get("transcription_sha256") or "")
        if Path(audio).name != audio or not audio or audio in seen:
            raise ValueError(f"Nom audio invalide ou duplique: {audio!r}")
        if not re_full_sha256(digest):
            raise ValueError(f"Hash de transcription invalide pour {audio}")
        validated.append({"audio": audio, "transcription_sha256": digest})
        seen.add(audio)
    return validated


def re_full_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def assert_forbidden_paths_inaccessible(paths: list[str]) -> None:
    for raw in paths:
        path = Path(raw)
        try:
            if path.is_dir():
                next(path.iterdir(), None)
            else:
                with path.open("rb") as handle:
                    handle.read(1)
        except (FileNotFoundError, PermissionError, OSError):
            continue
        raise PermissionError(
            f"Le processus de prediction peut lire une source de verite interdite: {path}"
        )


def _application_fingerprint() -> str:
    paths = [PROJECT_ROOT / "extraire_informations.py"]
    paths.extend(sorted((PROJECT_ROOT / "src").glob("*.py")))
    for name in (
        "evaluation-safety.json", "erp-safety.json", "synonymes-produits.json",
        "variantes-clients.json", "telephones-clients.json", "unites-articles.csv",
        "catalogue-articles.json", "references-articles-controle.json",
        "reappro_basco.csv", "regles-metier-sures.json",
        "aliases-telephoniques-confirmes.json",
    ):
        candidate = PROJECT_ROOT / "config" / name
        if candidate.is_file():
            paths.append(candidate)
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(str(path.relative_to(PROJECT_ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _prediction_from_command(audio: str, command: dict[str, Any]) -> dict[str, Any]:
    lines = [
        {
            "code": str(
                line.get("code_article")
                or line.get("article_code")
                or line.get("code")
                or ""
            ),
            "quantity": line.get("quantite", line.get("quantity")),
            "unit": str(line.get("unite") or line.get("unit") or ""),
            "label": str(
                line.get("libelle_article") or line.get("designation") or ""
            ),
            "source_text": str(line.get("texte_source") or ""),
        }
        for line in command.get("lignes_commande") or []
    ]
    return {
        "audio": audio,
        "client_code": str(command.get("client_retenu") or ""),
        "client_name": str(command.get("client_nom_retenu") or ""),
        "delivery_date": str(
            (command.get("date_livraison") or {}).get("date_iso") or ""
        ),
        "status": str(command.get("statut") or ""),
        "lines": lines,
        "transcription": str(command.get("transcription") or ""),
        "diagnostics": {
            "client_zone": command.get("zone_client_detectee") or "",
            "client_candidates": command.get("clients_candidats") or [],
            "client_reasons": command.get("raisons_decision_client") or [],
            "problem_reasons": command.get("raisons_problematiques") or [],
            "mentions": command.get("mentions_produits") or [],
            "products": command.get("produits") or [],
        },
        "error": "",
    }


def _predict_chunk(
    payload: tuple[int, list[dict[str, str]], str, str]
) -> list[dict[str, Any]]:
    index, rows, transcriptions_raw, output_root_raw = payload
    transcriptions = Path(transcriptions_raw)
    output_dir = Path(output_root_raw) / f"chunk-{index:03d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from src import llm_arbitrage
    from src.evaluation_safety import load_evaluation_safety_policy
    from src.erp_safety import erp_safety_status

    evaluation_policy = load_evaluation_safety_policy()
    erp_status = erp_safety_status()
    if not evaluation_policy.valid or evaluation_policy.mode != "strict_no_target_leakage":
        raise RuntimeError("Politique anti-fuite absente ou invalide.")
    if erp_status.writes_allowed or not erp_status.evaluation_lock:
        raise RuntimeError("Le verrou central ERP n'est pas actif.")

    llm_arbitrage.ollama_disponible = lambda: False
    import extraire_informations as extraction

    extraction.DOSSIER_RESULTATS = output_dir
    paths: list[Path] = []
    by_stem: dict[str, str] = {}
    errors: dict[str, str] = {}
    for row in rows:
        audio = row["audio"]
        path = transcriptions / f"{Path(audio).stem}__transcription.json"
        if not path.is_file():
            errors[audio] = f"transcription_absente:{path}"
            continue
        if _sha256(path) != row["transcription_sha256"]:
            errors[audio] = "hash_transcription_incorrect"
            continue
        paths.append(path)
        by_stem[Path(audio).stem] = audio

    commands: list[dict[str, Any]] = []
    captured = io.StringIO()
    if paths:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            commands = extraction.traiter_transcriptions(paths)
    predictions: dict[str, dict[str, Any]] = {}
    for command in commands:
        stem = Path(str(command.get("fichier_audio") or "")).stem
        audio = by_stem.get(stem)
        if audio:
            predictions[audio] = _prediction_from_command(audio, command)
    result: list[dict[str, Any]] = []
    for row in rows:
        audio = row["audio"]
        if audio in predictions:
            result.append(predictions[audio])
        else:
            result.append(
                {
                    "audio": audio,
                    "client_code": "",
                    "delivery_date": "",
                    "status": "ERREUR",
                    "lines": [],
                    "transcription": "",
                    "diagnostics": {"runtime_log": captured.getvalue()[-4000:]},
                    "error": errors.get(audio, "aucune_sortie_du_moteur"),
                }
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genere des predictions sans jamais recevoir la verite ERP."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--transcriptions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--forbidden-path", action="append", default=[])
    args = parser.parse_args()

    assert_forbidden_paths_inaccessible(args.forbidden_path)
    raw_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = validate_manifest(raw_manifest)
    workers = max(1, min(int(args.workers), max(1, len(rows))))
    chunks = [rows[index::workers] for index in range(workers)]
    started = time.perf_counter()
    predictions: list[dict[str, Any]] = []
    payloads = [
        (index, chunk, str(args.transcriptions), str(args.work_dir))
        for index, chunk in enumerate(chunks)
        if chunk
    ]
    if workers == 1:
        predictions = _predict_chunk(payloads[0]) if payloads else []
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_predict_chunk, payload) for payload in payloads]
            for future in as_completed(futures):
                predictions.extend(future.result())
    predictions.sort(key=lambda row: row["audio"])
    output = {
        "schema": "emalo-evaluation-predictions/v1",
        "dataset_id": raw_manifest["dataset_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_manifest_sha256": _sha256(args.manifest),
        "application_fingerprint": _application_fingerprint(),
        "prediction_mode": "deterministic_no_network_no_llm",
        "truth_received_by_predictor": False,
        "erp_write_attempted": False,
        "workers": workers,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "row_count": len(predictions),
        "rows": predictions,
    }
    _atomic_json(args.output, output)
    print(json.dumps({key: value for key, value in output.items() if key != "rows"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
