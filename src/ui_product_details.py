"""Projection UI des produits reconnus et des vrais items non identifies.

Les phrases hors commande restent masquees. En revanche, une mention dont le
noyau produit a ete prouve doit rester visible dans les details, meme si aucune
reference assez fiable n'a pu etre retenue.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


SOFT_WARNING_PREFIXES = (
    "article_duplique_consolide_",
    "produit_ambigu_ligne_",
    "produit_non_vendu_prix_zero_ligne_",
    "quantite_implicite_un_ligne_",
)


def avertissements_commande(raisons: list[Any] | None) -> list[str]:
    return sorted({
        str(raison)
        for raison in (raisons or [])
        if str(raison).startswith(SOFT_WARNING_PREFIXES)
    })


def _tokens_famille(libelle: str) -> set[str]:
    normalise = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", libelle.casefold())
        if not unicodedata.combining(caractere)
    )
    return {
        token
        for token in re.findall(r"[a-z]+", normalise)
        if len(token) >= 3
        and token not in {
            "avec", "aux", "des", "extra", "nature", "pour",
        }
    }


def _meme_famille_visible(libelle_a: str, libelle_b: str) -> bool:
    communs = _tokens_famille(libelle_a) & _tokens_famille(libelle_b)
    # Deux mots communs (SEL + GROS), ou un noyau suffisamment distinctif
    # (COULIS, PISTACHE, BURRATA...) sont necessaires pour exposer une
    # alternative. Cela evite d'afficher des rapprochements fuzzy hors famille.
    return len(communs) >= 2 or any(len(token) >= 5 for token in communs)


def projection_produit_reconnu(
    produit: dict[str, Any],
    ligne: dict[str, Any] | None,
    index: int,
) -> dict[str, Any] | None:
    selection = (
        produit.get("selection")
        if isinstance(produit.get("selection"), dict)
        else {}
    )
    reconnaissance_moteur = bool(
        produit.get(
            "produit_reconnu",
            produit.get("produit_fiable"),
        )
    )
    statut_couverture = str(
        produit.get("statut_couverture") or ""
    ).upper()
    afficher_non_identifie = statut_couverture in {
        "NON_IDENTIFIE",
        "AMBIGU",
    }
    if not reconnaissance_moteur and not afficher_non_identifie:
        return None

    ligne = ligne or {}
    code = str(
        ligne.get("code_article")
        or selection.get("code_article")
        or ""
    )
    libelle = str(
        ligne.get("libelle_article")
        or selection.get("libelle_article")
        or ""
    )
    if reconnaissance_moteur and not code:
        return None

    ambigu = bool(produit.get("ambigu"))
    raisons = sorted({
        str(raison)
        for raison in (produit.get("raisons_ambiguite") or [])
        if str(raison)
    })
    alternatives: list[dict[str, Any]] = []
    if ambigu or raisons or afficher_non_identifie:
        score_selection = float(selection.get("score_texte") or 0.0)
        seuil = max(35.0, score_selection - 20.0)
        vues: set[str] = {code} if code else set()
        candidats = sorted(
            (
                candidat
                for candidat in (produit.get("candidats") or [])
                if isinstance(candidat, dict)
                and candidat.get("semantiquement_compatible", True)
            ),
            key=lambda candidat: float(
                candidat.get("score_texte") or 0.0
            ),
            reverse=True,
        )
        for candidat in candidats:
            code_candidat = str(candidat.get("code_article") or "")
            score_candidat = float(candidat.get("score_texte") or 0.0)
            libelle_candidat = str(
                candidat.get("libelle_article") or ""
            )
            if (
                not code_candidat
                or code_candidat in vues
                or score_candidat < seuil
                or (
                    bool(libelle)
                    and not _meme_famille_visible(libelle, libelle_candidat)
                )
            ):
                continue
            vues.add(code_candidat)
            alternatives.append({
                "product_code": code_candidat,
                "product_label": libelle_candidat,
                "score": round(score_candidat, 2),
                "in_client_schedule": bool(
                    candidat.get("dans_cadencier_client")
                ),
            })
            if len(alternatives) >= 3:
                break

    quantite = (
        ligne.get("quantite")
        if ligne
        else produit.get(
            "quantite_resolue",
            produit.get("quantite_principale", ""),
        )
    )
    unite = (
        ligne.get("unite")
        if ligne
        else produit.get(
            "unite_resolue",
            produit.get("unite_principale", ""),
        )
    )
    return {
        "order": produit.get("segment_index", index),
        "segment_id": produit.get("segment_id", ""),
        "source_text": produit.get("texte_source", ""),
        "recognized": reconnaissance_moteur,
        "coverage_status": (
            statut_couverture
            or ("RECONNU" if reconnaissance_moteur else "NON_IDENTIFIE")
        ),
        "request_modality": str(
            produit.get("modalite_demande") or "CERTAINE"
        ),
        "product_alternatives": list(
            produit.get("alternatives_produit") or []
        ),
        "product_code": code,
        "product_label": libelle,
        "quantity": quantite,
        "unit": unite,
        "candidate_code": selection.get("code_article", ""),
        "candidate_label": selection.get("libelle_article", ""),
        "score": selection.get("score_global", ""),
        "ambiguous": ambigu,
        "warnings": raisons,
        "quantity_inferred": bool(
            ligne.get("quantite_inferree")
            or produit.get("quantite_inferree")
        ),
        "alternatives": alternatives,
    }
