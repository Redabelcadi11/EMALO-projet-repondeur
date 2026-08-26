#!/usr/bin/env python3
"""Affiche des entrées du catalogue autorisé, sans données d'évaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.arbitrer_predictions_llama_local import _load_resources
from src.llama_product_resolver import build_authorized_catalogue


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True)
    parser.add_argument("--code", action="append", required=True)
    args = parser.parse_args()

    cadencier, global_catalogue, references = _load_resources()
    client_keys = [
        key for key in cadencier
        if str(key).casefold() == str(args.client).casefold()
    ]
    client_products = cadencier.get(args.client, [])
    catalogue = build_authorized_catalogue(
        global_catalogue,
        client_products,
        references,
    )
    print(
        json.dumps(
            {
                "requested_client": args.client,
                "direct_client_product_count": len(client_products),
                "case_insensitive_client_keys": client_keys,
                "entries": {
                    code: catalogue.get(code)
                    for code in args.code
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
