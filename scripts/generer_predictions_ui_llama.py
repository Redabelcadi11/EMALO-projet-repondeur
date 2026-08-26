#!/usr/bin/env python3
"""Rejoue exactement le pipeline UI sur des transcriptions gelees.

Llama reste borne par les regles de l'UI : il ne traite que les selections
produit ambigues. Aucune donnee cible ERP n'est lue ni fournie au moteur.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from generer_predictions_evaluation import (
    _application_fingerprint,
    _atomic_json,
    _prediction_from_command,
    _sha256,
    assert_forbidden_paths_inaccessible,
    validate_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--transcriptions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--forbidden-path", action="append", default=[])
    args = parser.parse_args()

    assert_forbidden_paths_inaccessible(args.forbidden_path)
    raw_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = validate_manifest(raw_manifest)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from src.evaluation_safety import load_evaluation_safety_policy
    from src.erp_safety import erp_safety_status
    from src.llm_arbitrage import ollama_disponible
    import extraire_informations as extraction

    policy = load_evaluation_safety_policy()
    erp = erp_safety_status()
    if not policy.valid or policy.mode != "strict_no_target_leakage":
        raise RuntimeError("Politique anti-fuite absente ou invalide.")
    if erp.writes_allowed or not erp.evaluation_lock:
        raise RuntimeError("Le verrou central ERP n'est pas actif.")
    if not ollama_disponible():
        raise RuntimeError("Llama local indisponible.")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    extraction.DOSSIER_RESULTATS = args.work_dir
    paths: list[Path] = []
    by_stem: dict[str, str] = {}
    errors: dict[str, str] = {}
    for row in rows:
        audio = row["audio"]
        path = args.transcriptions / f"{Path(audio).stem}__transcription.json"
        if not path.is_file():
            errors[audio] = "transcription_absente"
        elif _sha256(path) != row["transcription_sha256"]:
            errors[audio] = "hash_transcription_incorrect"
        else:
            paths.append(path)
            by_stem[Path(audio).stem] = audio

    started = time.perf_counter()
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        commands = extraction.traiter_transcriptions(paths) if paths else []
    by_audio = {
        by_stem[Path(str(command.get("fichier_audio") or "")).stem]: command
        for command in commands
        if Path(str(command.get("fichier_audio") or "")).stem in by_stem
    }
    predicted: list[dict[str, Any]] = []
    for row in rows:
        audio = row["audio"]
        if audio in by_audio:
            predicted.append(_prediction_from_command(audio, by_audio[audio]))
        else:
            predicted.append({
                "audio": audio,
                "client_code": "",
                "delivery_date": "",
                "status": "ERREUR",
                "lines": [],
                "transcription": "",
                "diagnostics": {"runtime_log": captured.getvalue()[-4000:]},
                "error": errors.get(audio, "aucune_sortie_du_moteur"),
            })
    output = {
        "schema": "emalo-evaluation-predictions/v1",
        "dataset_id": raw_manifest["dataset_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_manifest_sha256": _sha256(args.manifest),
        "application_fingerprint": _application_fingerprint(),
        "prediction_mode": "ui_pipeline_with_bounded_local_llama",
        "truth_received_by_predictor": False,
        "erp_write_attempted": False,
        "llama_available": True,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "row_count": len(predicted),
        "rows": predicted,
    }
    _atomic_json(args.output, output)
    print(json.dumps({key: value for key, value in output.items() if key != "rows"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
