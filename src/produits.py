from __future__ import annotations

"""Façade de fiabilité autour du moteur produit historique.

Le moteur historique reste conservé intégralement dans ``src._produits_legacy``.
Cette façade ne modifie que des garde-fous généraux : preuve du noyau produit,
interprétation prudente des synonymes, disponibilité d'un candidat sans prix
local, récupération des ajouts présents dans un récapitulatif et secours
phonétique très borné pour les références hors cadencier.
"""

import re
from typing import Any

from . import _produits_legacy as _legacy

_ORIGINAL_PREUVE_NOYAU = _legacy._preuve_positive_noyau_produit
_ORIGINAL_VARIANTES = _legacy._generer_variantes_recherche
_ORIGINAL_EXTRAIRE_MENTIONS = _legacy.extraire_mentions_produits
_ORIGINAL_CANDIDAT_COMMANDABLE = _legacy._candidat_commandable
_ORIGINAL_CHERCHER_PRODUITS = _legacy.chercher_produits


def _tokens_significatifs_source(texte: str) -> list[str]:
    tokens_non_noyau = (
        _legacy.TOKENS_SANS_NOYAU_PRODUIT
        | _legacy.TOKENS_CONDITIONNEMENT_SANS_PRODUIT
        | _legacy.QUALIFICATIFS_PRODUIT
        | _legacy.FORMES_DISCOURS_COMMANDE
        | _legacy.NOMS_DISCOURS_COMMANDE
        | _legacy.TOKENS_CALENDRIER
    )
    return [
        token
        for token in _legacy._tokens_produit(texte)
        if token not in tokens_non_noyau
        and not token.isdigit()
        and not re.fullmatch(r"\d+(?:[.,]\d+)?[a-z]*", token)
    ]


def _noyau_unique_est_secondaire_du_libelle(
    texte_source: str,
    candidat: dict[str, Any],
) -> bool:
    """Détecte un mot qui décrit un produit composé sans en être le noyau.

    Exemples génériques : ``couteau`` dans ``tartare boeuf aux couteaux``,
    ``olive`` dans ``huile d'olive`` ou ``poulet`` dans ``filet de poulet``.
    La règle n'agit que lorsque le client n'a prononcé qu'un seul noyau utile.

    Un terme métier autonome absent de l'ontologie (par exemple le nom usuel
    d'un fromage) n'est cependant pas rejeté simplement parce que le libellé
    contient ``fromage de ...`` : il faut soit une famille explicitement
    contradictoire, soit un véritable noyau composé avant le complément.
    """
    tokens_source = _tokens_significatifs_source(texte_source)
    if len(tokens_source) != 1:
        return False

    token_source = tokens_source[0]
    famille_source = _legacy.primary_product_family(texte_source)
    libelle = str(
        candidat.get("libelle_normalise")
        or candidat.get("libelle_article")
        or ""
    )
    tokens_bruts = _legacy.normaliser_texte(libelle).split()
    liaisons = {
        "a", "au", "aux", "avec", "de", "des", "du", "d", "saveur",
    }

    for index, token_libelle in enumerate(tokens_bruts):
        if _legacy._score_token_produit(token_source, token_libelle) < 95.0:
            continue
        if index <= 0 or tokens_bruts[index - 1] not in liaisons:
            continue

        prefixe = " ".join(tokens_bruts[:index])
        famille_prefixe = _legacy.primary_product_family(prefixe)
        if not famille_prefixe:
            continue

        if famille_source and famille_source != famille_prefixe:
            return True

        if famille_source is None:
            noyaux_prefixe = _tokens_significatifs_source(prefixe)
            if len(noyaux_prefixe) >= 2:
                return True

    return False


