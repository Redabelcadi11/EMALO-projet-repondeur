from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any


MOTS_ASR_TROP_GENERIQUES = {
    "alimentaire", "article", "boite", "carton", "colis", "commande",
    "conditionne", "frais", "france", "gramme", "kilo", "piece",
    "poche", "produit", "sachet", "surgele", "unite",
}


def _normaliser_token(valeur: str) -> str:
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", valeur.lower())
        if not unicodedata.combining(caractere)
    )


def _tokens_distinctifs(valeur: Any) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for token_original in re.findall(
        r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'-]{2,}",
        str(valeur or ""),
    ):
        token = _normaliser_token(token_original).strip("'-")
        if (
            len(token) < 4
            or token in MOTS_ASR_TROP_GENERIQUES
            or token.isdigit()
        ):
            continue
        tokens.setdefault(token, token_original.strip("'-"))
    return tokens


def telephone_depuis_nom_audio(nom_audio: str) -> str:
    match = re.search(r"_De-([^_.]+)", str(nom_audio or ""), re.IGNORECASE)
    if not match:
        return ""
    chiffres = re.sub(r"\D+", "", match.group(1))
    if chiffres.startswith("0033") and len(chiffres) >= 12:
        chiffres = "0" + chiffres[4:]
    elif chiffres.startswith("33") and len(chiffres) >= 11:
        chiffres = "0" + chiffres[2:]
    return chiffres


def construire_hotwords_par_telephone(
    clients: list[dict[str, Any]],
    cadencier: dict[str, list[dict[str, Any]]],
    synonymes_produits: dict[str, list[str]] | None = None,
    limite_termes: int = 160,
) -> dict[str, str]:
    """Construit un vocabulaire ASR client sans utiliser les commandes ES."""
    articles_uniques: dict[str, dict[str, Any]] = {}
    for produits in cadencier.values():
        for produit in produits:
            code = str(produit.get("code_article") or "").strip()
            cle = code or str(produit.get("libelle_article") or "").strip()
            if cle:
                articles_uniques.setdefault(cle, produit)

    frequence_catalogue: Counter[str] = Counter()
    for produit in articles_uniques.values():
        frequence_catalogue.update(
            _tokens_distinctifs(produit.get("libelle_article")).keys()
        )

    # Les formes canoniques des synonymes sont des mots métier difficiles
    # appris hors commandes ES (txistorra, sriracha, fregola...). Elles sont
    # communes à tous les clients et placées après l'identité client mais
    # avant les qualificatifs secondaires du cadencier.
    termes_metier_globaux = [
        (500.0, str(canonique).strip())
        for canonique in (synonymes_produits or {})
        if str(canonique).strip()
    ]

    termes_par_telephone: dict[str, list[tuple[float, str]]] = {}
    for client in clients:
        code_client = str(client.get("code_client") or "").strip()
        telephones = {
            re.sub(r"\D+", "", str(telephone or ""))
            for telephone in client.get("telephones", [])
            if re.sub(r"\D+", "", str(telephone or ""))
        }
        if not telephones:
            continue

        termes_client: list[tuple[float, str]] = []
        for valeur in (
            client.get("nom_client"),
            client.get("ville"),
            *(client.get("aliases", []) or []),
        ):
            texte = str(valeur or "").strip()
            if texte:
                termes_client.append((1000.0, texte))
        termes_client.extend(termes_metier_globaux)

        meilleurs_tokens: dict[str, tuple[float, str]] = {}
        for produit in cadencier.get(code_client, []):
            recent = int(produit.get("nb_ventes_article_recentes", 0) or 0)
            total = int(produit.get("nb_ventes_article_total", 0) or 0)
            tokens_produit = _tokens_distinctifs(
                produit.get("libelle_article")
            )
            for position, (token, original) in enumerate(tokens_produit.items()):
                rarete = 30.0 / max(1, frequence_catalogue[token])
                # Le debut du libelle porte généralement le nom commande
                # (TXISTORRA, PIQUILLOS, RABAS), les marques et qualificatifs
                # venant ensuite. Cette priorite reste entierement issue du
                # cadencier, jamais des commandes ES d'evaluation.
                priorite_nom_produit = 100.0 / (position + 1)
                score = (
                    priorite_nom_produit
                    + rarete
                    + math.log1p(recent)
                    + 0.25 * math.log1p(total)
                )
                precedent = meilleurs_tokens.get(token)
                if precedent is None or score > precedent[0]:
                    meilleurs_tokens[token] = (score, original)

        termes_client.extend(meilleurs_tokens.values())
        for telephone in telephones:
            termes_par_telephone.setdefault(telephone, []).extend(termes_client)

    resultat: dict[str, str] = {}
    for telephone, termes_scores in termes_par_telephone.items():
        termes_tries = sorted(
            termes_scores,
            key=lambda item: (item[0], len(item[1])),
            reverse=True,
        )
        vus: set[str] = set()
        termes: list[str] = []
        for _, terme in termes_tries:
            cle = _normaliser_token(terme)
            if not cle or cle in vus:
                continue
            vus.add(cle)
            termes.append(terme)
            if len(termes) >= max(1, limite_termes):
                break
        if termes:
            resultat[telephone] = ", ".join(termes)
    return resultat
