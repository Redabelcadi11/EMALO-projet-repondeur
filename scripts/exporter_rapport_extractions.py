#!/usr/bin/env python3
"""Exporte des extractions intermediaires en rapport Markdown lisible."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def esc(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extractions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for path in sorted(args.extractions.glob("*__extraction.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    report = ["# Réanalyse intermédiaire — pipeline UI avec Llama", "", f"- Audios terminés : {len(rows)}", ""]
    for index, row in enumerate(rows, 1):
        report.extend([
            f"## {index}. {row.get('fichier_audio', '')}", "",
            f"- Client : `{row.get('client_retenu') or 'NON_RECONNU'}` — {row.get('client_nom_retenu', '')}",
            f"- Statut : `{row.get('statut', '')}`", "", "### Transcription", "",
            str(row.get('transcription') or "*(absente)*"), "", "### Commande retenue", "",
        ])
        lines = row.get("lignes_commande") or []
        if lines:
            report.extend(["| Code | Produit | Quantité | Unité | Entendu |", "|---|---|---:|---|---|"])
            for item in lines:
                report.append(
                    f"| {esc(item.get('code_article'))} | {esc(item.get('libelle_article'))} | "
                    f"{esc(item.get('quantite'))} | {esc(item.get('unite'))} | {esc(item.get('texte_source'))} |"
                )
        else:
            report.append("*(Aucune ligne retenue)*")
        report.append("")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(report), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
