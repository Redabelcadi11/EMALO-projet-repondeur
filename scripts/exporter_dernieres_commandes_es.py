#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


COLONNES = [
    "search_date", "order_number", "command_ik", "operator",
    "client_code", "client_label", "order_date", "departure_date",
    "delivery_date", "article_code", "designation", "quantity", "unit",
    "quantity_billed", "unit_billed", "source", "error", "source_export",
]


def _date(valeur: Any) -> date:
    texte = str(valeur or "").strip()[:10]
    try:
        return date.fromisoformat(texte)
    except ValueError:
        return date.min


def _numero(valeur: Any) -> int:
    try:
        return int(str(valeur or "").strip())
    except ValueError:
        return -1


def charger_versions(dossier: Path, sortie: Path) -> dict[str, list[dict[str, str]]]:
    versions: dict[str, list[tuple[tuple[Any, ...], list[dict[str, str]]]]] = defaultdict(list)
    for chemin in sorted(dossier.glob("*.csv")):
        if chemin.resolve() == sortie.resolve():
            continue
        try:
            with chemin.open("r", encoding="utf-8-sig", newline="") as fichier:
                lecteur = csv.DictReader(fichier, delimiter=";")
                if not lecteur.fieldnames or not {
                    "order_number", "operator"
                }.issubset(lecteur.fieldnames):
                    continue
                lignes_par_commande: dict[str, list[dict[str, str]]] = defaultdict(list)
                for ligne in lecteur:
                    if str(ligne.get("operator") or "").strip().upper() != "ES":
                        continue
                    numero = str(ligne.get("order_number") or "").strip()
                    if numero:
                        lignes_par_commande[numero].append(dict(ligne))
        except (OSError, UnicodeError, csv.Error):
            continue

        for numero, lignes in lignes_par_commande.items():
            premiere = lignes[0]
            cle_version = (
                _date(premiere.get("order_date")),
                _date(premiere.get("search_date")),
                _date(premiere.get("departure_date")),
                chemin.stat().st_mtime,
            )
            for ligne in lignes:
                ligne["source_export"] = chemin.name
            versions[numero].append((cle_version, lignes))

    return {
        numero: max(candidats, key=lambda candidat: candidat[0])[1]
        for numero, candidats in versions.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exporte les N dernieres commandes uniques de l'operateur ES."
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    versions = charger_versions(args.source_dir, args.output)
    commandes = sorted(
        versions.items(),
        key=lambda item: (
            _date(item[1][0].get("order_date")),
            _numero(item[0]),
        ),
        reverse=True,
    )[: max(1, args.limit)]
    if len(commandes) < args.limit:
        raise RuntimeError(
            f"Seulement {len(commandes)} commandes ES uniques disponibles, "
            f"{args.limit} demandees."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as fichier:
        writer = csv.DictWriter(
            fichier,
            fieldnames=COLONNES,
            delimiter=";",
            extrasaction="ignore",
        )
        writer.writeheader()
        for _, lignes in commandes:
            writer.writerows(lignes)

    dates = [_date(lignes[0].get("order_date")) for _, lignes in commandes]
    resume = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "operator": "ES",
        "unique_orders": len(commandes),
        "lines": sum(len(lignes) for _, lignes in commandes),
        "date_from": min(dates).isoformat(),
        "date_to": max(dates).isoformat(),
        "newest_order_number": commandes[0][0],
        "oldest_order_number": commandes[-1][0],
        "output": str(args.output.resolve()),
    }
    resume_path = args.output.with_suffix(".json")
    resume_path.write_text(
        json.dumps(resume, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(resume, ensure_ascii=False, indent=2))
    print(f"SUMMARY={resume_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
