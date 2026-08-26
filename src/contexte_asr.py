from __future__ import annotations

"""Façade ASR: meilleure couverture des références rares et attributs décisifs."""

import re
from typing import Any

from . import _contexte_asr_legacy as _legacy

_ORIGINAL_CONSTRUIRE_HOTWORDS = _legacy.construire_hotwords_par_telephone

MOTIFS_ATTRIBUTS_ASR_CRITIQUES = {
    "frais": r"\b(?:frais|fraiche|fraiches)\b",
    "surgele": r"\bsurgele(?:e|es|s)?\b",
    "congele": r"\bcongele(?:e|es|s)?\b",
    "cru": r"\bcru(?:e|es|s)?\b",
    "cuit": r"\bcuit(?:e|es|s)?\b",
    "rape": r"\brape(?:e|es|s)?\b",
    "entier": r"\bentier(?:e|es|s)?\b",
    "demi ecreme": r"\b(?:demi|1\s*2)\s+ecreme(?:e|es|s)?\b",
    "ecreme": r"\becreme(?:e|es|s)?\b",
    "plein air": r"\bplein\s+air\b",
    "sans sucre": r"\bsans\s+sucre\b",
}
ATTRIBUTS_ASR_CRITIQUES = tuple(MOTIFS_ATTRIBUTS_ASR_CRITIQUES)


def _telephone_normalise(valeur: Any) -> str:
    chiffres = re.sub(r"\D+", "", str(valeur or ""))
    if chiffres.startswith("0033") and len(chiffres) >= 12:
        return "0" + chiffres[4:]
    if chiffres.startswith("33") and len(chiffres) >= 11:
        return "0" + chiffres[2:]
    return chiffres


def _dedupe_termes(termes: list[str], limite: int) -> list[str]:
    resultat: list[str] = []
    vus: set[str] = set()
    for terme in termes:
        propre = str(terme or "").strip()
        cle = _legacy._normaliser_token(propre)
        if not cle or cle in vus:
            continue
        vus.add(cle)
        resultat.append(propre)
        if len(resultat) >= max(1, limite):
            break
    return resultat


def construire_hotwords_par_telephone(
    clients: list[dict[str, Any]],
    cadencier: dict[str, list[dict[str, Any]]],
    synonymes_produits: dict[str, list[str]] | None = None,
    limite_termes: int = 240,
) -> dict[str, str]:
    """Réserve de la place aux produits rares sans abandonner le contexte client."""
    base = _ORIGINAL_CONSTRUIRE_HOTWORDS(
        clients,
        cadencier,
        synonymes_produits=synonymes_produits,
        limite_termes=max(480, limite_termes),
    )

    clients_par_tel: dict[str, dict[str, Any]] = {}
    for client in clients:
        for telephone in (
            list(client.get("telephones", []) or [])
            + list(client.get("telephones_confirmes", []) or [])
        ):
            tel = _telephone_normalise(telephone)
            if tel:
                clients_par_tel[tel] = client

    resultat: dict[str, str] = {}
    for telephone, chaine in base.items():
        termes_base = [
            terme.strip()
            for terme in str(chaine or "").split(",")
            if terme.strip()
        ]
        client = clients_par_tel.get(_telephone_normalise(telephone))
        if not client:
            resultat[telephone] = ", ".join(
                _dedupe_termes(termes_base, limite_termes)
            )
            continue

        code_client = str(client.get("code_client") or "").strip()
        produits = list(cadencier.get(code_client, []) or [])

        libelles_normalises = " ".join(
            _legacy._normaliser_token(
                str(produit.get("libelle_article") or "")
            )
            for produit in produits
        )
        attributs = [
            canonique
            for canonique, motif in MOTIFS_ATTRIBUTS_ASR_CRITIQUES.items()
            if re.search(motif, libelles_normalises)
        ]

        produits_rares = sorted(
            produits,
            key=lambda produit: (
                int(produit.get("nb_ventes_article_total", 0) or 0),
                int(produit.get("nb_ventes_article_recentes", 0) or 0),
                str(produit.get("libelle_article") or ""),
            ),
        )
        phrases_rares = [
            phrase
            for produit in produits_rares[:96]
            if (
                phrase := _legacy._phrase_distinctive_produit(
                    produit.get("libelle_article")
                )
            )
        ]

        ordonnes = [
            *termes_base[:20],
            *attributs,
            *phrases_rares,
            *termes_base[20:],
        ]
        resultat[telephone] = ", ".join(
            _dedupe_termes(ordonnes, limite_termes)
        )

    return resultat


_legacy.construire_hotwords_par_telephone = construire_hotwords_par_telephone

for _nom in dir(_legacy):
    if _nom.startswith("__"):
        continue
    globals()[_nom] = getattr(_legacy, _nom)

globals()["construire_hotwords_par_telephone"] = construire_hotwords_par_telephone
globals()["ATTRIBUTS_ASR_CRITIQUES"] = ATTRIBUTS_ASR_CRITIQUES
globals()["MOTIFS_ATTRIBUTS_ASR_CRITIQUES"] = MOTIFS_ATTRIBUTS_ASR_CRITIQUES
