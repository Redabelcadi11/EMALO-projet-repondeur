"""Analyse de diagnostic d'un seul audio via le worker GPU, sans ERP.

Ce script reutilise exactement le pipeline de production distant et ne fait
aucun appel aux modules d'ecriture Copilote. Il sert aux validations isolees
apres une modification ASR/matching.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker_client import remote_analyze_audio, write_remote_transcription


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    audio = args.audio.resolve()
    if not audio.is_file():
        raise FileNotFoundError(audio)
    result = remote_analyze_audio(audio, force=args.force)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("message") or result))
    write_remote_transcription(audio, result)

    commandes = result.get("commandes") or []
    print(json.dumps({
        "audio": audio.name,
        "transcription_seconds": result.get("transcription_seconds"),
        "analysis_seconds": result.get("analysis_seconds"),
        "commandes": commandes,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
