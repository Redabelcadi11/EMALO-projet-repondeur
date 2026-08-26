"""Publish completed backfill batches to the shared operator UI cache.

This helper is deliberately read/local-write only: it observes the backfill
state and regenerates the UI JSON when a completed batch changes.  It exits
when the backfill lock disappears.  It never calls Copilote or an ERP API.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from src.runtime_paths import bootstrap_runtime_environment


PROJECT_ROOT = bootstrap_runtime_environment()
STATE_PATH = PROJECT_ROOT / "cache" / "automatic-audio-pipeline-state.json"
LOCK_PATH = PROJECT_ROOT / "cache" / "automatic-audio-pipeline.lock"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rafraichit l'UI pendant un rattrapage audio.")
    parser.add_argument("--interval", type=int, default=30, help="Intervalle de surveillance en secondes.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    interval = max(10, min(int(args.interval), 300))
    last_signature = ""
    while LOCK_PATH.exists():
        try:
            signature = f"{STATE_PATH.stat().st_mtime_ns}:{STATE_PATH.stat().st_size}"
        except OSError:
            signature = ""
        if signature and signature != last_signature:
            from generer_ui_data_prod import main as generate_prod_ui_data

            generate_prod_ui_data()
            last_signature = signature
        time.sleep(interval)

    # Publish the last completed batch as well.
    from generer_ui_data_prod import main as generate_prod_ui_data

    generate_prod_ui_data()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
