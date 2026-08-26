#!/usr/bin/env python3
"""Exporte une prediction gelee en rapport Markdown lisible dans l'UI/TSE."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def esc(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.predictions.read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    lines = [
        "# Réanalyse des commandes — transcriptions gelées",
        "",
        f"- Audios : {len(rows)}",
        f"- Mode : {data.get('prediction_mode', '')}",
        f"- Vérité ERP reçue par le prédicteur : {data.get('truth_received_by_predictor')}",
        f"- Écriture ERP tentée : {data.get('erp_write_attempted')}",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        lines.extend([
            f"## {index}. {row.get('audio', '')}",
            "",
            f"- Client : `{row.get('client_code') or 'NON_RECONNU'}` — {row.get('client_name', '')}",
            f"- Statut : `{row.get('status', '')}`",
            f"- Livraison : {row.get('delivery_date', '')}",
            "",
            "### Transcription",
            "",
            str(row.get('transcription') or "*(absente)*"),
            "",
            "### Commande retenue",
            "",
        ])
        command_lines = row.get('lines') or []
        if command_lines:
            lines.extend(["| Code | Produit | Quantité | Unité | Entendu |", "|---|---|---:|---|---|"])
            for item in command_lines:
                lines.append(
                    f"| {esc(item.get('code'))} | {esc(item.get('label'))} | "
                    f"{esc(item.get('quantity'))} | {esc(item.get('unit'))} | "
                    f"{esc(item.get('source_text'))} |"
                )
        else:
            lines.append("*(Aucune ligne retenue)*")
        if row.get('error'):
            lines.extend(["", f"Erreur : `{esc(row['error'])}`"])
        lines.append("")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
