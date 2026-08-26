#!/usr/bin/env python3
"""Transcrit un lot via le worker local uniquement.

Ce client ne connait aucun endpoint ERP. L'URL est volontairement limitee a
la boucle locale afin qu'un lot d'evaluation ne puisse pas quitter l'instance.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import tempfile
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


EXTENSIONS_AUDIO = {".wav", ".mp3", ".ogg", ".m4a", ".flac", ".webm"}


def _date_from_name(name: str) -> date | None:
    try:
        return date.fromisoformat(name[:10])
    except ValueError:
        return None


def select_audio_files(root: Path, date_from: date, date_to: date) -> list[Path]:
    return sorted(
        path
        for path in root.iterdir()
        if path.is_file()
        and path.suffix.casefold() in EXTENSIONS_AUDIO
        and (audio_date := _date_from_name(path.name)) is not None
        and date_from <= audio_date <= date_to
    )


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


def assert_loopback_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Le worker de lot doit rester sur la boucle locale.")
    if parsed.path.rstrip("/") != "/transcribe":
        raise ValueError("Endpoint local de transcription invalide.")


def transcribe_one(endpoint: str, audio: Path, force: bool) -> dict[str, Any]:
    payload = json.dumps(
        {
            "audio_name": audio.name,
            "audio_base64": base64.b64encode(audio.read_bytes()).decode("ascii"),
            "force": force,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3600) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"worker_http_{exc.code}: {body[:2000]}") from exc
    if not result.get("ok"):
        raise RuntimeError(str(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcription GPU par lot via le worker local.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--date-from", type=date.fromisoformat, required=True)
    parser.add_argument("--date-to", type=date.fromisoformat, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8787/transcribe")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    assert_loopback_endpoint(args.endpoint)
    files = select_audio_files(args.input_dir, args.date_from, args.date_to)
    if not files:
        raise RuntimeError("Aucun audio dans le perimetre demande.")

    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema": "emalo-transcription-batch/v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "date_from": args.date_from.isoformat(),
        "date_to": args.date_to.isoformat(),
        "audio_count": len(files),
        "completed": 0,
        "failed": 0,
        "rows": [],
    }
    _atomic_json(args.report, report)
    consecutive_failures = 0
    for index, audio in enumerate(files, start=1):
        item_started = time.perf_counter()
        try:
            result = transcribe_one(args.endpoint, audio, args.force)
            row = {
                "audio": audio.name,
                "ok": True,
                "transcription_seconds": result.get("transcription_seconds"),
                "worker_total_seconds": result.get("worker_total_seconds"),
                "model_load_seconds": result.get("model_load_seconds"),
                "reused": result.get("transcription_reused"),
                "model": (result.get("transcription_json") or {}).get("modele"),
                "device": (result.get("transcription_json") or {}).get("appareil"),
                "compute_type": (result.get("transcription_json") or {}).get("type_calcul"),
            }
            report["completed"] += 1
            consecutive_failures = 0
        except Exception as exc:
            row = {
                "audio": audio.name,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_seconds": round(time.perf_counter() - item_started, 3),
            }
            report["failed"] += 1
            consecutive_failures += 1
        report["rows"].append(row)
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        _atomic_json(args.report, report)
        print(
            f"AUDIO={index}/{len(files)} OK={row['ok']} "
            f"SECONDS={row.get('worker_total_seconds', row.get('elapsed_seconds', 0))}",
            flush=True,
        )
        if consecutive_failures >= 3:
            report["aborted"] = "trois_echecs_consecutifs"
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            _atomic_json(args.report, report)
            print("ABORTED=trois_echecs_consecutifs", flush=True)
            return 2
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    _atomic_json(args.report, report)
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}))
    return 0 if report["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
