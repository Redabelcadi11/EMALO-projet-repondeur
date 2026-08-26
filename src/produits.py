from __future__ import annotations

"""Façade de fiabilité autour du moteur produit historique.

Le moteur historique reste conservé intégralement dans ``src._produits_legacy``.
Cette façade ne modifie que des garde-fous généraux : preuve du noyau produit,
interprétation prudente des synonymes, disponibilité d'un candidat sans prix
local, récupération des mentions perdues et secours Réappro intra-famille.
"""

import re
from collections import Counter
from typing import Any

from . import _produits_legacy as _legacy
from .product_hierarchy import PRIMARY_PRODUCT_FAMILIES

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

    Exemple générique : ``couteau`` dans ``tartare boeuf aux couteaux``.
    Le garde-fou n'agit que lorsqu'un unique noyau utile a été prononcé et
    qu'il apparaît comme complément d'une famille produit déjà exprimée.
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
    liaisons_simples = {
        "a", "au", "aux", "avec", "de", "des", "du", "d", "saveur",
    }
    articles_liaison = {"l", "la", "le", "les"}

    for index, token_libelle in enumerate(tokens_bruts):
        if _legacy._score_token_produit(token_source, token_libelle) < 95.0:
            continue
        if index <= 0:
            continue

        debut_liaison: int | None = None
        precedent = tokens_bruts[index - 1]
        if precedent in liaisons_simples:
            debut_liaison = index - 1
        elif (
            precedent in articles_liaison
            and index >= 2
            and tokens_bruts[index - 2] in {"a", "de"}
        ):
            debut_liaison = index - 2

        if debut_liaison is None:
            continue

        prefixe = " ".join(tokens_bruts[:debut_liaison])
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

    ``moutarde`` ne devient plus automatiquement ``moutarde de dijon`` parce
    que l'alias ne doit pas ajouter un attribut absent. Une vraie substitution
    phonétique déclarée, telle que ``chistora`` -> ``txistorra``, reste valide.
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


def _cle_repetition_sure(mention: dict[str, Any]) -> tuple[str, str, str]:
    quantite = mention.get("quantite_principale")
    try:
        quantite_cle = f"{float(quantite):.4f}"
    except (TypeError, ValueError):
        quantite_cle = ""
    return (
        _legacy.normaliser_texte(mention.get("produit_normalise", "")),
        quantite_cle,
        str(mention.get("unite_principale") or ""),
    )


