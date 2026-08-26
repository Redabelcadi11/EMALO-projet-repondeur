from __future__ import annotations

import csv
import json
import re
import os
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from src.runtime_paths import get_project_root


PROJECT_ROOT = get_project_root()
VALIDATED_CSV = PROJECT_ROOT / "resultats" / "commandes-validees" / "commandes_validees.csv"
COPILOTE_CSV = PROJECT_ROOT / "copilote" / "commandes-copilote.csv"
PROBLEM_CSV = PROJECT_ROOT / "resultats" / "commandes-problematiques" / "commandes_problematiques.csv"
OUTPUT_JSON = Path(tempfile.gettempdir()) / "projet-repondeur" / "repondeur-data-nextcloud.json"
PENDING_STATUSES = {"A_ENVOYER"}
UNSUPPORTED_UNITS = {"BID"}


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delimiter))


def _safe_order_ref(audio_source: str, fallback: str) -> str:
    stem = Path(audio_source).stem if audio_source else ""
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-_.")
    return f"NC-{stem[:64]}" if stem else fallback


def is_nextcloud_order_ref(order_ref: str) -> bool:
    return (order_ref or "").strip().upper().startswith("NC-")


def normalize_status(value: str) -> str:
    return (value or "").strip().upper()


def is_supported_product_row(row: dict[str, str]) -> bool:
    return (row.get("unit") or "").strip().upper() not in UNSUPPORTED_UNITS


def build_orders_from_validated(rows: list[dict[str, str]]) -> dict[str, dict]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        source = (row.get("audio_source") or "").strip()
        if source:
            grouped[source].append(row)

    orders: dict[str, dict] = {}
    for index, (source, lines) in enumerate(
        sorted(grouped.items(), key=lambda item: ((item[1][0].get("run_id") or ""), item[0]))
    , start=1):
        first = lines[0]
        order_ref = _safe_order_ref(source, f"NC-{index:03d}")
        orders[order_ref] = {
            "order_ref": order_ref,
            "source_audio": source,
            "run_id": first.get("run_id", ""),
            "client": first.get("client_nom", ""),
            "client_code": first.get("client_code", ""),
            "date_livraison": first.get("date_livraison", ""),
            "statut": "A_ENVOYER",
            "copilote_numero": "",
            "message": "Extrait des audios Nextcloud",
            "products": [
                {
                    "product_code": line.get("code_article", ""),
                    "product_label": line.get("libelle_article", ""),
                    "quantity": line.get("quantite", ""),
                    "unit": line.get("unite", ""),
                    "statut": "A_ENVOYER",
                }
                for line in sorted(lines, key=lambda item: int(item.get("ordre_ligne") or 0))
            ],
        }
    return orders


def build_orders(rows: list[dict[str, str]], validated_rows: list[dict[str, str]]) -> list[dict]:
    validated_map = build_orders_from_validated(validated_rows)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        order_ref = (row.get("order_ref") or "").strip()
        if order_ref:
            grouped[order_ref].append(row)

    orders = []
    for order_ref, lines in sorted(grouped.items(), key=lambda item: item[0]):
        statuses = [normalize_status(line.get("statut", "")) for line in lines]
        if not statuses or not all(status in PENDING_STATUSES for status in statuses):
            continue
        if not all(is_supported_product_row(line) for line in lines):
            continue

        if order_ref in validated_map:
            base = validated_map[order_ref]
            first = lines[0]
            orders.append(
                {
                    **base,
                    "statut": first.get("statut", "") or base.get("statut", ""),
                    "copilote_numero": first.get("copilote_numero", "") or base.get("copilote_numero", ""),
                    "message": first.get("message", "") or base.get("message", ""),
                    "products": [
                        {
                            "product_code": line.get("product_code", ""),
                            "product_label": line.get("product_label", ""),
                            "quantity": line.get("quantity", ""),
                            "unit": line.get("unit", ""),
                            "statut": line.get("statut", ""),
                        }
                        for line in lines
                    ],
                }
            )
            continue

        first = lines[0]
        orders.append(
            {
                "order_ref": order_ref,
                "source_audio": "CSV manuel" if not is_nextcloud_order_ref(order_ref) else "",
                "run_id": "",
                "client": first.get("client", ""),
                "client_code": first.get("client_code", ""),
                "date_livraison": first.get("date_livraison", ""),
                "statut": first.get("statut", ""),
                "copilote_numero": first.get("copilote_numero", ""),
                "message": first.get("message", "") or "Commande issue du CSV Copilote",
                "products": [
                    {
                        "product_code": line.get("product_code", ""),
                        "product_label": line.get("product_label", ""),
                        "quantity": line.get("quantity", ""),
                        "unit": line.get("unit", ""),
                        "statut": line.get("statut", ""),
                    }
                    for line in lines
                ],
            }
        )

    for order_ref, order in validated_map.items():
        if order_ref not in grouped:
            if not all(is_supported_product_row(product) for product in order.get("products", [])):
                continue
            orders.append(order)
    return sorted(orders, key=lambda item: item["order_ref"])


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$content = [Console]::In.ReadToEnd(); "
        "[System.IO.File]::WriteAllText($env:REPONDEUR_OUTPUT_PATH, $content, "
        "[System.Text.UTF8Encoding]::new($false))"
    )
    env = os.environ.copy()
    env["REPONDEUR_OUTPUT_PATH"] = str(path)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        input=content,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip() or f"Ecriture impossible: {path}")


def main() -> int:
    validated_rows = read_csv(VALIDATED_CSV, delimiter=";")
    copilote_rows = read_csv(COPILOTE_CSV)
    payload = {
        "orders": build_orders(copilote_rows, validated_rows),
        "problematic": read_csv(PROBLEM_CSV, delimiter=";"),
        "paths": {
            "project": str(PROJECT_ROOT),
            "validated_csv": str(VALIDATED_CSV),
            "copilote_csv": str(COPILOTE_CSV),
            "problem_csv": str(PROBLEM_CSV),
        },
    }
    write_text(OUTPUT_JSON, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"UI data written: {OUTPUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
