"""Reanalyse des audios précis après la fin du pipeline automatique actif.

Le script ne produit que des propositions locales ``A_ENVOYER`` et refuse de
démarrer si le verrou central ERP n'est plus en mode évaluation.
"""

from __future__ import annotations

import argparse
import json
import time

from src.erp_safety import erp_safety_status
from src.runtime_paths import bootstrap_runtime_environment


PROJECT_ROOT = bootstrap_runtime_environment()
PIPELINE_LOCK = PROJECT_ROOT / "cache" / "automatic-audio-pipeline.lock"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_keys", nargs="+")
    args = parser.parse_args()

    while PIPELINE_LOCK.exists():
        time.sleep(15)

    safety = erp_safety_status()
    if (
        safety.writes_allowed
        or not safety.evaluation_lock
        or safety.mode != "evaluation"
    ):
        raise RuntimeError("Réanalyse refusée : verrou ERP non conforme")

    from prod_pipeline import run_selected_audios_pipeline
    from generer_ui_data_prod import main as generate_prod_ui_data

    result = run_selected_audios_pipeline(
        args.audio_keys,
        max_new_transcriptions=None,
        preserve_existing_queue=True,
    )
    generate_prod_ui_data()
    print(json.dumps({**result, "erp_writes": False}, ensure_ascii=False))
    return 0 if int(result.get("audios") or 0) == len(args.audio_keys) else 1


if __name__ == "__main__":
    raise SystemExit(main())
