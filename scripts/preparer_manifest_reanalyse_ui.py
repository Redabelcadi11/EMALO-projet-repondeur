#!/usr/bin/env python3
"""Prepare un manifeste sans cible ERP depuis des resultats UI existants."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extractions", type=Path, required=True)
    parser.add_argument("--transcriptions", type=Path, required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    since_input = datetime.fromisoformat(str(args.since).replace("Z", "+00:00"))
    if since_input.tzinfo is not None:
        since = since_input.timestamp()
    else:
        since = since_input.replace(tzinfo=timezone.utc).timestamp()

    rows: list[dict[str, str]] = []
    for extraction in sorted(args.extractions.glob("*__extraction.json")):
        if extraction.stat().st_mtime < since:
            continue
        stem = extraction.name.removesuffix("__extraction.json")
        transcription = args.transcriptions / f"{stem}__transcription.json"
        if transcription.is_file():
            rows.append({
                "audio": f"{stem}.wav",
                "transcription_sha256": sha256(transcription),
            })

    payload = {
        "schema": "emalo-evaluation-input/v1",
        "dataset_id": args.dataset_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"row_count": len(rows), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
