#!/usr/bin/env python3
"""
Exp25c - Recalcul honnete du statut apres les corrections de Layer C.

fusion_hybride_topn_valide.py (Exp25/25b) modifie deliberement row["lines"]
sans jamais toucher row["status"], pour eviter le biais d'Exp24 (une ligne
supprimee ne doit jamais se traduire automatiquement en une hausse de
automatic_acceptance_rate). Consequence attendue et acceptee : quand Layer C
corrige une commande jusqu'a la rendre exactement correcte, son statut reste
celui, potentiellement PROBLEMATIQUE, calcule par le moteur AVANT la
correction (cause "rejet_interne_d_une_commande_correcte" mesuree dans
Exp25b).

Ce script recalcule le statut de facon honnete et minimale, en reappliquant
exactement la meme fonction de production (extraire_informations.
construire_lignes_commande) sur une copie de diagnostics.products ou seules
les mentions effectivement modifiees par Layer C sont ajustees :
- mention remplacee (origine llama_topn_valide dans les lignes finales) :
  produit_fiable force a True, ambigu a False, code/libelle/quantite/unite
  mis a jour depuis la ligne validee ;
- mention supprimee (source_text present dans la base Exp21 mais absent des
  lignes finales) : retiree de la liste avant recalcul, exactement comme si
  cette mention n'avait jamais existe.

Le statut n'est JAMAIS degrade (VALIDEE -> PROBLEMATIQUE) par ce script :
seule une amelioration (PROBLEMATIQUE -> VALIDEE) est possible, et seulement
quand construire_lignes_commande ne remonte plus aucune raison bloquante.
L'identification client n'est jamais recalculee ici (client_accuracy est
deja a 100% sur les 43 audios de developpement, donc jamais bloquante).

Aucune verite ERP n'est utilisee. Aucun appel reseau/LLM. Aucune ecriture
ERP.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import extraire_informations as extraction  # noqa: E402
from fusion_hybride_additive import _normaliser_texte  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="Base Exp21 (avant Layer C)")
    parser.add_argument("--guarded", required=True, type=Path, help="Sortie Layer C (Exp25/25b)")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    base_data = json.loads(args.base.read_text(encoding="utf-8"))
    guarded_data = json.loads(args.guarded.read_text(encoding="utf-8"))

    base_rows = {r["audio"]: r for r in base_data.get("rows", [])}
    upgrades = 0

    for row in guarded_data.get("rows", []):
        if row.get("status") == "VALIDEE":
            continue  # deja accepte, rien a ameliorer

        audio = row.get("audio")
        base_row = base_rows.get(audio)
        if not base_row:
            continue

        base_lines_by_src = {
            _normaliser_texte(str(l.get("source_text") or "")): l
            for l in base_row.get("lines", [])
            if "origine" not in l  # mentions deterministes brutes uniquement
        }
        guarded_lines_by_src = {
            _normaliser_texte(str(l.get("source_text") or "")): l
            for l in row.get("lines", [])
        }

        diag = row.get("diagnostics", {}) or {}
        produits_modifies = []
        modifie = False
        for prod in diag.get("products", []) or []:
            sel = prod.get("selection")
            if not sel or prod.get("produit_fiable"):
                produits_modifies.append(prod)
                continue

            src_norm = _normaliser_texte(str(prod.get("texte_source") or ""))
            etait_dans_base = src_norm in base_lines_by_src
            ligne_actuelle = guarded_lines_by_src.get(src_norm)

            if etait_dans_base and ligne_actuelle is None:
                # Layer C a supprime cette mention : on l'exclut du recalcul.
                modifie = True
                continue

            if ligne_actuelle is not None and ligne_actuelle.get("origine") == "llama_topn_valide":
                nouveau_prod = dict(prod)
                nouvelle_sel = dict(sel)
                nouvelle_sel["code_article"] = ligne_actuelle.get("code")
                nouvelle_sel["libelle_article"] = ligne_actuelle.get("label")
                nouveau_prod["selection"] = nouvelle_sel
                nouveau_prod["quantite_resolue"] = ligne_actuelle.get("quantity")
                nouveau_prod["unite_resolue"] = ligne_actuelle.get("unit")
                nouveau_prod["produit_fiable"] = True
                nouveau_prod["ambigu"] = False
                produits_modifies.append(nouveau_prod)
                modifie = True
                continue

            produits_modifies.append(prod)

        if not modifie:
            continue

        lignes_commande, raisons_lignes = extraction.construire_lignes_commande(produits_modifies)
        raisons_bloquantes = [
            r
            for r in raisons_lignes
            if not r.startswith("article_duplique_consolide_")
            and not (r.startswith("quantite_absente_ligne_") and lignes_commande)
        ]
        if not lignes_commande:
            raisons_bloquantes.append("produit_non_vendu_aucune_selection")

        if row.get("client_code") and not raisons_bloquantes:
            row["status"] = "VALIDEE"
            upgrades += 1
            print(f"UPGRADE -> VALIDEE : {audio}")

    guarded_data["prediction_mode"] = "hybrid_additive_topn_valide_exp25c_status_recompute"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(guarded_data, f, ensure_ascii=False, indent=2)

    print(f"Total upgrades PROBLEMATIQUE -> VALIDEE: {upgrades}")
    print(f"Sauvegarde: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
