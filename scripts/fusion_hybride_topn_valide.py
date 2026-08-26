#!/usr/bin/env python3
"""
Exp25 - Arbitrage Top-N discipline sur les lignes deterministes ambigues.

Diagnostic Exp24 vs Exp21 (voir ANTIGRAVITY_HANDOFF.md, section Exp22-25) :

1. fusion_hybride_topn.py (Exp24) reconstruisait row["lines"] uniquement a
   partir de diagnostics.products. Cela supprimait silencieusement les
   lignes additives cadencier-selectives de fusion_hybride_additive.py
   (Exp18b/20/21), qui sont la seule source du gain de rappel record
   d'Exp21. Consequence : rappel reference 59.61% -> 56.27%, rappel ligne
   exacte 53.20% -> 49.58%.
2. fusion_hybride_topn.py recalculait un statut "reliable" maison a partir
   des seules origines de lignes retenues. Une ligne supprimee (reponse
   Llama "AUCUN") n'etait jamais ajoutee a la liste finale, donc ne pouvait
   jamais faire echouer le test all(...) de fiabilite : la suppression
   silencieuse d'une ligne etait donc comptee comme un signe de fiabilite
   plutot que comme une commande potentiellement incomplete. Cela a fait
   grimper automatic_acceptance_rate de 51.16% (Exp21, calcule par le
   determiner_statut_commande deja valide) a 97.67% (Exp24) sans gain de
   justesse reelle proportionnel (order_content_accuracy = 16.28% seulement).
3. Quand Llama proposait un nouveau code pour une ligne ambigue, la
   quantite/unite deterministe de l'ancien candidat etait recopiee telle
   quelle sur le nouveau code, sans revalidation face au conditionnement
   officiel de ce nouveau code. Exemple mesure : "vinaigre bals[amique]"
   ambigu, candidats offerts au LLM ne contenant pas le bon code
   (00051270), Llama choisit par defaut 00051265 (vinaigre de xeres, deja
   present ailleurs dans la commande) -> doublon de code avec une
   quantite/unite non revalidee -> nouvelle cause unite_conditionnement
   (0 -> 9 occurrences) et quantite (16 -> 18).

Correctifs appliques dans ce script (Exp25) :

1. Ce script s'applique en TROISIEME couche, apres la fusion additive
   cadencier-selective deja validee (fusion_hybride_additive.py). Il ne
   reconstruit jamais row["lines"] a partir de zero : il ne modifie que les
   lignes issues de produits deterministes marques ambigus
   (produit_fiable=False) dans diagnostics.products, et laisse toutes les
   autres lignes (deterministes fiables + additions Llama cadencier-
   selectives) strictement intactes.
2. row["status"] n'est jamais recalcule ici : il reste exactement celui
   deja calcule par extraire_informations.determiner_statut_commande.
   automatic_acceptance_rate ne peut donc plus etre gonfle par ce script -
   une suppression de ligne ne peut plus se traduire en une hausse
   artificielle de l'acceptation automatique.
3. Toute proposition de remplacement Llama est revalidee par
   valider_candidat_llama (le meme filtre selectif deja valide d'Exp18b,
   importe depuis fusion_hybride_additive.py) : autorite du referentiel/
   unite officielle pour le NOUVEAU code (recalcul, pas de recopie),
   bornes de quantite, anti-doublon contre les autres lignes deja
   retenues, incompatibilites semantiques, seuil de chevauchement lexical
   cadencier-conscient (>=50 dans le cadencier client, >=75 hors
   cadencier). Une proposition qui ne passe pas ce filtre est ignoree et
   l'etat deterministe existant (ligne conservee ou deja absente) reste
   inchange.
4. Une reponse Llama "AUCUN" ne supprime une ligne deterministe ambigue
   deja retenue comme meilleure estimation que s'il n'existe aucun
   remplacement valide pour cette meme clause vocale. Cette suppression
   reste possible (c'est le mecanisme qui a produit les 2 nouvelles
   commandes parfaites d'Exp24 en eliminant un faux produit), mais elle
   n'influence jamais le statut de la commande.

Aucune verite ERP n'est fournie a ce script ni au LLM. Aucune ecriture ERP.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import urllib.request

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import extraire_informations as extraction  # noqa: E402
from fusion_hybride_additive import (  # noqa: E402
    charger_referentiel,
    charger_unites_officielles,
    valider_candidat_llama,
    _normaliser_texte,
)
from src.produits import SEUIL_PRODUIT_MIN  # noqa: E402

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"


def call_ollama(prompt: str, timeout: int = 120) -> str:
    payload = {
        "model": "llama3.1:70b",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "seed": 0},
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response).get("response", "")


def build_prompt(transcription: str, texte_source: str, candidats: list) -> str:
    prompt = (
        "Tu es un expert metier pour un fournisseur alimentaire (EMALO).\n"
        "Un client a passe une commande vocale. Le systeme a isole un extrait de "
        "la transcription qui correspond a un produit, mais hesite entre "
        "plusieurs candidats de son catalogue.\n\n"
        f'TRANSCRIPTION COMPLETE DU CLIENT :\n"{transcription}"\n\n'
        f'EXTRAIT SPECIFIQUE A ANALYSER :\n"{texte_source}"\n\n'
        "CANDIDATS POSSIBLES DU CATALOGUE :\n"
    )
    for i, c in enumerate(candidats, start=1):
        prompt += f"{i}. Code: {c.get('code_article')} | Libelle: {c.get('libelle_article')}\n"
    prompt += (
        "\nTA MISSION :\n"
        "Analyse le contexte de la transcription et l'extrait specifique, puis "
        "choisis LE MEILLEUR candidat parmi la liste.\n"
        "Si l'extrait correspond de maniere evidente a l'un des candidats, "
        "renvoie UNIQUEMENT le Code du produit sous ce format exact :\n"
        "CODE: <code_article>\n\n"
        "Si aucun candidat ne correspond du tout a l'extrait (c'est-a-dire si "
        "le systeme s'est trompe en isolant cet extrait, ou que le client "
        "parle d'autre chose), renvoie exactement :\n"
        "CODE: AUCUN\n"
    )
    return prompt


def parse_chosen_code(response_text: str) -> str | None:
    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("CODE:"):
            return line.split("CODE:", 1)[1].strip()
    return None


def traiter_ligne(
    prod: dict,
    lignes: list[dict],
    transcription: str,
    transcription_norm: str,
    codes_cadencier: set[str],
    referentiel: dict,
    unites_officielles: dict,
    stats: dict,
) -> None:
    selection = prod.get("selection")
    if not selection or prod.get("produit_fiable"):
        return

    source_text = str(prod.get("texte_source") or "")
    source_norm = _normaliser_texte(source_text)
    if not source_norm:
        return

    candidats = prod.get("candidats") or []
    if not candidats:
        return

    idx_existant = None
    for i, l in enumerate(lignes):
        if _normaliser_texte(str(l.get("source_text") or "")) == source_norm:
            idx_existant = i
            break

    top10 = candidats[:10]
    prompt = build_prompt(transcription, source_text, top10)
    try:
        response_text = call_ollama(prompt)
    except Exception as exc:  # reseau/timeout : ne rien changer
        stats["erreurs_appel"] += 1
        print(f"  Erreur appel Llama (ignoree, etat inchange): {exc}")
        return

    chosen_code = parse_chosen_code(response_text)
    stats["appels"] += 1

    remplacement_valide = None
    if chosen_code and chosen_code != "AUCUN":
        chosen = next(
            (c for c in top10 if str(c.get("code_article")) == chosen_code), None
        )
        if chosen:
            candidat_dict = {
                "code": chosen_code,
                "quantity": prod.get("quantite_resolue"),
                "unit": prod.get("unite_resolue"),
                "label": chosen.get("libelle_article"),
                "source_text": source_text,
            }
            code_norm = chosen_code.lstrip("0")
            dans_cad = code_norm in codes_cadencier
            autres_lignes = [l for j, l in enumerate(lignes) if j != idx_existant]
            remplacement_valide = valider_candidat_llama(
                candidat_dict,
                transcription_norm,
                dans_cad,
                autres_lignes,
                referentiel,
                unites_officielles,
            )

    if remplacement_valide:
        remplacement_valide["origine"] = "llama_topn_valide"
        if idx_existant is not None:
            lignes[idx_existant] = remplacement_valide
            stats["remplacements"] += 1
        else:
            lignes.append(remplacement_valide)
            stats["ajouts"] += 1
    elif chosen_code == "AUCUN" and idx_existant is not None:
        # Ne pas laisser un "AUCUN" du LLM ecraser une ligne que le moteur
        # deterministe avait deja score au-dessus de son propre seuil de
        # confiance etabli (SEUIL_PRODUIT_MIN, deja valide dans
        # src/produits.py). En dessous de ce seuil, le LLM corrobore une
        # incertitude deja presente et la suppression reste autorisee
        # (c'est ce mecanisme qui a produit les 2 nouvelles commandes
        # parfaites d'Exp24, toutes deux tres en dessous du seuil).
        score_actuel = float((selection or {}).get("score_global") or 0.0)
        if score_actuel < SEUIL_PRODUIT_MIN:
            del lignes[idx_existant]
            stats["suppressions"] += 1
        else:
            stats["suppressions_evitees_score_suffisant"] += 1
    # sinon : aucun changement, l'etat deterministe (present ou absent) reste inchange


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=None, help="Limiter aux N premiers audios (smoke test)")
    args = parser.parse_args()

    racine = PROJECT_ROOT
    referentiel = charger_referentiel(racine)
    unites_officielles = charger_unites_officielles(racine)
    cadencier_clients = extraction.charger_cadencier()

    data = json.loads(args.predictions.read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    if args.limit:
        rows = rows[: args.limit]

    stats = {
        "appels": 0,
        "erreurs_appel": 0,
        "remplacements": 0,
        "ajouts": 0,
        "suppressions": 0,
        "suppressions_evitees_score_suffisant": 0,
    }

    for row_idx, row in enumerate(rows, start=1):
        client_code = str(row.get("client_code") or "").strip().upper()
        cadencier_client = cadencier_clients.get(client_code, [])
        codes_cadencier = {
            str(a.get("code_article") or "").strip().lstrip("0") for a in cadencier_client
        }

        diag = row.get("diagnostics", {}) or {}
        products = diag.get("products", []) or []
        transcription = row.get("transcription") or ""
        transcription_norm = _normaliser_texte(transcription)

        lignes = list(row.get("lines", []))
        avant = len(lignes)

        for prod in products:
            traiter_ligne(
                prod,
                lignes,
                transcription,
                transcription_norm,
                codes_cadencier,
                referentiel,
                unites_officielles,
                stats,
            )

        row["lines"] = lignes
        # row["status"] volontairement non touche.
        print(
            f"[{row_idx}/{len(rows)}] {row.get('audio')}: {avant} -> {len(lignes)} lignes"
        )

    data["rows"] = rows
    data["prediction_mode"] = "hybrid_additive_topn_valide_exp25"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("--- Statistiques Exp25 ---")
    print(stats)
    print(f"Sauvegarde: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
