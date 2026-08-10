from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import worker_client
from src.runtime_paths import get_project_root


PROJECT_ROOT = get_project_root()
AUDIO_ROOT = PROJECT_ROOT / "ressources-originales" / "audio-nextcloud"
AUDIO_EXTENSIONS = {".ogg", ".mp3", ".wav", ".m4a", ".webm", ".flac", ".mp4", ".mpeg", ".mpga"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark strictement distant, sans envoi Copilote."
    )
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--audio", action="append", default=[])
    parser.add_argument("--transcription-only", action="store_true")
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--output")
    return parser.parse_args()


def select_audios(arguments: argparse.Namespace) -> list[Path]:
    if arguments.audio:
        audios = [Path(value).expanduser().resolve() for value in arguments.audio]
    else:
        audios = sorted(
            (
                path
                for path in AUDIO_ROOT.rglob("*")
                if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
            ),
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )[: max(0, arguments.count)]
    if len(audios) != arguments.count:
        raise RuntimeError(
            f"{arguments.count} audios requis, {len(audios)} selectionnes."
        )
    for audio in audios:
        if not audio.exists():
            raise FileNotFoundError(audio)
    return audios


def main() -> int:
    arguments = parse_args()
    health = worker_client.remote_health()
    if not health.get("ok"):
        raise RuntimeError("Instance distante indisponible")

    audios = select_audios(arguments)
    rows: list[dict[str, Any]] = []
    force = not arguments.reuse
    for index, audio in enumerate(audios, start=1):
        started = time.perf_counter()
        if arguments.transcription_only:
            result = worker_client.remote_transcribe_audio(audio, force=force)
        else:
            result = worker_client.remote_analyze_audio(audio, force=force)
        elapsed = round(time.perf_counter() - started, 3)
        if not result.get("ok"):
            raise RuntimeError(f"{audio.name}: {result.get('message', 'erreur worker')}")

        worker_client.write_remote_transcription(audio, result)
        commandes = result.get("commandes") if isinstance(result.get("commandes"), list) else []
        if commandes:
            from prod_pipeline import persist_analysis_details

            persist_analysis_details(commandes)
        row = {
            "index": index,
            "audio": audio.name,
            "bytes": audio.stat().st_size,
            "transcription_seconds": float(result.get("transcription_seconds") or 0.0),
            "analysis_seconds": float(result.get("analysis_seconds") or 0.0),
            "model_load_seconds": float(result.get("model_load_seconds") or 0.0),
            "worker_total_seconds": float(result.get("worker_total_seconds") or 0.0),
            "client_elapsed_seconds": elapsed,
            "command_count": len(commandes),
            "transcription_reused": bool(result.get("transcription_reused")),
        }
        rows.append(row)
        print(
            f"[{index}/{len(audios)}] {audio.name}: "
            f"transcription={row['transcription_seconds']:.3f}s, "
            f"analyse={row['analysis_seconds']:.3f}s, "
            f"total_vm={row['worker_total_seconds']:.3f}s"
        )

    transcription_times = [row["transcription_seconds"] for row in rows]
    report = {
        "generated_at": datetime.now().isoformat(),
        "worker": health,
        "count": len(rows),
        "force_transcription": force,
        "creation_commande_remote": not arguments.transcription_only,
        "copilote_send_attempted": False,
        "average_transcription_seconds": round(statistics.fmean(transcription_times), 3),
        "audios": rows,
    }
    output = (
        Path(arguments.output).expanduser().resolve()
        if arguments.output
        else PROJECT_ROOT
        / "resultats"
        / "benchmarks"
        / f"benchmark_vm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Moyenne transcription: {report['average_transcription_seconds']:.3f}s")
    print(f"Rapport: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
