#!/usr/bin/env python3
"""Rejoue les derniers audios avec le contexte Whisper actuel.

Ce script est volontairement limite a la transcription GPU et a la
prediction locale. Il n'importe aucun module Copilote/ERP et refuse de
demarrer si le verrou ERP n'est pas actif. Les transcriptions et extractions
sont recopiees localement afin que l'UI affiche le nouveau resultat.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from prod_pipeline import all_nextcloud_audios, persist_analysis_details
from src.erp_safety import erp_safety_status
from worker_client import remote_analyze_audio, remote_transcribe_audio, write_remote_transcription


STATUS_DIR = PROJECT_ROOT / "resultats" / "reanalyses"


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def refresh_ui() -> None:
    # La generation du cache UI lit seulement les resultats locaux ; elle ne
    # cree aucune commande et ne contacte pas l'ERP.
    from generer_ui_data_prod import main as generate_ui_data

    if generate_ui_data() != 0:
        raise RuntimeError("Echec de regeneration des donnees UI")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reanalyse les derniers audios avec contexte Whisper force."
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--ui-every",
        type=int,
        default=5,
        help="Regenerer le cache UI toutes les N analyses (defaut: 5).",
    )
    parser.add_argument("--status", type=Path)
    args = parser.parse_args()

    safety = erp_safety_status()
    if not safety.evaluation_lock or safety.writes_allowed:
        raise RuntimeError(
            "Refus: le verrou ERP doit rester actif et les ecritures interdites."
        )
    if args.limit < 1:
        raise ValueError("--limit doit etre superieur a zero")

    audios = all_nextcloud_audios()[: args.limit]
    if not audios:
        raise RuntimeError("Aucun audio Nextcloud disponible")

    status_path = args.status or (
        STATUS_DIR / "reanalyse-dernieres-commandes-contexte-asr.json"
    )
    state: dict[str, Any] = {
        "schema": "emalo-reanalyse-contexte-asr/v1",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": "",
        "requested": len(audios),
        "transcribed": 0,
        "analysed": 0,
        "failed": 0,
        "phase": "transcription",
        "erp_write_attempted": False,
        "erp_safety": safety.as_dict(),
        "audios": [audio.name for audio in audios],
        "rows": [],
    }
    write_json_atomic(status_path, state)

    # Phase 1 : Whisper reste resident sur le GPU et chaque audio est force
    # pour prendre en compte le contexte telephone/cadencier nouvellement
    # deployee. Aucun resultat precedent n'est reutilise.
    for index, audio in enumerate(audios, start=1):
        started = time.perf_counter()
        try:
            response = remote_transcribe_audio(audio, force=True)
            if not response.get("ok"):
                raise RuntimeError(str(response.get("message") or "worker indisponible"))
            write_remote_transcription(audio, response)
            state["transcribed"] += 1
            state["rows"].append(
                {
                    "audio": audio.name,
                    "transcription": "ok",
                    "transcription_seconds": response.get("transcription_seconds"),
                    "context_active": (response.get("transcription_json") or {}).get("contexte_asr_actif"),
                    "context_terms": (response.get("transcription_json") or {}).get("contexte_asr_nb_termes"),
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                }
            )
        except Exception as exc:
            state["failed"] += 1
            state["rows"].append(
                {
                    "audio": audio.name,
                    "transcription": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                }
            )
        write_json_atomic(status_path, state)
        print(f"TRANSCRIPTION {index}/{len(audios)} {audio.name}", flush=True)

    # Phase 2 : les transcriptions sont deja figees. L'analyse ne force donc
    # pas Whisper et le worker peut liberer le GPU pour Llama.
    state["phase"] = "analyse"
    write_json_atomic(status_path, state)
    for index, audio in enumerate(audios, start=1):
        row = next(item for item in state["rows"] if item["audio"] == audio.name)
        if row.get("transcription") != "ok":
            continue
        started = time.perf_counter()
        try:
            response = remote_analyze_audio(audio, force=False)
            if not response.get("ok"):
                raise RuntimeError(str(response.get("message") or "analyse worker indisponible"))
            write_remote_transcription(audio, response)
            commandes = response.get("commandes")
            if not isinstance(commandes, list) or len(commandes) != 1:
                raise RuntimeError("Reponse worker sans commande unique")
            persist_analysis_details(commandes)
            commande = commandes[0]
            row.update(
                {
                    "analysis": "ok",
                    "status": commande.get("statut"),
                    "client": commande.get("client_retenu"),
                    "lines": len(commande.get("lignes_commande") or []),
                    "analysis_seconds": response.get("analysis_seconds"),
                    "elapsed_analysis_seconds": round(time.perf_counter() - started, 3),
                }
            )
            state["analysed"] += 1
        except Exception as exc:
            state["failed"] += 1
            row.update(
                {
                    "analysis": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_analysis_seconds": round(time.perf_counter() - started, 3),
                }
            )

        if state["analysed"] % max(1, args.ui_every) == 0:
            refresh_ui()
        write_json_atomic(status_path, state)
        print(f"ANALYSE {index}/{len(audios)} {audio.name}", flush=True)

    refresh_ui()
    state["phase"] = "complete"
    state["finished_at"] = datetime.now().isoformat(timespec="seconds")
    write_json_atomic(status_path, state)
    print(json.dumps(state, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