def _dedupliquer_repetitions_differees_sures(
    mentions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ne retire que des répétitions réellement identiques de Whisper."""
    if not any(
        "repetition_transcription_supprimee"
        in (item.get("raisons_ambiguite") or [])
        for item in mentions
    ):
        return mentions

    cles = [_cle_repetition_sure(item) for item in mentions]
    comptes = Counter(cle for cle in cles if cle[0])
    repetes = {cle for cle, compte in comptes.items() if compte >= 2}
    if len(repetes) < 2:
        return mentions

    resultat: list[dict[str, Any]] = []
    vus: set[tuple[str, str, str]] = set()
    for item, cle in zip(mentions, cles):
        if cle in repetes and cle in vus:
            continue
        resultat.append(item)
        vus.add(cle)
    return resultat


def _stabiliser_mentions(mentions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resultat = _legacy._dedupliquer_repetitions_mentions(mentions)
    resultat = _legacy._dedupliquer_repetitions_mentions(resultat)
    resultat = _dedupliquer_repetitions_differees_sures(resultat)
    return _legacy._fusionner_mentions_dupliquees_proches(resultat)


def extraire_mentions_produits(
    transcription: str,
) -> list[dict[str, Any]]:
    """Ne perd plus un ajout annoncé dans un récapitulatif ou une liste dense."""
    source = str(transcription or "")
    mentions = list(_ORIGINAL_EXTRAIRE_MENTIONS(source))

    recap = _RECAP_RE.search(source)
    if recap:
        suffixe = source[recap.end():].strip()
        if suffixe:
            mentions.extend(_ORIGINAL_EXTRAIRE_MENTIONS(suffixe))

    marqueurs = list(_ENUM_MARKER_RE.finditer(source))
    if len(marqueurs) >= 3 and len(mentions) < len(marqueurs):
        segmente = _ENUM_SPLIT_RE.sub("; ", source)
        if segmente != source:
            mentions.extend(_ORIGINAL_EXTRAIRE_MENTIONS(segmente))

    if not mentions and marqueurs and marqueurs[0].start() > 0:
        queue_commande = source[marqueurs[0].start():].strip()
        mentions.extend(_ORIGINAL_EXTRAIRE_MENTIONS(queue_commande))

    return _stabiliser_mentions(mentions)


def _score_phonetique_reappro(
    texte_source: str,
    candidat: dict[str, Any],
) -> float:
    """Score phonétique porté par la variante, pas par la famille commune."""
    famille = _legacy.primary_product_family(texte_source)
    aliases_famille = set(PRIMARY_PRODUCT_FAMILIES.get(famille or "", ()))
    aliases_famille.add(str(famille or ""))

    tokens_source = [
        token
        for token in _tokens_significatifs_source(texte_source)
        if len(token) >= 4 and token not in aliases_famille
    ]
    tokens_candidat = [
        token
        for token in _tokens_significatifs_source(
            str(
                candidat.get("libelle_normalise")
                or candidat.get("libelle_article")
                or ""
            )
        )
        if len(token) >= 4 and token not in aliases_famille
    ]
    if not tokens_source or not tokens_candidat:
        return 0.0

    groupes_source = [*tokens_source]
    groupes_source.extend(
        "".join(tokens_source[index:index + 2])
        for index in range(len(tokens_source) - 1)
    )
    groupes_candidat = [*tokens_candidat]
    groupes_candidat.extend(
        "".join(tokens_candidat[index:index + 2])
        for index in range(len(tokens_candidat) - 1)
    )

    scores = [
        float(_legacy._score_phonetique_borne(source, cible))
        for source in groupes_source
        for cible in groupes_candidat
        if _legacy.normaliser_texte(source) != _legacy.normaliser_texte(cible)
    ]
    return max(scores, default=0.0)


def _selection_secours_reappro(
    texte_source: str,
    candidats: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float]:
    """Choisit un candidat Réappro uniquement dans une famille déjà dite."""
    if not _legacy.business_rule_enabled("reappro_variante_intra_famille"):
        return None, 0.0

    famille_source = _legacy.primary_product_family(texte_source)
    if not famille_source:
        return None, 0.0

    eligibles: list[tuple[float, dict[str, Any]]] = []
    for candidat in candidats:
        if candidat.get("source_recherche") != "catalogue_reappro":
            continue
        if not candidat.get("semantiquement_compatible", True):
            continue
        if candidat.get("quantite_resolue") is None:
            continue
        if not _candidat_commandable(candidat):
            continue
        famille_candidat = _legacy.primary_product_family(
            str(
                candidat.get("libelle_normalise")
                or candidat.get("libelle_article")
                or ""
            )
        )
        if famille_candidat != famille_source:
            continue
        score = _score_phonetique_reappro(texte_source, candidat)
        if score >= 90.0:
            eligibles.append((score, candidat))

    eligibles.sort(
        key=lambda item: (
            item[0],
            float(item[1].get("score_texte", 0.0) or 0.0),
        ),
        reverse=True,
    )
    if not eligibles:
        return None, 0.0

    score_premier, premier = eligibles[0]
    score_second = eligibles[1][0] if len(eligibles) > 1 else 0.0
    if score_premier - score_second < 8.0:
        return None, 0.0
    return premier, score_premier


def chercher_produits(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Rattrape un produit Réappro seulement après échec du moteur normal.

    Le +80 du cadencier n'est pas modifié : tout produit cadencier déjà
    reconnu garde donc sa priorité. Le secours ne s'ouvre qu'une fois la
    reconnaissance normale en échec, dans la famille explicitement dite et
    avec une preuve phonétique unique portée par la variante elle-même.
    """
    resultats = _ORIGINAL_CHERCHER_PRODUITS(*args, **kwargs)
    raisons_recuperables = {
        "aucun_article_trouve",
        "score_produit_trop_faible",
        "selection_article_non_nette",
        "product_gate_noyau_non_prouve",
        "quantite_commande_non_resolue",
        "quantite_absente_a_resoudre",
        "unite_absente_a_resoudre",
        "unite_absente",
        "repetition_transcription_supprimee",
        "reformulation_proche_fusionnee",
        "precision_quantite_rattachee",
        "conditionnement_multiple",
    }

    for produit in resultats:
        if produit.get("produit_reconnu"):
            continue
        if str(produit.get("role_semantique") or "PRODUCT_ITEM") in (
            _legacy.ROLES_SEMANTIQUES_NON_PRODUIT
        ):
            continue

        raisons_existantes = set(produit.get("raisons_ambiguite") or [])
        if raisons_existantes - raisons_recuperables:
            continue

        texte_source = str(
            produit.get("produit_normalise")
            or produit.get("texte_source")
            or ""
        )
        candidat, score = _selection_secours_reappro(
            texte_source,
            list(produit.get("candidats", []) or []),
        )
        if candidat is None:
            continue
        if _noyau_unique_est_secondaire_du_libelle(texte_source, candidat):
            continue

        selection = dict(candidat)
        selection["noyau_produit_prouve"] = True
        selection["noyau_phonetique_reappro_prouve"] = True
        selection.setdefault("raisons", []).append(
            f"secours_phonetique_reappro_intra_famille={score:.2f}"
        )
        produit["selection"] = selection
        produit["quantite_resolue"] = selection.get("quantite_resolue")
        produit["unite_resolue"] = selection.get("unite_resolue")
        produit["produit_fiable"] = True
        produit["produit_reconnu"] = True
        produit["seconde_passe_produit"] = True
        produit["raisons_ambiguite"] = []
        produit["ambigu"] = False
        produit["statut_couverture"] = "RECONNU"

    return resultats


# Les fonctions historiques résolvent leurs dépendances dans leurs globals :
# on les remplace avant toute exécution puis on réexporte l'API publique.
_legacy._preuve_positive_noyau_produit = _preuve_positive_noyau_produit
_legacy._generer_variantes_recherche = _generer_variantes_recherche
_legacy._candidat_commandable = _candidat_commandable
_legacy._dedupliquer_repetitions_differees = (
    _dedupliquer_repetitions_differees_sures
)
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
globals()["_dedupliquer_repetitions_differees_sures"] = (
    _dedupliquer_repetitions_differees_sures
)
globals()["extraire_mentions_produits"] = extraire_mentions_produits
globals()["_score_phonetique_reappro"] = _score_phonetique_reappro
globals()["_selection_secours_reappro"] = _selection_secours_reappro
globals()["chercher_produits"] = chercher_produits