def _preuve_positive_noyau_produit(
    texte_source: str,
    candidat: dict[str, Any],
    variantes_recherche: list[str] | None = None,
    mention: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    if _noyau_unique_est_secondaire_du_libelle(texte_source, candidat):
        return False, ["noyau_unique_secondaire_du_produit_compose"]
    return _ORIGINAL_PREUVE_NOYAU(
        texte_source,
        candidat,
        variantes_recherche,
        mention,
    )


def _tokens_semantiques(texte: str) -> set[str]:
    return {
        token
        for token in _legacy._tokens_produit(texte)
        if token not in _legacy.TOKENS_SANS_NOYAU_PRODUIT
        and token not in _legacy.TOKENS_CONDITIONNEMENT_SANS_PRODUIT
        and not token.isdigit()
    }


def _generer_variantes_recherche(
    produit_normalise: str,
    synonymes: dict[str, list[str]],
) -> list[str]:
    """Conserve les corrections ASR mais refuse les spécialisations inventées.

    Si une variante ne fait qu'ajouter des mots à ce qui a été prononcé
    (``moutarde`` -> ``moutarde de dijon``), elle n'est plus utilisée comme
    preuve lexicale. Les vraies substitutions (``chistora`` -> ``txistorra``)
    restent autorisées.
    """
    base = _legacy.normaliser_texte(produit_normalise)
    tokens_base = _tokens_semantiques(base)
    variantes = _ORIGINAL_VARIANTES(produit_normalise, synonymes)

    resultat: list[str] = []
    for variante in variantes:
        tokens_variante = _tokens_semantiques(variante)
        if tokens_base and tokens_base < tokens_variante:
            continue
        resultat.append(variante)

    if base and base not in resultat:
        resultat.append(base)
    return sorted(
        dict.fromkeys(resultat),
        key=lambda variante: (-len(variante), variante),
    )[:16]


def _candidat_commandable(candidat: dict[str, Any]) -> bool:
    """Tolère un prix local manquant sans ouvrir tout le catalogue inactif."""
    if _ORIGINAL_CANDIDAT_COMMANDABLE(candidat):
        return True

    libelle = str(candidat.get("libelle_article") or "")
    libelle_normalise = str(candidat.get("libelle_normalise") or "")
    if (
        "***" in libelle
        or "***" in libelle_normalise
        or not candidat.get("semantiquement_compatible", True)
    ):
        return False

    # Exception étroite : article déjà réellement vendu à ce client, retrouvé
    # lexicalement, mais dont le prix local n'est pas exploitable. Le product
    # gate reste ensuite obligatoire pour prouver que l'article a été dit.
    return bool(
        candidat.get("source_recherche") == "cadencier_client"
        and int(candidat.get("nb_ventes_article_total", 0) or 0) > 0
        and float(candidat.get("score_texte", 0.0) or 0.0) >= 45.0
        and str(candidat.get("code_article") or "").strip()
    )


_RECAP_RE = re.compile(
    r"\b(?:donc\s+)?je\s+(?:vous\s+)?r[eé]p[eè]te\s+"
    r"(?:la\s+)?commande\b",
    flags=re.IGNORECASE,
)
_ENUM_SPLIT_RE = re.compile(
    r"\s+(?=(?:\d+(?:[.,]\d+)?|un|une|deux|trois|quatre|cinq|six|sept|"
    r"huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|vingt)\s+"
    r"(?:cartons?|colis|pots?|poches?|bo[iî]tes?|bouteilles?|kilos?|kg|"
    r"litres?|pieces?|pi[eè]ces?|paquets?|sacs?|seaux?|barquettes?)\b)",
    flags=re.IGNORECASE,
)
_ENUM_MARKER_RE = re.compile(
    r"\b(?:\d+(?:[.,]\d+)?|un|une|deux|trois|quatre|cinq|six|sept|"
    r"huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|vingt)\s+"
    r"(?:cartons?|colis|pots?|poches?|bo[iî]tes?|bouteilles?|kilos?|kg|"
    r"litres?|pieces?|pi[eè]ces?|paquets?|sacs?|seaux?|barquettes?)\b",
    flags=re.IGNORECASE,
)


def _stabiliser_mentions(mentions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resultat = _legacy._dedupliquer_repetitions_mentions(mentions)
    resultat = _legacy._dedupliquer_repetitions_mentions(resultat)
    resultat = _legacy._dedupliquer_repetitions_differees(resultat)
    return _legacy._fusionner_mentions_dupliquees_proches(resultat)


def extraire_mentions_produits(
    transcription: str,
) -> list[dict[str, Any]]:
    """Ne perd plus un ajout annoncé dans un récapitulatif ou une liste dense."""
    mentions = list(_ORIGINAL_EXTRAIRE_MENTIONS(transcription))

    recap = _RECAP_RE.search(str(transcription or ""))
    if recap:
        suffixe = str(transcription or "")[recap.end():].strip()
        if suffixe:
            mentions.extend(_ORIGINAL_EXTRAIRE_MENTIONS(suffixe))

    marqueurs = len(_ENUM_MARKER_RE.findall(str(transcription or "")))
    if marqueurs >= 3 and len(mentions) + 1 < marqueurs:
        segmente = _ENUM_SPLIT_RE.sub("; ", str(transcription or ""))
        if segmente != transcription:
            mentions.extend(_ORIGINAL_EXTRAIRE_MENTIONS(segmente))

    return _stabiliser_mentions(mentions)


def _score_phonetique_global_borne(
    texte_source: str,
    candidat: dict[str, Any],
) -> float:
    """Mesure une déformation ASR légère sans faire de fuzzy catalogue ouvert."""
    tokens_source = [
        token
        for token in _tokens_significatifs_source(texte_source)
        if len(token) >= 6
    ]
    tokens_libelle = [
        token
        for token in _legacy._tokens_produit(
            str(
                candidat.get("libelle_normalise")
                or candidat.get("libelle_article")
                or ""
            )
        )
        if len(token) >= 6
        and token not in _legacy.TOKENS_CONDITIONNEMENT_SANS_PRODUIT
    ]
    return max(
        (
            float(_legacy._score_token_produit(source, cible))
            for source in tokens_source
            for cible in tokens_libelle
        ),
        default=0.0,
    )


def chercher_produits(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Rattrape exceptionnellement un produit hors cadencier déformé par l'ASR.

    Le cadencier garde exactement sa priorité habituelle. Ce secours ne se
    déclenche qu'après échec de la reconnaissance normale, parmi les candidats
    globaux/Réappro déjà produits par le moteur, avec une ressemblance sur un
    mot long >=92, une marge >=10 points, une quantité résolue et aucune
    contradiction sémantique. Le cas ``couteau -> tartare ... aux couteaux``
    reste bloqué par le garde-fou de noyau composé.
    """
    resultats = _ORIGINAL_CHERCHER_PRODUITS(*args, **kwargs)

    for produit in resultats:
        if produit.get("produit_reconnu"):
            continue
        if str(produit.get("role_semantique") or "PRODUCT_ITEM") in (
            _legacy.ROLES_SEMANTIQUES_NON_PRODUIT
        ):
            continue

        texte_source = str(
            produit.get("produit_normalise")
            or produit.get("texte_source")
            or ""
        )
        candidats_scores: list[tuple[float, dict[str, Any]]] = []
        for candidat in produit.get("candidats", []) or []:
            if candidat.get("source_recherche") not in {
                "catalogue_global",
                "catalogue_reappro",
            }:
                continue
            if not candidat.get("semantiquement_compatible", True):
                continue
            if candidat.get("quantite_resolue") is None:
                continue
            if not _candidat_commandable(candidat):
                continue
            score = _score_phonetique_global_borne(texte_source, candidat)
            if score >= 92.0:
                candidats_scores.append((score, candidat))

        candidats_scores.sort(
            key=lambda item: (
                item[0],
                float(item[1].get("score_texte", 0.0) or 0.0),
            ),
            reverse=True,
        )
        if not candidats_scores:
            continue

        score_premier, candidat_premier = candidats_scores[0]
        score_second = (
            candidats_scores[1][0]
            if len(candidats_scores) > 1
            else 0.0
        )
        if score_premier - score_second < 10.0:
            continue
        if float(candidat_premier.get("score_texte", 0.0) or 0.0) < 25.0:
            continue

        # Le garde-fou spécifique des noyaux secondaires reste obligatoire.
        if _noyau_unique_est_secondaire_du_libelle(
            texte_source,
            candidat_premier,
        ):
            continue

        selection = dict(candidat_premier)
        selection["noyau_produit_prouve"] = True
        selection.setdefault("raisons", []).append(
            f"secours_phonetique_global_borne={score_premier:.2f}"
        )
        produit["selection"] = selection
        produit["quantite_resolue"] = selection.get("quantite_resolue")
        produit["unite_resolue"] = selection.get("unite_resolue")
        produit["produit_fiable"] = True
        produit["produit_reconnu"] = True
        produit["seconde_passe_produit"] = True

        raisons = [
            raison
            for raison in (produit.get("raisons_ambiguite") or [])
            if raison not in {
                "aucun_article_trouve",
                "score_produit_trop_faible",
                "selection_article_non_nette",
                "product_gate_noyau_non_prouve",
                "quantite_commande_non_resolue",
                "unite_absente_a_resoudre",
            }
        ]
        produit["raisons_ambiguite"] = sorted(set(raisons))
        produit["ambigu"] = bool(raisons)
        produit["statut_couverture"] = (
            "AMBIGU"
            if produit.get("modalite_demande") == "ALTERNATIVE" or raisons
            else "RECONNU"
        )

    return resultats


# Les fonctions du moteur historique résolvent leurs dépendances dans leurs
# globals. On remplace donc aussi ces globals avant de réexporter l'API.
_legacy._preuve_positive_noyau_produit = _preuve_positive_noyau_produit
_legacy._generer_variantes_recherche = _generer_variantes_recherche
_legacy._candidat_commandable = _candidat_commandable
_legacy.extraire_mentions_produits = extraire_mentions_produits
_legacy.chercher_produits = chercher_produits

for _nom in dir(_legacy):
    if _nom.startswith("__"):
        continue
    globals()[_nom] = getattr(_legacy, _nom)

# Réaffectation explicite pour les symboles durcis.
globals()["_preuve_positive_noyau_produit"] = _preuve_positive_noyau_produit
globals()["_generer_variantes_recherche"] = _generer_variantes_recherche
globals()["_candidat_commandable"] = _candidat_commandable
globals()["extraire_mentions_produits"] = extraire_mentions_produits
globals()["_score_phonetique_global_borne"] = _score_phonetique_global_borne
globals()["chercher_produits"] = chercher_produits
