#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Objet JSON attendu: {path}")
    return payload


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
        try:
            os.chmod(temporary_name, 0o644)
        except OSError:
            pass
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def build_manifest(
    corpus: dict[str, Any],
    transcriptions: Path,
    splits: set[str] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    seen_audio: set[str] = set()
    seen_stems: set[str] = set()
    for source in corpus.get("rows") or []:
        split = str(source.get("split") or "unspecified")
        if splits is not None and split not in splits:
            continue
        audio = str(source.get("audio") or "")
        if not audio or Path(audio).name != audio:
            raise ValueError(f"Nom audio invalide: {audio!r}")
        stem = Path(audio).stem
        if audio in seen_audio or stem in seen_stems:
            raise ValueError(f"Audio ou stem duplique: {audio}")
        transcript = transcriptions / f"{stem}__transcription.json"
        if not transcript.is_file():
            raise FileNotFoundError(transcript)
        rows.append(
            {
                "audio": audio,
                "transcription_sha256": _sha256(transcript),
            }
        )
        seen_audio.add(audio)
        seen_stems.add(stem)
    rows.sort(key=lambda row: row["audio"])
    identity = hashlib.sha256(
        "\n".join(row["audio"] for row in rows).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "emalo-evaluation-input/v1",
        "dataset_id": identity,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Produit un manifeste sans verite ERP pour le predicteur."
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--transcriptions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--splits",
        default="",
        help="Liste separee par des virgules; vide signifie tous les splits.",
    )
    args = parser.parse_args()
    splits = {item.strip() for item in args.splits.split(",") if item.strip()}
    manifest = build_manifest(
        _read_json(args.corpus), args.transcriptions, splits or None
    )
    _atomic_json(args.output, manifest)
    print(json.dumps({key: value for key, value in manifest.items() if key != "rows"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
