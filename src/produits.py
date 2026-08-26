from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from itertools import permutations
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

import src.llm_arbitrage as llm_arbitrage
from .normalisation import enlever_accents, normaliser_texte
from .evaluation_safety import filter_prediction_rules
from .business_rules import business_rule_enabled
from .product_hierarchy import (
    core_anchors,
    eligible_secondary_codes,
    explicit_attribute_conflicts,
    primary_product_family,
    reappro_fallback_bonuses,
    safe_physical_score,
    semantic_variant_score,
)


UNITES_EQUIVALENCES = {
    "kg": "KG",
    "kilo": "KG",
    "kilos": "KG",
    "kilogramme": "KG",
    "kilogrammes": "KG",
    "g": "G",
    "gramme": "G",
    "grammes": "G",
    "l": "L",
    "litre": "L",
    "litres": "L",
    "boite": "BOITE",
    "boites": "BOITE",
    "carton": "CAR",
    "cartons": "CAR",
    "caisse": "CAR",
    "caisses": "CAR",
    "colis": "COL",
    "piece": "PCE",
    "pieces": "PCE",
    "unite": "PCE",
    "unites": "PCE",
    "bloc": "PCE",
    "blocs": "PCE",
    "bac": "PCE",
    "bacs": "PCE",
    "bague": "PCE",
    "bagues": "PCE",
    "barquette": "PCE",
    "barquettes": "PCE",
    "brique": "PCE",
    "briques": "PCE",
    "fromage": "PCE",
    "fromages": "PCE",
    "bouteille": "PCE",
    "bouteilles": "PCE",
    "bidon": "PCE",
    "bidons": "PCE",
    "seau": "PCE",
    "seaux": "PCE",
    "peau": "PCE",
    "peaux": "PCE",
    "pot": "PCE",
    "pots": "PCE",
    "poche": "PCE",
    "poches": "PCE",
    "fosse": "PCE",
    "fosses": "PCE",
    "rouleau": "PCE",
    "rouleaux": "PCE",
    "plaque": "PCE",
    "plaques": "PCE",
    "morceau": "PCE",
    "morceaux": "PCE",
    "paquet": "PCE",
    "paquets": "PCE",
    "packet": "PCE",
    "packets": "PCE",
    "pack": "PCE",
    "packs": "PCE",
    "sachet": "PCE",
    "sachets": "PCE",
    "sac": "PCE",
    "sacs": "PCE",
    "palette": "PAL",
    "palettes": "PAL",
}

UNITES_REGEX = (
    r"kg|kilos?|kilogrammes?|g|grammes?|"
    r"l|litres?|boites?|cartons?|caisses?|colis|pieces?|unites?|blocs?|"
    r"bacs?|bagues?|barquettes?|briques?|fromages?|"
    r"bouteilles?|bidons?|seaux?|peaux?|pots?|poches?|fosses?|"
    r"rouleaux?|plaques?|morceaux?|"
    r"paquets?|packets?|packs?|sachets?|sacs?|palettes?"
)

MOTS_NOMBRE = {
    "zero": 0,
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "onze": 11,
    "douze": 12,
    "treize": 13,
    "quatorze": 14,
    "quinze": 15,
    "seize": 16,
    "vingt": 20,
    "trente": 30,
    "quarante": 40,
    "cinquante": 50,
    "soixante": 60,
}

MOTS_INTENTION_DEBUT = (
    "bonjour",
    "bonsoir",
    "je voudrais",
    "je souhaite",
    "je souhaiterais",
    "j aimerais",
    "je commande",
    "ce serait pour commander",
    "ce serait pour recommander",
    "je voudrais commander",
    "je souhaite recommander",
    "je veux commander",
    "c est pour une commande",
    "ce sera pour une commande",
    "pour passer une commande",
    "passer une commande",
    "pour une commande",
    "pour commander",
    "pour recommander",
    "recommander",
    "commander",
    "vous pourrez avoir",
    "pourrez avoir",
    "on aurait besoin de",
    "on aurait besoin",
    "j aurais besoin de",
    "j aurais besoin",
    "j ai besoin d",
    "j ai besoin de",
    "j ai besoin",
    "il me faudra",
    "il me faudrait",
    "il me faut",
    "il m en faudra",
    "il m en faudrait",
    "il m en faut",
    "il nous faudra",
    "il nous faudrait",
    "il nous faut",
    "il nous en faudra",
    "il nous en faudrait",
    "il nous en faut",
    "il m aurait fallu",
    "il faudrait",
    "il faudra",
    "me faudra",
    "faudrait",
    "je prendrai",
    "je vais vous en prendre",
    "je vais vous prendre",
    "je vais prendre",
    "je vous prendrai",
    "faites moi",
    "faites nous",
    "nous prendrons",
    "on va vous prendre",
    "on va prendre",
    "on prendra",
    "nous allons prendre",
    "par contre",
    "aussi",
    "egalement",
    "prendre demain",
    "prendre pour demain",
    "rajouter",
    "ajouter",
    "je vais rajouter",
    "je vais ajouter",
    "je voudrais donc",
    "donc",
    "c est",
    "c est le",
    "c est la",
    "c est les",
    "je suis le client",
)

MOTS_FIN_COMMANDE = (
    "ca serait tout",
    "ce serait tout",
    "ca sera tout",
    "ce sera tout",
    "c est tout",
    "ce sera tous",
    "je vous en remercie",
    "je vous remercie",
    "nous vous remercions",
    "bonne journee",
    "bonne soiree",
    "a demain",
    "sous titrage",
    "merci",
)

STOPWORDS_PRODUIT = {
    "de",
    "du",
    "des",
    "d",
    "la",
    "le",
    "les",
    "au",
    "aux",
    "et",
    "pate",
    "pates",
}

EXPRESSIONS_NON_PRODUIT = (
    "bonjour",
    "bonsoir",
    "merci",
    "je suis",
    "a l appareil",
    "client",
    "restaurant",
    "je voudrais",
    "je souhaite",
    "je souhaiterais",
    "je commande",
    "pour demain",
    "pour apres demain",
    "pour lundi",
    "pour mardi",
    "pour mercredi",
    "pour jeudi",
    "pour vendredi",
    "pour samedi",
    "pour dimanche",
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
    "demain",
    "apres demain",
    "demain matin",
    "demain soir",
    "alors",
    "voila",
    "je vous remercie",
    "je vous en remercie",
    "nous vous remercions",
    "bonne journee",
    "bonne soiree",
    "a demain",
    "sous titrage",
    "ca serait",
    "ce serait",
    "ici le",
    "ici la",
    "ici les",
    "ce matin",
    "me faudra",
    "il faudra",
    "j appelle",
    "en plus",
    "en plus ce sera tout",
    "en plus c est tout",
    "mettez moi",
    "mettez nous",
    "comment on appelle",
    "comment ca s appelle",
    "comment dire",
    "la marque que",
    "c est la marque",
    "la marque que tu preferes",
    "voila excusez moi",
    "voila ce sera tout",
    "barre du cru",
    "bar du cru",
    "casa rontedro",
    "casa juan pedro",
    "port des pecheurs",
    "port de peche",
    "pour ma commande",
    "j ai oublie",
)

# Une clause de commande peut ne decrire aucun article : elle annonce alors
# une action (commande, ajout, demande, correction, transition...) au lieu de
# porter un noyau produit. Les formes nominales regulieres sont derivees des
# verbes d'intention deja connus plus haut, afin de ne pas maintenir une liste
# d'exceptions phrase par phrase.
VERBES_DISCOURS_COMMANDE = {
    token
    for expression in MOTS_INTENTION_DEBUT
    for token in expression.split()
    if token.endswith("er")
} | {
    "annoncer",
    "apporter",
    "changer",
    "completer",
    "continuer",
    "corriger",
    "demander",
    "effectuer",
    "faire",
    "indiquer",
    "modifier",
    "passer",
    "preciser",
    "proceder",
    "reprendre",
    "rectifier",
    "souhaiter",
    "terminer",
}

# Vocabulaire de variantes partagé par toutes les glaces/sorbets. Il ne porte
# aucune référence article et n'est consulté qu'après établissement explicite
# de la famille dessert glacé des deux côtés.
PARFUMS_DESSERTS_GLACES = {
    "abricot", "ananas", "banane", "cassis", "cerise", "citron",
    "coco", "fraise", "framboise", "goyave", "groseille", "kiwi",
    "litchi", "mangue", "marron", "melon", "mure", "myrtille",
    "orange", "papaye", "passion", "peche", "poire", "pomme",
    "raisin", "amande", "basilic", "cafe", "caramel", "chocolat",
    "cookie", "menthe", "noisette", "nougat", "pecan", "pistache",
    "rhum", "speculoos", "the", "thym", "vanille", "yaourt",
}

PARFUMS_DESSERTS_GLACES_CANONIQUES = {
    "raisins": "raisin",
    "cookies": "cookie",
    "moka": "cafe",
    "matcha": "the",
}

NOMS_DISCOURS_COMMANDE = {
    "ajout",
    "changement",
    "commande",
    "complement",
    "correction",
    "demande",
    "information",
    "message",
    "modification",
    "precision",
    "rajout",
    "rectification",
    "requete",
    "suite",
    "sujet",
    "transition",
}

TOKENS_SANS_NOYAU_PRODUIT = {
    "a",
    "ai",
    "ainsi",
    "alors",
    "apres",
    "au",
    "aux",
    "avec",
    "avant",
    "ca",
    "ce",
    "cela",
    "cette",
    "d",
    "de",
    "des",
    "donc",
    "dois",
    "doit",
    "doivent",
    "devons",
    "devez",
    "du",
    "elle",
    "en",
    "encore",
    "ensuite",
    "et",
    "hier",
    "il",
    "j",
    "je",
    "juste",
    "l",
    "la",
    "le",
    "les",
    "leur",
    "leurs",
    "ma",
    "me",
    "mes",
    "mon",
    "nous",
    "nouveau",
    "nouvelle",
    "nouvelles",
    "nouveaux",
    "on",
    "ou",
    "par",
    "petit",
    "petite",
    "peu",
    "peut",
    "peuvent",
    "pouvez",
    "plus",
    "pour",
    "puis",
    "que",
    "qui",
    "sa",
    "ses",
    "simple",
    "simplement",
    "son",
    "supplementaire",
    "supplementaires",
    "sur",
    "te",
    "ton",
    "tout",
    "toute",
    "un",
    "une",
    "va",
    "vais",
    "veut",
    "veux",
    "voudrais",
    "vous",
    "avoir",
    "avais",
    "avait",
    "avions",
    "aviez",
    "avaient",
    # ``grain/graine`` decrit une forme ou une famille trop large : seul,
    # il ne peut pas justifier sesame, rape, poivre, etc. Le produit reste
    # evidemment reconnaissable des qu'un noyau est aussi prononce (lin,
    # courge, sesame, poivre...).
    "grain",
    "grains",
    "graine",
    "graines",
} | set(MOTS_NOMBRE)

TOKENS_CONDITIONNEMENT_SANS_PRODUIT = {
    "barquette",
    "barquettes",
    "bidon",
    "bidons",
    "boite",
    "boites",
    "bouteille",
    "bouteilles",
    "carton",
    "cartons",
    "colis",
    "gramme",
    "grammes",
    "kg",
    "kilo",
    "kilos",
    "litre",
    "litres",
    "paquet",
    "paquets",
    "piece",
    "pieces",
    "poche",
    "poches",
    "pot",
    "pots",
    "sac",
    "sacs",
    "seau",
    "seaux",
    "unite",
    "unites",
}

QUALIFICATIFS_PRODUIT = {
    "confit",
    "confite",
    "confites",
    "confits",
    "congele",
    "congelee",
    "congelees",
    "congeles",
    "cru",
    "crue",
    "crues",
    "crus",
    "decoupe",
    "decoupee",
    "decoupees",
    "decoupes",
    "entier",
    "entiere",
    "entieres",
    "entiers",
    "frais",
    "fraiche",
    "fraiches",
    "hache",
    "hachee",
    "hachees",
    "haches",
    "marine",
    "marinee",
    "marinees",
    "marines",
    "pele",
    "pelee",
    "pelees",
    "peles",
    "rape",
    "rapee",
    "rapees",
    "rapes",
    "surgele",
    "surgelee",
    "surgelees",
    "surgeles",
    "tranche",
    "tranchee",
    "tranchees",
    "tranches",
}

QUALIFICATIFS_ORPHELINS = QUALIFICATIFS_PRODUIT | {
    "blanc",
    "blanche",
    "bleu",
    "bleue",
    "demi",
    "jaune",
    "noir",
    "noire",
    "rouge",
    "sel",
    "vert",
    "verte",
}

ROLES_SEMANTIQUES_NON_PRODUIT = {
    "CLIENT",
    "CONDITION",
    "DELIVERY",
    "INFORMATION_ONLY",
    "NEGATION",
    "ORDER_DISCOURSE",
    "POLITENESS",
    "SUBSTITUTION",
}


# Ces vocabulaires de calendrier servent uniquement au pipeline produit. La
# date de livraison continue d'etre extraite depuis la transcription brute par
# son module dedie. Ici, on empeche simplement un numero de jour (``21 aout``)
# de devenir une quantite article.
JOURS_CALENDRIER = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)
MOIS_CALENDRIER = (
    "janvier",
    "fevrier",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "aout",
    "septembre",
    "octobre",
    "novembre",
    "decembre",
)
TOKENS_CALENDRIER = set(JOURS_CALENDRIER) | set(MOIS_CALENDRIER) | {
    "aujourd",
    "hui",
    "demain",
    "matin",
    "midi",
    "soir",
}

SEUIL_PRODUIT_FIABLE = 78.0
SEUIL_PRODUIT_MIN = 60.0
SEUIL_PRODUIT_CADENCIER_MIN = 55.0
UNITES_EMBALLAGE = {"COL", "CAR", "BOITE", "PAL", "POC", "SAC", "PACK", "BARQ", "SEAU", "BID"}
UNITES_EMBALLAGE_EXTERIEUR = {"COL", "CAR", "BOITE", "PAL", "SAC", "PACK", "BARQ", "SEAU", "BID"}
_REGLES_APPRENTISSAGE_CACHE: dict[str, Any] = {
    "mtime_ns": None,
    "regles": [],
}
_CONDITIONNEMENTS_ARTICLES_CACHE: dict[str, Any] = {
    "mtime_ns": None,
    "regles": {},
}
_REFERENCES_CONTROLE_CACHE: dict[str, Any] = {
    "mtime_ns": None,
    "references": {},
}
_REFERENCES_CONTROLE_PRODUITS_CACHE: dict[str, Any] = {
    "mtime_ns": None,
    "produits": [],
}
_POOL_LIBELLES_CACHE: dict[int, tuple[int, list[str]]] = {}


def charger_synonymes_produits(
    chemin: Path,
) -> dict[str, list[str]]:
    if not chemin.exists():
        return {}

    brut = json.loads(
        chemin.read_text(encoding="utf-8")
    )

    synonymes: dict[str, list[str]] = {}

    for canonique, variantes in (brut or {}).items():
        canon = normaliser_texte(canonique)

        if not canon:
            continue

        if isinstance(variantes, str):
            valeurs = [variantes]
        else:
            valeurs = [
                str(v or "")
                for v in (variantes or [])
            ]

        liste = {
            normaliser_texte(v)
            for v in valeurs
            if normaliser_texte(v)
        }
        liste.add(canon)

        synonymes[canon] = sorted(liste)

    return synonymes


def _charger_regles_apprentissage() -> list[dict[str, Any]]:
    chemin = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "regles-apprentissage.json"
    )
    try:
        mtime_ns = chemin.stat().st_mtime_ns
    except OSError:
        return []
    if _REGLES_APPRENTISSAGE_CACHE["mtime_ns"] == mtime_ns:
        return list(_REGLES_APPRENTISSAGE_CACHE["regles"])
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    regles_chargees = [
        regle
        for regle in (brut.get("rules") if isinstance(brut, dict) else [])
        if isinstance(regle, dict) and regle.get("enabled", True)
    ]
    regles = filter_prediction_rules(regles_chargees)
    _REGLES_APPRENTISSAGE_CACHE["mtime_ns"] = mtime_ns
    _REGLES_APPRENTISSAGE_CACHE["regles"] = regles
    return list(regles)


def _charger_conditionnements_articles() -> dict[str, dict[str, Any]]:
    chemin = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "conditionnements-articles.json"
    )
    try:
        mtime_ns = chemin.stat().st_mtime_ns
    except OSError:
        return {}
    if _CONDITIONNEMENTS_ARTICLES_CACHE["mtime_ns"] == mtime_ns:
        return dict(_CONDITIONNEMENTS_ARTICLES_CACHE["regles"])
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    regles_brutes = brut.get("rules", {}) if isinstance(brut, dict) else {}
    regles = {
        str(code): details
        for code, details in regles_brutes.items()
        if isinstance(details, dict)
    }
    _CONDITIONNEMENTS_ARTICLES_CACHE["mtime_ns"] = mtime_ns
    _CONDITIONNEMENTS_ARTICLES_CACHE["regles"] = regles
    return dict(regles)


def _charger_references_controle() -> dict[str, dict[str, Any]]:
    chemin = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "references-articles-controle.json"
    )
    try:
        mtime_ns = chemin.stat().st_mtime_ns
    except OSError:
        return {}
    if _REFERENCES_CONTROLE_CACHE["mtime_ns"] == mtime_ns:
        return dict(_REFERENCES_CONTROLE_CACHE["references"])
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    references_brutes = (
        brut.get("references", {}) if isinstance(brut, dict) else {}
    )
    references = {
        str(code): details
        for code, details in references_brutes.items()
        if isinstance(details, dict)
    }
    _REFERENCES_CONTROLE_CACHE["mtime_ns"] = mtime_ns
    _REFERENCES_CONTROLE_CACHE["references"] = references
    return dict(references)


def _catalogue_references_controle_produits() -> list[dict[str, Any]]:
    """Expose le référentiel officiel comme dernier pool de recherche.

    Ce pool n'est jamais utilisé seul : l'appelant exige plusieurs ancrages
    lexicaux explicites avant qu'une référence puisse devenir candidate.
    """
    chemin = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "references-articles-controle.json"
    )
    try:
        mtime_ns = chemin.stat().st_mtime_ns
    except OSError:
        return []
    if _REFERENCES_CONTROLE_PRODUITS_CACHE["mtime_ns"] == mtime_ns:
        # Conserver l'identite de la liste permet a _rechercher_dans_pool de
        # reutiliser son index RapidFuzz. Le pool n'est jamais modifie par la
        # recherche.
        return _REFERENCES_CONTROLE_PRODUITS_CACHE["produits"]

    produits = [
        {
            "code_article": code,
            "libelle_article": str(reference.get("label") or ""),
            "libelle_normalise": normaliser_texte(
                str(reference.get("label") or "")
            ),
            "unite_vente": str(reference.get("order_unit") or ""),
            "source_article": "referentiel_articles",
            "prix": None,
        }
        for code, reference in _charger_references_controle().items()
        if str(reference.get("label") or "").strip()
    ]
    _REFERENCES_CONTROLE_PRODUITS_CACHE["mtime_ns"] = mtime_ns
    _REFERENCES_CONTROLE_PRODUITS_CACHE["produits"] = produits
    return produits


def _bonus_regle_apprentissage(
    produit: str,
    source_mention: str,
    libelle: str,
    client: str = "",
) -> tuple[float, str | None]:
    meilleur_bonus = 0.0
    meilleure_raison: str | None = None
    champs = {
        "mention": produit,
        "source": source_mention,
        "label": libelle,
        "client": client,
    }
    for regle in _charger_regles_apprentissage():
        correspond = True
        for champ, texte in champs.items():
            tous = [
                normaliser_texte(str(valeur))
                for valeur in regle.get(f"{champ}_all", [])
                if normaliser_texte(str(valeur))
            ]
            un_des = [
                normaliser_texte(str(valeur))
                for valeur in regle.get(f"{champ}_any", [])
                if normaliser_texte(str(valeur))
            ]
            exclus = [
                normaliser_texte(str(valeur))
                for valeur in regle.get(f"{champ}_none", [])
                if normaliser_texte(str(valeur))
            ]
            if any(valeur not in texte for valeur in tous):
                correspond = False
                break
            if un_des and not any(valeur in texte for valeur in un_des):
                correspond = False
                break
            if any(valeur in texte for valeur in exclus):
                correspond = False
                break
        if not correspond:
            continue
        try:
            bonus = min(80.0, max(0.0, float(regle.get("bonus", 0.0))))
        except (TypeError, ValueError):
            continue
        if bonus > meilleur_bonus:
            meilleur_bonus = bonus
            identifiant = re.sub(
                r"[^a-z0-9_-]+",
                "_",
                normaliser_texte(str(regle.get("id") or "locale")),
            ).strip("_")
            meilleure_raison = f"preference_apprise_{identifiant or 'locale'}"
    return meilleur_bonus, meilleure_raison


def normaliser_transcription_produits(
    transcription: str,
) -> str:
    texte = enlever_accents(transcription).lower()
    texte = texte.replace("œ", "oe")
    texte = texte.replace("'", " ")
    texte = re.sub(
        r"\bcontre\s+(?:cinq|5)\s*(?=%|pour\s+cent)",
        "35 ",
        texte,
    )
    texte = re.sub(r"\b5\s*-\s*1\b", "5 1", texte)
    texte = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "x", texte)
    texte = re.sub(r"[-/]", " ", texte)
    # Dans une commande, ``en des`` est la graphie ASR frequente de
    # ``en des/des en cube`` (ex. mangue en des).  Cette forme est une
    # decoupe explicite, pas l'article francais ``des`` : ne la normaliser
    # qu'apres la preposition ``en`` evite d'alterer le texte courant.
    texte = re.sub(r"\ben\s+des\b", "en cube", texte)
    texte = re.sub(
        r"(?<![a-z0-9])(\d+)\s*,\s*(\d+)",
        r"\1.\2",
        texte,
    )
    texte = re.sub(r"\s+", " ", texte).strip()

    return texte


def _remplacer_nombres_composes(texte: str) -> str:
    petits = {
        "un": 1,
        "deux": 2,
        "trois": 3,
        "quatre": 4,
        "cinq": 5,
        "six": 6,
        "sept": 7,
        "huit": 8,
        "neuf": 9,
        "dix": 10,
        "onze": 11,
        "douze": 12,
        "treize": 13,
        "quatorze": 14,
        "quinze": 15,
        "seize": 16,
        "dix sept": 17,
        "dix huit": 18,
        "dix neuf": 19,
    }

    def remplacer_base(
        valeur_base: int,
        expression_base: str,
        suffixes: dict[str, int],
    ) -> None:
        nonlocal texte
        for expression, valeur in sorted(
            suffixes.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            texte = re.sub(
                rf"\b{expression_base}(?:\s+et)?\s+{expression}\b",
                str(valeur_base + valeur),
                texte,
            )

    remplacer_base(80, r"quatre\s+vingts?", petits)
    remplacer_base(60, "soixante", petits)
    unites = {expression: valeur for expression, valeur in petits.items() if valeur < 10}
    for expression, valeur in (
        ("cinquante", 50),
        ("quarante", 40),
        ("trente", 30),
        ("vingt", 20),
    ):
        remplacer_base(valeur, expression, unites)

    texte = re.sub(r"\bquatre\s+vingts?\b", "80", texte)
    for expression, valeur in sorted(
        petits.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if valeur >= 17:
            texte = re.sub(rf"\b{expression}\b", str(valeur), texte)
    return texte


def remplacer_nombres_en_chiffres(
    texte: str,
) -> str:
    texte = _remplacer_nombres_composes(texte)

    for mot, valeur in sorted(
        MOTS_NOMBRE.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        texte = re.sub(
            rf"\b{re.escape(mot)}\b",
            str(valeur),
            texte,
        )

    return texte


def _convertir_decimal_oral(
    base: float,
    suffixe: str,
) -> float | None:
    if not suffixe.isdigit():
        return None

    valeur = int(suffixe)

    if valeur < 10:
        return base + (valeur / 10)

    if valeur < 100:
        return base + (valeur / 100)

    return None


def _normaliser_oraux_decimaux(
    texte: str,
) -> str:
    def remplacer(motif: re.Match[str]) -> str:
        base = float(motif.group("base"))
        unite = motif.group("unite")
        suffixe = motif.group("suffixe")
        conversion = _convertir_decimal_oral(
            base=base,
            suffixe=suffixe,
        )

        if conversion is None:
            return motif.group(0)

        return f"{conversion:.3f} {unite}"

    return re.sub(
        (
            rf"\b(?P<base>\d+(?:\.\d+)?)\s+"
            rf"(?P<unite>{UNITES_REGEX})\s+"
            r"(?P<suffixe>\d{1,2})\b"
        ),
        remplacer,
        texte,
    )


def _retirer_contexte_calendaire_produits(texte: str) -> str:
    """Neutralise le numero d'une date avant l'extraction des quantites.

    Les marqueurs ``demain`` et ``vendredi`` sont deliberement conserves :
    ils aident les grammaires existantes a borner une introduction ou une
    queue de livraison. Seul ``21 aout`` doit disparaitre du flux quantite.
    """
    jours = "|".join(JOURS_CALENDRIER)
    mois = "|".join(MOIS_CALENDRIER)

    motif = re.compile(
        rf"\b(?:(?P<jour>(?:pour\s+)?(?:ce\s+|le\s+)?(?:{jours}))\s+|"
        rf"(?:pour\s+)?(?:le\s+)?)"
        rf"(?:0?[1-9]|[12]\d|3[01])\s+(?:{mois})"
        rf"(?:\s+(?:20)?\d{{2}})?\b"
    )

    def remplacer_date(match: re.Match[str]) -> str:
        jour = (match.group("jour") or "").strip()
        return f" {jour} " if jour else " "

    texte = motif.sub(remplacer_date, texte)
    return re.sub(r"\s+", " ", texte).strip(" ,;.")


def _nettoyer_debut_clause(
    clause: str,
) -> str:
    clause = clause.strip(" ,;.")

    precedent = None

    while clause and clause != precedent:
        precedent = clause

        for prefixe in sorted(
            MOTS_INTENTION_DEBUT,
            key=len,
            reverse=True,
        ):
            clause = re.sub(
                rf"^\s*{re.escape(prefixe)}\s+",
                "",
                clause,
            )

    return clause.strip(" ,;.")


def _normaliser_clause_parse(
    clause: str,
) -> str:
    texte = normaliser_transcription_produits(clause)
    texte = remplacer_nombres_en_chiffres(texte)
    texte = _normaliser_oraux_decimaux(texte)
    texte = _retirer_contexte_calendaire_produits(texte)
    texte = re.sub(
        r"[^a-z0-9\.\s]",
        " ",
        texte,
    )
    texte = re.sub(
        r"\b(?:s il vous plai?\s*t|s il te plai?\s*t|svp)\b",
        " ",
        texte,
    )
    texte = re.sub(r"\s+", " ", texte).strip()

    return texte


_MOTIF_HEURE_LIVRAISON = (
    r"(?:\d{1,2}\s*(?:h|heure|heures)(?:\s*(?:\d{1,2}|et\s+quart|et\s+demi))?|"
    r"\d{1,2}\s*h\s*\d{1,2})"
)
_MOMENT_JOURNEE_LIVRAISON = (
    r"(?:\s+(?:(?:du|le|ce)\s+)?(?:matin|midi|soir|apres\s+midi))?"
)


def _est_expression_horaire_livraison(texte: str) -> bool:
    """Reconnait une plage horaire, quelle que soit sa formulation orale.

    Une heure n'est pas une quantite produit. Cette grammaire couvre les
    prepositions usuelles et les moments de la journee sans enumerer des
    phrases completes : ``vers 9h30``, ``a partir de 9 heures du matin``,
    ``entre 8 h et 10 h``.
    """
    heure = _MOTIF_HEURE_LIVRAISON
    moment = _MOMENT_JOURNEE_LIVRAISON
    return bool(
        re.fullmatch(
            (
                rf"(?:(?:(?:je|nous|on)\s+(?:pass\w*|livr\w*|"
                rf"receptionn\w*)\s+)?"
                rf"(?:a\s+partir\s+de|vers|a|avant|apres|depuis)\s+)?"
                rf"{heure}{moment}|"
                rf"entre\s+{heure}{moment}(?:\s+(?:et|a)\s+"
                rf"{heure}{moment})?"
            ),
            texte,
        )
    )


def _est_queue_livraison(clause: str) -> bool:
    """Indique qu'un suffixe est une consigne de livraison, pas un article."""
    texte = _normaliser_clause_parse(clause)
    return bool(
        _est_expression_horaire_livraison(texte)
        or re.match(
            r"^(?:de\s+)?(?:les?\s+)?livr\w*\b",
            texte,
        )
    )


def _couper_avant_quantite_commande(
    clause_norm: str,
) -> str:
    if re.match(r"^\d+(?:\.\d+)?\b", clause_norm):
        return clause_norm

    match = re.search(
        (
            r"\b\d+(?:\.\d+)?(?:\s*x\s*\d+(?:\.\d+)?)?"
            r"\s*"
            rf"(?:(?:{UNITES_REGEX})\b)?"
            r"\s*(?:(?:de|d)\b)?\s+"
            r"[a-z0-9]"
        ),
        clause_norm,
    )
    if not match:
        return clause_norm

    prefixe = clause_norm[: match.start()].strip()
    if not prefixe:
        return clause_norm

    marqueurs_intro = (
        "livraison",
        "pour demain",
        "pour apres demain",
        "pour lundi",
        "pour mardi",
        "pour mercredi",
        "pour jeudi",
        "pour vendredi",
        "pour samedi",
        "pour dimanche",
        "est ce qu",
        "j ai besoin",
        "faites moi",
        "faites nous",
        "il me faudrait",
        "il me faut",
        "je voudrais",
        "je souhaite",
        "je vais vous prendre",
        "je vais vous en prendre",
        "passer une commande",
        "pour passer une commande",
        "pour une commande",
        "c est pour une commande",
        "ce sera pour une commande",
        "il m aurait fallu",
        "il me faudra",
        "il me faudrait",
        "il me faut",
        "il nous faudra",
        "il nous faudrait",
        "il nous faut",
        "je prendrai",
        "je vais vous en prendre",
        "je vais vous prendre",
        "je vais prendre",
        "je vous prendrai",
        "nous prendrons",
        "on va vous prendre",
        "on va prendre",
        "on prendra",
        "nous allons prendre",
    )
    if any(marqueur in prefixe for marqueur in marqueurs_intro):
        return clause_norm[match.start() :].strip()

    return clause_norm


_MARQUEUR_CODE_ARTICLE = re.compile(
    r"\b(?:reference|ref|code(?:\s+(?:article|produit))?)\b"
)


def _texte_numerique_code_article(texte: str) -> str:
    """Normalise les chiffres tels que Whisper peut les restituer.

    Les séparateurs (`-`, espaces, `x`) ne font pas partie du code ERP. Les
    nombres prononcés mot à mot sont convertis avant la recherche, ce qui
    couvre notamment ``zéro zéro quarante quarante-deux douze``.
    """
    return remplacer_nombres_en_chiffres(
        normaliser_transcription_produits(texte)
    )


def _clause_est_reference_article_seule(texte: str) -> bool:
    """Vrai pour une précision de référence, sans nouveau noyau produit."""
    normalise = _texte_numerique_code_article(texte)
    if not _MARQUEUR_CODE_ARTICLE.search(normalise):
        return False
    reste = _MARQUEUR_CODE_ARTICLE.sub(" ", normalise)
    reste = re.sub(r"\b(?:avec|la|le|un|une|numero|n|par)\b", " ", reste)
    reste = re.sub(r"\b\d+\s*(?:pieces?|unites?)\b", " ", reste)
    reste = re.sub(r"[\dx.\s]+", " ", reste)
    return not re.search(r"[a-z]", reste)


def _candidats_numeriques_code_article(
    texte: str,
) -> list[tuple[str, bool]]:
    """Retourne `(chiffres, marqueur_explicite)` sans deviner un article.

    Après un marqueur explicite, les préfixes successifs sont conservés :
    ``0 0 40 42 12`` peut ainsi être comparé à ``00404212`` sans absorber
    la quantité du produit suivant. Sans marqueur, seuls les blocs compacts
    d'au moins cinq chiffres sont admis afin de ne pas confondre poids,
    dimensions, dates ou quantités avec une référence.
    """
    normalise = _texte_numerique_code_article(texte)
    trouves: list[tuple[str, bool]] = []

    for marqueur in _MARQUEUR_CODE_ARTICLE.finditer(normalise):
        fenetre = normalise[marqueur.end() : marqueur.end() + 64]
        groupes = re.findall(r"\d+", fenetre)
        concatene = ""
        for groupe in groupes[:8]:
            concatene += groupe
            if 3 <= len(concatene) <= 12:
                trouves.append((concatene, True))
            if len(concatene) > 12:
                break

    for correspondance in re.finditer(
        r"(?<![a-z0-9])\d{5,10}(?![a-z0-9])",
        normalise,
    ):
        chiffres = re.sub(r"\D", "", correspondance.group(0))
        if chiffres:
            trouves.append((chiffres, False))

    # Ordre stable et sans doublons ; l'appelant choisira le plus long code
    # réellement présent et unique dans les catalogues autorisés.
    uniques: list[tuple[str, bool]] = []
    vus: set[tuple[str, bool]] = set()
    for item in trouves:
        if item not in vus:
            uniques.append(item)
            vus.add(item)
    return uniques


def _rattacher_precision_produit_precedent(
    clause_norm: str,
    mentions: list[dict[str, Any]],
) -> bool:
    precision = clause_norm.strip()

    if mentions:
        precedente = mentions[-1]

        if (
            business_rule_enabled("code_article_prononce_prioritaire")
            and _clause_est_reference_article_seule(precision)
        ):
            # Une référence isolée qualifie le produit qui vient d'être
            # énoncé. Elle ne doit créer ni une nouvelle ligne produit ni une
            # nouvelle quantité (ex. ``80 pièces avec la référence ...``).
            precedente["texte_source"] = (
                f"{precedente.get('texte_source', '')}; {precision}"
            ).strip("; ")
            precedente["texte_normalise"] = (
                f"{precedente.get('texte_normalise', '')} {precision}"
            ).strip()
            precedente.setdefault(
                "references_article_prononcees", []
            ).append(precision)
            return True

        preference_historique_avec_variante = re.fullmatch(
            r"(?:(?:celui|celle|ceux|celles)\s+qu?e?\s+"
            r"(?:je|j|on|nous)\s+(?:vous\s+)?prends?|"
            r"(?:la|le)\s+produit\s+qu?e?\s+"
            r"(?:je|j|on|nous)\s+(?:vous\s+)?prends?)\s+"
            r"(?:d\s+habitude|habituellement)\s+(?P<variante>.+)",
            precision,
        )
        if (
            preference_historique_avec_variante
            and business_rule_enabled("historique_modificateur")
        ):
            variante = preference_historique_avec_variante.group(
                "variante"
            ).strip()
            if variante:
                for champ in ("produit_normalise", "texte_produit"):
                    valeur = normaliser_texte(precedente.get(champ, ""))
                    if variante not in valeur:
                        precedente[champ] = f"{valeur} {variante}".strip()
                precedente["texte_source"] = (
                    f"{precedente.get('texte_source', '')}; {precision}"
                ).strip("; ")
                precedente["preference_historique_compatible"] = True
                precedente["modalite_demande"] = "HABITUELLE"
                precedente.setdefault("raisons_ambiguite", []).append(
                    "variante_historique_explicitement_rattachee"
                )
                return True

        preference_historique = re.fullmatch(
            r"(?:(?:la|le)\s+)?(?:derniere|dernier)\s+"
            r"(?:(?:marque|reference)\s+)?(?:que\s+j\s+ai\s+)?"
            r"(?:achetee?|prise?)|"
            r"(?:la|le|les)?\s*meme(?:s)?\s+que\s+(?:la\s+)?derniere\s+fois|"
            r"toujours\s+(?:la|le|les)?\s*meme(?:s)?|"
            r"(?:(?:celui|celle|ceux|celles)\s+qu?e?\s+"
            r"(?:je|j|on|nous)\s+(?:vous\s+)?prends?\s+"
            r"(?:d\s+habitude|habituellement))|"
            r"(?:(?:la|l|les)?\s*ancienne(?:s)?\s+"
            r"(?:reference|references|ref|refs))|"
            r"comme\s+(?:la\s+derniere\s+fois|d\s+habitude)|"
            r"(?:la\s+)?marque\s+habituelle",
            precision,
        )
        if (
            preference_historique
            and business_rule_enabled("historique_modificateur")
        ):
            precedente["preference_historique_compatible"] = True
            precedente["modalite_demande"] = "HABITUELLE"
            precedente["texte_source"] = (
                f"{precedente.get('texte_source', '')}; {precision}"
            ).strip("; ")
            precedente.setdefault("raisons_ambiguite", []).append(
                "preference_historique_rattachee_au_produit_precedent"
            )
            return True

        attribut_mesure = re.fullmatch(
            r"(?P<valeur>\d+(?:\.\d+)?)\s*"
            r"(?P<attribut>mm|millimetres?|cm|centimetres?|"
            r"metres?|pouces?|blooms?)",
            precision,
        )
        if attribut_mesure:
            valeur = attribut_mesure.group("valeur")
            attribut_brut = attribut_mesure.group("attribut")
            attribut = (
                "cm" if attribut_brut.startswith("centimetre")
                else "mm" if attribut_brut.startswith("millimetre")
                else attribut_brut
            )
            precision_normalisee = f"{valeur} {attribut}"
            for champ in ("produit_normalise", "texte_produit"):
                contenu = str(precedente.get(champ) or "").strip()
                if precision_normalisee not in normaliser_texte(contenu):
                    precedente[champ] = (
                        f"{contenu} {precision_normalisee}".strip()
                    )
            precedente["texte_source"] = (
                f"{precedente.get('texte_source', '')}; {precision}"
            ).strip("; ")
            precedente.setdefault("raisons_ambiguite", []).append(
                "attribut_produit_rattache"
            )
            return True

        exclusion = re.fullmatch(
            r"(?:pas\s+(?:de|du|la|le|les)|sans)\s+"
            r"(?P<terme>[a-z][a-z0-9\s]{0,50}?)"
            r"(?:\s+si\s+possible)?",
            precision,
        )
        if exclusion:
            terme = exclusion.group("terme").strip()
            exclusions = precedente.setdefault("exclusions_produit", [])
            if terme and terme not in exclusions:
                exclusions.append(terme)
            precedente["texte_source"] = (
                f"{precedente.get('texte_source', '')}; {precision}"
            ).strip("; ")
            precedente.setdefault("raisons_ambiguite", []).append(
                "exclusion_produit_rattachee"
            )
            return True

        multiple = re.fullmatch(
            r"(?P<nombre>\d+(?:\.\d+)?)\s+(?:fois|x)\s+"
            r"(?P<taille>\d+(?:\.\d+)?)\s*"
            rf"(?P<unite>{UNITES_REGEX})\b",
            precision,
        )
        if multiple:
            nombre = float(multiple.group("nombre"))
            taille = float(multiple.group("taille"))
            unite_taille = _normaliser_unite(multiple.group("unite"))
            if precedente.get("quantite_principale") is None:
                precedente["quantite_principale"] = nombre
                precedente["quantite"] = nombre
                precedente["unite_principale"] = "PCE"
                precedente["unite_detectee"] = "PCE"
            precedente.setdefault("precisions_quantite", []).append(
                {
                    "quantite": taille,
                    "unite": unite_taille,
                    "texte_source": precision,
                    "origine": "taille_unitaire_multiple",
                    "nombre_unites": nombre,
                }
            )
            precedente.setdefault("raisons_ambiguite", []).append(
                "taille_unitaire_rattachee"
            )
            return True

        quantite_explication = re.fullmatch(
            r"(?:(?:je\s+(?:crois|pense)(?:\s+que)?(?:\s+c\s+est)?)|"
            r"(?:(?:donc\s+)?(?:ca|cela)\s+(?:fait|fera)))?\s*"
            r"(?P<quantite>\d+(?:\.\d+)?)\s*"
            rf"(?P<unite>{UNITES_REGEX})\b",
            precision,
        )
        if quantite_explication:
            quantite = float(quantite_explication.group("quantite"))
            unite = _normaliser_unite(quantite_explication.group("unite"))
            quantite, unite, conversions = _adapter_quantite_unite(
                quantite, unite
            )
            quantite_precedente = precedente.get("quantite_principale")
            if quantite_precedente is None:
                precedente["quantite_principale"] = quantite
                precedente["quantite"] = quantite
                precedente["unite_principale"] = unite
                precedente["unite_detectee"] = unite
            elif (
                precedente.get("unite_principale") is None
                and unite not in {None, "KG", "L"}
                and abs(float(quantite_precedente) - quantite) <= 0.001
            ):
                precedente["unite_principale"] = unite
                precedente["unite_detectee"] = unite
            else:
                detail = {
                    "quantite": quantite,
                    "unite": unite,
                    "texte_source": precision,
                    "origine": "precision_quantite_orale",
                }
                if conversions:
                    detail["precisions"] = conversions
                precedente.setdefault("precisions_quantite", []).append(detail)
            precedente.setdefault("raisons_ambiguite", []).append(
                "precision_quantite_rattachee"
            )
            return True

        compteur = re.fullmatch(
            r"(?P<quantite>\d+(?:\.\d+)?)\s+"
            r"(?:(?:unites?|pieces?)\s+(?:en\s+)?)?"
            r"(?P<contenant>filets?|tranches?|pots?|poches?|sacs?|"
            r"bouteilles?|boites?|cartons?|colis|paquets?|sachets?)",
            precision,
        )
        if compteur:
            quantite = float(compteur.group("quantite"))
            contenant = compteur.group("contenant")
            unite = _normaliser_unite(contenant)
            if contenant.startswith(("filet", "tranche")):
                unite = "PCE"
                produit_precedent = normaliser_texte(
                    precedente.get("produit_normalise", "")
                )
                if contenant.rstrip("s") not in produit_precedent:
                    precedente["produit_normalise"] = (
                        f"{produit_precedent} {contenant.rstrip('s')}"
                    ).strip()
                    precedente["texte_produit"] = precedente[
                        "produit_normalise"
                    ]
            quantite_precedente = precedente.get("quantite_principale")
            if quantite_precedente is None:
                precedente["quantite_principale"] = quantite
                precedente["quantite"] = quantite
                precedente["unite_principale"] = unite
                precedente["unite_detectee"] = unite
            elif abs(float(quantite_precedente) - quantite) <= 0.001:
                if precedente.get("unite_principale") is None:
                    precedente["unite_principale"] = unite
                    precedente["unite_detectee"] = unite
            else:
                precedente.setdefault("precisions_quantite", []).append(
                    {
                        "quantite": quantite,
                        "unite": unite,
                        "texte_source": precision,
                        "origine": "compteur_produit_precedent",
                    }
                )
            precedente.setdefault("raisons_ambiguite", []).append(
                "compteur_produit_precedent_rattache"
            )
            return True

    pourcentage = re.fullmatch(
        r"(?P<taux>\d+(?:\.\d+)?)\s*(?:pour\s*cent|pourcent)",
        precision,
    )
    if pourcentage and mentions:
        precedente = mentions[-1]
        produit_precedent = normaliser_texte(
            precedente.get("produit_normalise", "")
        )
        if any(
            terme in produit_precedent
            for terme in (
                "creme", "lait", "matiere grasse", "chocolat", "cacao"
            )
        ):
            taux = pourcentage.group("taux")
            for champ in ("produit_normalise", "texte_produit"):
                valeur = str(precedente.get(champ) or "").strip()
                precedente[champ] = f"{valeur} {taux} pour cent".strip()
            precedente["texte_normalise"] = (
                f"{precedente.get('texte_normalise', '')} {precision}"
            ).strip()
            precedente.setdefault("raisons_ambiguite", []).append(
                "pourcentage_produit_rattache"
            )
            return True

    qualificatif = re.sub(
        r"^(?:le|la|les|l)\s+|\s+(?:pareil|pareille|aussi)$",
        "",
        precision,
    ).strip()
    if mentions and qualificatif and all(
        token in QUALIFICATIFS_ORPHELINS
        for token in qualificatif.split()
    ):
        precedente = mentions[-1]
        for champ in ("produit_normalise", "texte_produit"):
            valeur = str(precedente.get(champ) or "").strip()
            if qualificatif not in normaliser_texte(valeur):
                precedente[champ] = f"{valeur} {qualificatif}".strip()
        precedente["texte_source"] = (
            f"{precedente.get('texte_source', '')}; {precision}"
        ).strip("; ")
        precedente.setdefault("raisons_ambiguite", []).append(
            "qualificatif_produit_rattache"
        )
        return True

    if precision not in {
        "madagascar",
        "bourbon",
        "au beurre",
        "pur beurre",
    }:
        return False

    if not mentions:
        return True

    precedente = mentions[-1]
    produit_precedent = normaliser_texte(
        precedente.get("produit_normalise", "")
    )
    if precision in {"madagascar", "bourbon"}:
        termes_acceptes = ("vanille", "glace", "glacee")
    else:
        termes_acceptes = (
            "croissant",
            "pain chocolat",
            "pain au chocolat",
            "brioche",
        )

    if not any(terme in produit_precedent for terme in termes_acceptes):
        return False

    if precision in {"au beurre", "pur beurre"}:
        precedente.setdefault("raisons_ambiguite", []).append(
            "precision_produit_rattachee"
        )
        return True

    for champ in ("produit_normalise", "texte_produit"):
        valeur = str(precedente.get(champ) or "").strip()
        if precision not in normaliser_texte(valeur):
            precedente[champ] = f"{valeur} {precision}".strip()

    precedente["texte_normalise"] = (
        f"{precedente.get('texte_normalise', '')} {precision}"
    ).strip()
    precedente.setdefault("raisons_ambiguite", []).append(
        "precision_produit_rattachee"
    )
    return True


def _clause_peut_completer_produit_precedent(clause_norm: str) -> bool:
    """Conserve les precisions que le filtre de bavardage ignorerait sinon."""
    qualificatif = re.sub(
        r"^(?:le|la|les|l)\s+|\s+(?:pareil|pareille|aussi)$",
        "",
        clause_norm,
    ).strip()
    return bool(
        re.fullmatch(
            r"(?:(?:je\s+(?:crois|pense)(?:\s+que)?(?:\s+c\s+est)?)|"
            r"(?:(?:donc\s+)?(?:ca|cela)\s+(?:fait|fera)))\s*"
            r"\d+(?:\.\d+)?\s*(?:" + UNITES_REGEX + r")\b",
            clause_norm,
        )
        or re.fullmatch(
            r"(?:pas\s+(?:de|du|la|le|les)|sans)\s+"
            r"[a-z][a-z0-9\s]{0,50}?(?:\s+si\s+possible)?",
            clause_norm,
        )
        or (
            qualificatif
            and all(
                token in QUALIFICATIFS_ORPHELINS
                for token in qualificatif.split()
            )
        )
    )


def _normaliser_produit_extrait(
    produit: str,
) -> str:
    produit = normaliser_texte(produit)
    produit = re.sub(
        r"^(?:des|du|de\s+la|de\s+l)\s+",
        " ",
        produit,
    )

    produit = re.sub(
        r"^(?:ou\s+)?(?:lot|lots)\s+de\s+",
        " ",
        produit,
    )
    # L'emballage est deja porte par l'unite de la mention. Il ne doit pas
    # affaiblir la recherche du noyau produit dans le cadencier.
    produit = re.sub(
        r"^(?:en\s+)?conserve\s+(?:de|d)\s+",
        " ",
        produit,
    )
    produit = re.sub(r"^ou\s+", " ", produit)

    produit = re.sub(
        r"\s+(?:et\s+)?(?:pas|sans)\s+(?:de\s+|du\s+|de\s+la\s+|d\s+|le\s+|la\s+|les\s+|l\s+)?[^,;]*$",
        " ",
        produit,
    )
    produit = re.sub(
        r"\s+(?:que|parce\s+que|car)\s+(?:vous|tu|je|on|nous)\b.*$",
        " ",
        produit,
    )

    if "lait entier" in produit and "citron" in produit:
        produit = re.sub(r"\bcitron\b", " ", produit)

    jours_livraison = (
        r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|"
        r"demain|apres demain|aujourd hui|ce soir|ce midi|midi|matin|soir|"
        r"\d{1,2}\s+[a-z]+"
    )
    produit = re.sub(
        rf"\bpour\s+(?:le|la|les|l)\s+[a-z0-9\s]{{1,70}}\s+pour\s+(?:{jours_livraison})\b.*$",
        " ",
        produit,
    )
    produit = re.sub(
        rf"\bpour\s+(?:{jours_livraison})\b.*$",
        " ",
        produit,
    )
    produit = re.sub(
        r"\s+pour\s+(?:le|la|les|l)\s+"
        r"(?:bar|restaurant|resto|hotel|bistrot|brasserie|cantine|snack)\b.*$",
        " ",
        produit,
    )
    produit = re.sub(
        r"\b(?:merci|remercie|remercions|au revoir|bonne journee|bonne soiree|a demain|sous titrage|voila|on restera|on reste|ce sera tout|ca sera tout)\b.*$",
        " ",
        produit,
    )
    produit = re.sub(
        r"\s+(?:(?:aussi|egalement)\s+)?(?:s\s+il\s+vous\s+plait|s\s+il\s+te\s+plait|svp)\b.*$",
        " ",
        produit,
    )
    produit = re.sub(r"\s+(?:aussi|egalement)\s*$", " ", produit)
    produit = re.sub(r"\bet\s*$", " ", produit)

    # Une transition peut suivre le produit dans la meme clause. Elle est
    # retiree seulement si sa partie droite est, a elle seule, non-produit.
    parties = re.split(r"\s+et\s+", produit)
    if len(parties) > 1:
        suffixe = parties[-1].strip()
        if (
            _est_queue_livraison(suffixe)
            or analyser_role_semantique_clause(suffixe) in {
                "DELIVERY",
                "ORDER_DISCOURSE",
                "POLITENESS",
            }
        ):
            produit = " et ".join(parties[:-1]).strip()

    return re.sub(r"\s+", " ", produit).strip()


def _formes_discours_commande() -> set[str]:
    """Retourne les flexions usuelles des verbes qui portent le discours."""
    formes: set[str] = set()
    for infinitif in VERBES_DISCOURS_COMMANDE:
        formes.add(infinitif)
        if not infinitif.endswith("er"):
            continue
        radical = infinitif[:-2]
        formes.update(
            {
                radical,
                f"{radical}e",
                f"{radical}es",
                f"{radical}ez",
                f"{radical}ons",
                f"{radical}ent",
                f"{radical}ais",
                f"{radical}ait",
                f"{radical}ions",
                f"{radical}iez",
                f"{radical}aient",
                f"{radical}erai",
                f"{radical}eras",
                f"{radical}era",
                f"{radical}erons",
                f"{radical}erez",
                f"{radical}eront",
                f"{radical}ant",
            }
        )
    return formes


FORMES_DISCOURS_COMMANDE = _formes_discours_commande()


def _clause_est_discours_commande_sans_noyau_produit(
    clause: str,
) -> bool:
    """Classe ORDER_DISCOURSE seulement si aucun lexeme produit ne subsiste."""
    tokens = normaliser_texte(clause).split()
    if not tokens:
        return True

    marqueurs_discours = FORMES_DISCOURS_COMMANDE | NOMS_DISCOURS_COMMANDE
    if not any(token in marqueurs_discours for token in tokens):
        return False

    noyau = [
        token
        for token in tokens
        if token not in marqueurs_discours
        and token not in TOKENS_SANS_NOYAU_PRODUIT
        and token not in TOKENS_CALENDRIER
        and token not in TOKENS_CONDITIONNEMENT_SANS_PRODUIT
        and not re.fullmatch(r"\d+(?:\.\d+)?", token)
    ]
    return not noyau


def analyser_role_semantique_clause(clause: str) -> str:
    """Classe une clause avant toute recherche de produit."""
    texte = _normaliser_clause_parse(clause)
    if not texte:
        return "ORDER_DISCOURSE"

    # Une presentation d'etablissement sans quantite est une identite client,
    # pas un article. Cette grammaire ne connait aucun nom de client.
    if (
        not re.search(r"\b\d+(?:\.\d+)?\b", texte)
        and re.match(
            r"^(?:(?:le|la|les|l)\s+)?"
            r"(?:restaurant|resto|bar|hotel|bistrot|brasserie|snack|"
            r"cantine|camping|maison|societe|sarl)\b",
            texte,
        )
        and re.search(r"\b(?:a|au|aux|dans|de|du|des|chez)\b", texte)
    ):
        return "CLIENT"
    if (
        not re.search(r"\b\d+(?:\.\d+)?\b", texte)
        and re.search(r"\bde\s+chez\b", texte)
    ):
        return "CLIENT"

    if re.search(
        r"\b(?:a|en)\s+la\s+place\b|"
        r"\bremplac(?:e|er|ez|era|erai|erons|eront)\b",
        texte,
    ):
        return "SUBSTITUTION"

    if re.match(r"^si\s+(?:vous|tu|on)\b", texte):
        return "CONDITION"

    if re.match(
        r"^(?:(?:dans|sur)\s+(?:ma|la|notre)\s+commande\s+)?"
        r"(?:pas\s+(?:de|du|des|la|le|les)|"
        r"ne\s+\w+(?:\s+\w+){0,3}\s+pas\b|"
        r"annul(?:e|er|ez)\b|retir(?:e|er|ez)\b|"
        r"supprim(?:e|er|ez)\b)",
        texte,
    ):
        return "NEGATION"

    if re.match(
        r"^(?:j\s+en\s+ai|je(?:\s+viens\s+de)?|"
        r"nous(?:\s+venons\s+de)?)\s+retrouv\w*\b|"
        r"^(?:receptionn\w*|recev\w*)\b",
        texte,
    ) and not re.search(r"\b\d+(?:\.\d+)?\b", texte):
        return "INFORMATION_ONLY"

    if re.fullmatch(
        r"(?:re)?(?:bonjour|bonsoir)|merci(?:\s+beaucoup)?|"
        r"(?:je\s+suis\s+)?desole(?:e)?|excusez\s+moi|pardon|"
        r"s\s+il\s+(?:vous|te)\s+plait|au\s+revoir|"
        r"bonne\s+(?:journee|soiree)|adios|a\s+bientot",
        texte,
    ):
        return "POLITENESS"

    if _est_expression_horaire_livraison(texte):
        return "DELIVERY"

    if re.fullmatch(r"(?:\d+\s+)?livraison", texte):
        return "DELIVERY"

    if re.fullmatch(
        r"(?:\d+(?:\.\d+)?\s+)?livraison(?:\s+pour)?(?:\s+le)?\s+"
        r"(?:aujourd\s+hui|demain|apres\s+demain|ce\s+matin|"
        r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
        r"(?:\s+matin|\s+midi|\s+soir)?|"
        r"\d{1,2}\s*(?:h|heure|heures)(?:\s+\d{1,2})?",
        texte,
    ):
        return "DELIVERY"

    if re.fullmatch(
        r"(?:il\s+)?me\s+faudrait|(?:il\s+)?nous\s+faudrait|"
        r"j\s+ai\s+ete\s+coupe|on\s+a\s+ete\s+coupe|"
        r"on\s+est\s+parti|vous\s+me\s+mettez|"
        r"tu\s+as\s+toutes\s+les\s+references|"
        r"vous\s+avez\s+toutes\s+les\s+references|"
        r"prends?\s+(?:ton|votre)\s+temps|"
        r"tu\s+regarderas|il\s+en\s+prend\s+souvent|"
        r"et\s+pour\s+finir|pour\s+finir|plus",
        texte,
    ):
        return "ORDER_DISCOURSE"

    if re.fullmatch(
        r"(?:en\s+)?(?:bouteille|bocal|boite|carton|sachet|poche|seau)",
        texte,
    ):
        return "ORDER_DISCOURSE"

    qualificatif = re.sub(
        r"^(?:le|la|les|l)\s+|\s+(?:pareil|pareille|aussi)$",
        "",
        texte,
    ).strip()
    if qualificatif and all(
        token in QUALIFICATIFS_PRODUIT
        for token in qualificatif.split()
    ):
        return "QUALIFIER"

    if re.fullmatch(
        r"(?:est\s+ce\s+que\s+)?(?:ce|c)\s+(?:est|serait)\s+possible\s+"
        r"(?:d\s+)?avoir|"
        r"(?:est\s+ce\s+que\s+)?(?:vous\s+)?(?:pourriez|pouvez)\s+"
        r"(?:m|nous)\s+(?:avoir|amener)|"
        r"(?:en\s+)?(?:ajout|rajout|complement)\s+(?:de|a|sur)\s+"
        r"(?:ma|la|notre|une)\s+(?:precedente\s+)?commande|"
        r"[a-z][a-z0-9\s]{1,60}\s+"
        r"(?:ajout\w*|rajout\w*)\s+(?:a\s+la\s+)?commande(?:\s+de)?",
        texte,
    ):
        return "ORDER_DISCOURSE"

    if _clause_est_discours_commande_sans_noyau_produit(texte):
        return "ORDER_DISCOURSE"

    return "PRODUCT_ITEM"


def _clause_hors_produit(
    clause_norm: str,
) -> bool:
    clause_norm = clause_norm.strip()

    if analyser_role_semantique_clause(clause_norm) in ROLES_SEMANTIQUES_NON_PRODUIT:
        return True

    if _clause_est_discours_commande_sans_noyau_produit(clause_norm):
        return True

    if clause_norm in MOTS_INTENTION_DEBUT:
        return True

    if clause_norm in {
        "merci",
        "au revoir",
        "bon",
        "alors",
        "oui",
        "donc",
        "ensuite",
        "faites moi",
        "faites nous",
        "il me faudrait",
        "il me faut",
        "je voudrais",
        "je souhaite",
        "je vais vous prendre",
        "je vais vous en prendre",
        "prendre demain",
        "prendre pour demain",
        "egalement",
        "voila",
        "la derniere fois",
        "la verte",
        "le vert",
        "bonne journee",
        "bonne soiree",
        "excusez moi",
        "pardon",
        "si vous avez",
        "s il vous plait",
        "s il te plait",
        "comment on appelle",
        "comment ca s appelle",
        "comment ca s appelait",
        "comment dire",
        "comment tu dis",
        "voila excusez moi",
        "voila ce sera tout",
        "voila c est tout",
        "c est tout",
        "ce sera tout",
        "c est la marque que tu preferes",
        "la marque que tu preferes",
        "bonjour basco",
        "bonsoir basco",
    }:
        return True

    # Une date ou une transition peut contenir un nombre sans designer un
    # article. La presence d'un nombre ne constitue jamais, seule, une preuve
    # de produit.
    if re.fullmatch(
        r"(?:le\s+)?\d{1,2}\s+"
        r"(?:janvier|fevrier|mars|avril|mai|juin|juillet|aout|"
        r"septembre|octobre|novembre|decembre)(?:\s+\d{2,4})?",
        clause_norm,
    ):
        return True
    if re.fullmatch(
        r"(?:pour\s+)?(?:aujourd hui|demain|apres demain|ce matin|"
        r"ce midi|ce soir|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
        clause_norm,
    ):
        return True

    prefixes = (
        "je crois",
        "je pense",
        "excusez moi",
        "pardon",
        "ca fait",
        "ca doit faire",
        "vous m avez dit",
        "vous ne m aviez",
        "a livrer",
        "je repete la commande",
        "je vous repete la commande",
        "ce lundi",
        "ce mardi",
        "ce mercredi",
        "ce jeudi",
        "ce vendredi",
        "ce samedi",
        "ce dimanche",
        "pour la pizzeria",
        "pour le restaurant",
        "pour la cantine",
        "pour aujourd hui",
        "pour ce soir",
        "en fait c est la",
        "en fait c est le",
        "pour faire un complement",
        "faire un complement",
        "un complement sur la commande",
        "complement sur la commande",
        "je vais rajouter",
        "je vais ajouter",
        "et apres on passe",
        "apres on passe",
        "on passe aux",
        "on passe au",
        "on restera",
        "on reste",
        "ce sera",
        "ca sera",
        "j appelle",
        "je t appelle",
        "je vous appelle",
        "tu l as sur le cadencier",
        "vous l avez sur le cadencier",
        "bien commander",
        "hier j avais commande",
        "hier j ai commande",
        "comme j avais commande",
        "la nouvelle que vous avez",
        "si vous avez",
        "a suivre",
        "et c est bon",
        "c est bon",
        "je sais pas",
        "je ne sais pas",
        "marque que tu preferes",
        "marque que vous preferez",
        "sans ",
    )

    if not re.match(r"^\d+(?:\.\d+)?\b", clause_norm) and re.search(
        r"\b(?:restaurant|resto|bar|hotel|bistrot|brasserie|snack|"
        r"beach|brunch)\b",
        clause_norm,
    ) and (
        re.search(r"\b(?:a|de|chez)\s+[a-z]", clause_norm)
        or clause_norm.startswith(("ici ", "c est ", "le ", "la ", "les "))
    ):
        return True

    if re.match(
        r"^commande\s+(?:pour\s+)?(?:le|la|les|l)?\s*[a-z]",
        clause_norm,
    ):
        return True

    if re.fullmatch(
        r"pour\s+(?:le|la|les|l)\s+[a-z][a-z0-9\s]{1,60}",
        clause_norm,
    ):
        return True

    # Fins de phrase, connecteurs et metadonnees isoles ne deviennent jamais
    # des produits, meme si Whisper leur rattache un nombre. Les motifs sont
    # purement grammaticaux et conservent tout groupe nominal possedant un nom
    # apres ``de`` (``saute de veau`` reste donc eligible).
    sans_quantite_initiale = re.sub(
        r"^\d+(?:\.\d+)?\s*(?:pieces?|unites?|boites?|cartons?|colis|"
        r"poches?|pots?|paquets?|sacs?|seaux?|bidons?)?\s*",
        "",
        clause_norm,
    ).strip()
    if re.fullmatch(
        r"(?:une?\s+)?(?:belle|bonne)\s+(?:journee|soiree)"
        r"(?:\s+pour\s+(?:demain|aujourd hui))?|"
        r"pareil|egalement|sinon\s+n\s+importe(?:\s+quoi)?|"
        r"(?:environ|a\s+peu\s+pres)\s*\d+(?:\.\d+)?|"
        r"(?:saut|saute|seau|sot)\s+de|"
        r"(?:en\s+)?(?:fr|bio|biologique|aop|igp|vce)",
        sans_quantite_initiale,
    ):
        return True

    return clause_norm.startswith(prefixes)


def _est_entete_enumeration_sans_article(
    clause_norm: str,
    clauses_suivantes: list[str],
) -> bool:
    """Detecte un en-tete de famille suivi d'une vraie enumeration.

    Un en-tete comme ``avec des glaces`` transporte un contexte, mais ne
    commande aucune ligne. Deux elements quantifies doivent suivre : cette
    exigence evite de supprimer un article reel simplement non quantifie.
    """
    if re.search(r"\b\d+(?:\.\d+)?\b", clause_norm):
        return False
    motif_entete = re.compile(
        r"\b(?:(?:et\s+)?(?:avec|concernant|pour|cote)\s+"
        r"(?:des|les|nos|vos)|"
        r"(?:et\s+)?(?:on|nous)\s+pass\w*\s+(?:a|au|aux|sur)|"
        r"(?:apres|ensuite)\s+(?:des|les|aux))\b"
    )
    entete = motif_entete.search(clause_norm)
    if entete is None:
        return False
    prefixe = clause_norm[: entete.start()].strip()
    if prefixe and analyser_role_semantique_clause(prefixe) not in (
        ROLES_SEMANTIQUES_NON_PRODUIT
    ):
        return False

    elements_quantifies = 0
    for suivante in clauses_suivantes[:3]:
        suivante_norm = _normaliser_clause_parse(suivante)
        if re.match(r"^\d+(?:\.\d+)?\b", suivante_norm):
            elements_quantifies += 1
        if elements_quantifies >= 2:
            return True
    return False


def _fusionner_alternatives_mentions(
    mentions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Conserve ``X ou Y`` comme une seule intention de commande.

    Le parseur quantitatif peut legitiment detecter deux groupes nominaux,
    mais la conjonction ``ou`` exprime une alternative et non deux lignes a
    commander. La relation est stockee explicitement pour que le matching et
    l'UI puissent l'exploiter sans perdre l'un des deux libelles.
    """
    resultat: list[dict[str, Any]] = []
    index = 0
    while index < len(mentions):
        courante = dict(mentions[index])
        source = normaliser_texte(str(courante.get("texte_source") or ""))
        produit = normaliser_texte(
            str(courante.get("produit_normalise") or "")
        )
        if (
            index + 1 < len(mentions)
            and (source.endswith(" ou") or produit.endswith(" ou"))
        ):
            suivante = dict(mentions[index + 1])
            alternative_a = re.sub(r"\s+ou$", "", produit).strip()
            alternative_b = normaliser_texte(
                str(suivante.get("produit_normalise") or "")
            )
            if alternative_a and alternative_b:
                courante["produit_normalise"] = alternative_a
                courante["texte_produit"] = alternative_a
                courante["texte_source"] = " ".join(
                    part
                    for part in (
                        str(courante.get("texte_source") or "").strip(),
                        str(suivante.get("texte_source") or "").strip(),
                    )
                    if part
                )
                courante["alternatives_produit"] = [
                    alternative_a,
                    alternative_b,
                ]
                courante["modalite_demande"] = "ALTERNATIVE"
                courante["ambigu"] = True
                raisons = set(courante.get("raisons_ambiguite") or [])
                raisons.update(suivante.get("raisons_ambiguite") or [])
                raisons.add("alternative_produit_a_resoudre")
                if (
                    courante.get("quantite_principale")
                    != suivante.get("quantite_principale")
                    or courante.get("unite_principale")
                    != suivante.get("unite_principale")
                ):
                    raisons.add("quantites_alternatives_differentes")
                courante["raisons_ambiguite"] = sorted(raisons)
                resultat.append(courante)
                index += 2
                continue
        resultat.append(courante)
        index += 1
    return resultat


def _annoter_modalites_demande(
    transcription: str,
    mentions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ajoute une modalite sans transformer celle-ci en nom de produit."""
    resultat: list[dict[str, Any]] = []
    for original in mentions:
        mention = dict(original)
        mention.setdefault("modalite_demande", "CERTAINE")
        produit_mention = normaliser_texte(
            str(mention.get("produit_normalise") or "")
        )
        motif_historique_inline = (
            r"\b(?:"
            r"(?:celui|celle|ceux|celles)?\s*qu?e?\s+"
            r"(?:je|j|on|nous)\s+(?:vous\s+)?prends?\s+"
            r"(?:d\s+habitude|habituellement)|"
            r"comme\s+(?:d\s+habitude|la\s+derniere\s+fois)|"
            r"toujours\s+(?:la|le|les)?\s*meme(?:s)?|"
            r"(?:la|l|les)?\s*ancienne(?:s)?\s+"
            r"(?:reference|references|ref|refs)"
            r")\b"
        )
        if re.search(motif_historique_inline, produit_mention):
            produit_nettoye = re.sub(
                motif_historique_inline,
                " ",
                produit_mention,
            )
            produit_nettoye = re.sub(r"\s+", " ", produit_nettoye).strip()
            if produit_nettoye:
                mention["produit_normalise"] = produit_nettoye
                mention["texte_produit"] = produit_nettoye
            mention["preference_historique_compatible"] = True
            mention["modalite_demande"] = "HABITUELLE"
            mention.setdefault("raisons_ambiguite", []).append(
                "preference_historique_inline"
            )
        source_mention = normaliser_texte(
            str(mention.get("texte_source") or "")
        )
        condition_postposee = bool(re.search(
            r"\bsi\s+(?:vous|tu|on)\s+"
            r"(?:(?:en\s+)?(?:avez|aviez|auriez|as|avais|aurais)|"
            r"(?:pouvez|peux|peut)\s+(?:avoir|faire|fournir))\b",
            source_mention,
        ))
        marqueur_preference = bool(
            re.search(r"\bplutot\b", source_mention)
        )
        if mention.get("preference_historique_compatible"):
            mention["modalite_demande"] = "HABITUELLE"
        elif mention.get("alternatives_produit"):
            mention["modalite_demande"] = "ALTERNATIVE"
        elif condition_postposee:
            mention["modalite_demande"] = "CONDITIONNELLE"
            mention["demande_conditionnelle"] = True
        elif marqueur_preference:
            mention["modalite_demande"] = "PREFERENCE"
        resultat.append(mention)
    return resultat


def decouper_clauses_produits(
    transcription: str,
    preserver_modalites: bool = False,
) -> list[str]:
    texte = normaliser_transcription_produits(
        transcription
    )
    texte = re.sub(
        (
            r"\b(?:c\s+est\s+pour\s+passer|"
            r"ce\s+sera\s+pour\s+passer|"
            r"c\s+est\s+pour|ce\s+sera\s+pour|"
            r"pour\s+passer|passer|pour)\s+une\s+commande"
            r"(?:\s+pour)?\b"
        ),
        " ",
        texte,
        count=1,
    ).strip()
    texte = remplacer_nombres_en_chiffres(texte)
    texte = _normaliser_oraux_decimaux(texte)
    texte = _retirer_contexte_calendaire_produits(texte)

    if preserver_modalites:
        motif_conditionnel = (
            r"(?P<prefix>^|\s+(?:et|ainsi\s+que|ainsi\s+qu)\s+)"
            r"si\s+(?:vous|tu|on)\s+"
            r"(?:(?:en\s+)?(?:avez|aviez|auriez|as|avais|aurais)|"
            r"(?:faites|fais|fait|vendez|vends|vend|proposez|proposes|propose|"
            r"fournissez|fournis|fournit)|"
            r"(?:pouvez|peux|peut)\s+"
            r"(?:avoir|faire|vendre|proposer|fournir))\s+"
            r"(?:(?:du|des|de\s+la|de\s+l|d)\s+)?"
        )

        def conserver_condition(match: re.Match[str]) -> str:
            prefixe = match.group("prefix")
            separateur = "" if not prefixe.strip() else ", "
            return f"{separateur}modaliteconditionnelle "

        texte = re.sub(
            motif_conditionnel,
            conserver_condition,
            texte,
        )

    # Une disponibilite positive introduit un second article, pas un
    # qualificatif du premier. Les conditions negatives/substitutions ne
    # passent pas par cette coupe et conservent leur traitement specifique.
    texte = re.sub(
        r"\s+(?:et|ainsi\s+que|ainsi\s+qu)\s+si\s+(?:vous|tu|on)\s+"
        r"(?:(?:en\s+)?(?:avez|aviez|auriez|as|avais|aurais)|"
        r"(?:faites|fais|fait|vendez|vends|vend|proposez|proposes|propose|"
        r"fournissez|fournis|fournit)|"
        r"(?:pouvez|peux|peut)\s+(?:avoir|faire|vendre|proposer|fournir))\s+"
        r"(?:(?:du|des|de\s+la|de\s+l|d)\s+)?",
        ", ",
        texte,
    )
    # Whisper rend parfois le nombre ``six`` par ``si`` entre deux groupes
    # nominaux. Sans pronom ni marqueur de condition, on peut restaurer la
    # quantite sans connaitre le produit qui suit.
    texte = re.sub(
        r"(?<=[a-z])\s+si\s+"
        r"(?!(?:vous|tu|on|possible|besoin|jamais|seulement)\b)"
        r"(?=[a-z][a-z0-9-]{2,})",
        ", 6 ",
        texte,
    )
    # Deux groupes nominaux coordonnes peuvent chacun designer un article
    # meme lorsque le second n'a pas de quantite repetee (``une fourme et des
    # pistoles de chocolat``). On limite volontairement la coupe aux groupes
    # ``des NOM de NOM`` : un simple ``ail et fines herbes`` reste un libelle
    # compose et n'est pas fragmente.
    texte = re.sub(
        r"\s+et\s+(?=des\s+[a-z][a-z0-9-]*\s+(?:de|d)\s+[a-z])",
        ", ",
        texte,
    )
    # Une demande de disponibilité peut porter sur le second article après
    # sa désignation (``un arôme et des gambas si vous avez...``). La coupe
    # s'appuie sur la structure grammaticale complète, pas sur un nom de
    # produit particulier, afin de ne plus fusionner le second article avec
    # le premier.
    texte = re.sub(
        r"\s+et\s+(?=des\s+[a-z][a-z0-9-]*"
        r"(?:\s+[a-z][a-z0-9-]*){0,4}\s+si\s+(?:vous|tu|on)\s+)",
        ", ",
        texte,
    )
    # Une transition explicite vers un second groupe nominal ouvre une
    # nouvelle mention meme si la seconde quantite est omise.
    texte = re.sub(
        r"\s+et\s+(?:ensuite|apres)\s+"
        r"(?=(?:du|des|de\s+la|de\s+l|d)\s+[a-z])",
        ", ",
        texte,
    )
    # Erreur ASR recurrente : la conjonction orale est rendue par ``1``
    # devant une nouvelle quantite munie de son unite.
    texte = re.sub(
        r"(?<=[a-z])\s+1\s+(?=\d+(?:\.\d+)?\s*(?:kg|kilos?|l|litres?)\b)",
        ", ",
        texte,
    )

    motif_conditionnement_imbrique = re.compile(
        r"\b(?P<nb>\d+(?:\.\d+)?)\s+"
        r"(?:sacs?|poches?|cartons?|boites?|seaux?|bidons?|packs?|colis)\s+"
        r"(?:de|d)\s+(?P<taille>\d+(?:\.\d+)?)\s*"
        r"(?P<unite>kg|kilos?|kilogrammes?|l|litres?)\b"
    )

    def aplatir_conditionnement(match: re.Match[str]) -> str:
        total = float(match.group("nb")) * float(match.group("taille"))
        return f"{total:g} {match.group('unite')}"

    texte = motif_conditionnement_imbrique.sub(
        aplatir_conditionnement,
        texte,
    )
    texte = re.sub(
        r"\bet\s+(?=(?:il\s+me\s+faudrait|il\s+me\s+faut|il\s+m\s+aurait\s+fallu|il\s+faudrait|faudrait)\b)",
        ", ",
        texte,
    )
    texte = re.sub(
        (
            r"\bet\s+(?:avec\s+ca|apres\s+ca)\s+"
            r"(?:(?:je|on)\s+(?:vous\s+)?"
            r"(?:donnerai|prendrai|prendrait|prendrons)\s+)?"
            r"(?=(?:\d+(?:\.\d+)?|un|une|deux|trois|quatre|cinq|six)\b)"
        ),
        ", ",
        texte,
    )

    marqueurs_debut_commande = (
        "ce serait pour commander",
        "ce serait pour recommander",
        "je voudrais commander",
        "je souhaite recommander",
        "je veux commander",
        "c est pour une commande",
        "ce sera pour une commande",
        "pour passer une commande",
        "passer une commande",
        "pour une commande",
        "mettez moi",
        "mettez nous",
        "mettez-moi",
        "mettez-nous",
        "rajoutez moi",
        "rajoutez nous",
        "ajoutez moi",
        "ajoutez nous",
        "livrez moi",
        "livrez nous",
        "on va vous prendre",
        "on va prendre",
        "on prendra",
        "on vous prendra",
        "faites moi",
        "faites nous",
        "je vais vous en prendre",
        "je vais vous prendre",
        "je vais prendre",
        "je vais rajouter",
        "je vais ajouter",
        "je vous prendrai",
        "vous pourrez avoir",
        "pourrez avoir",
        "on aurait besoin",
        "j aurais besoin",
        "je voudrais",
        "je souhaite",
        "je souhaiterais",
        "je commande",
        "recommander",
        "commander",
        "il me faudrait",
        "il me faut",
        "il m aurait fallu",
        "il faudrait",
        "il faudra",
        "il nous faudra",
        "faudrait",
    )
    clauses_avant_coupe: list[str] = []
    motif_produit_puis_quantite = re.compile(
        (
            r"(?:^|[,;])\s*(?P<produit>[a-z][a-z0-9\s]{2,200}?)"
            r"[,\s]+(?:il\s+me\s+faudrait|il\s+me\s+faut|il\s+m\s+aurait\s+fallu|il\s+faudrait)\s+"
            r"(?P<quantite>\d+(?:\.\d+)?)"
            r"\s*(?P<unite>"
            + UNITES_REGEX
            + r")\b"
        )
    )
    for match in motif_produit_puis_quantite.finditer(texte):
        produit_brut = match.group("produit")
        produit = _nettoyer_debut_clause(
            produit_brut
        )
        produit = _normaliser_produit_extrait(produit)
        if (
            produit
            and analyser_role_semantique_clause(produit_brut)
            not in ROLES_SEMANTIQUES_NON_PRODUIT
            and _clause_ressemble_a_produit(produit)
        ):
            clauses_avant_coupe.append(
                " ".join(
                    part
                    for part in (
                        match.group("quantite"),
                        match.group("unite"),
                        "de",
                        produit,
                    )
                    if part
                )
            )

    # Suppression des coupes par position (début/fin) pour supporter 
    # les commandes non contiguës et les blocs produits éclatés.

    morceaux_bruts = [
        morceau.strip()
        for morceau in re.split(
            r"[;,]|(?<!\d)\.(?!\d)",
            texte,
        )
        if morceau.strip()
    ]
    clauses_initiales: list[str] = []
    index_morceau = 0
    while index_morceau < len(morceaux_bruts):
        morceau = morceaux_bruts[index_morceau]
        suivant = (
            morceaux_bruts[index_morceau + 1]
            if index_morceau + 1 < len(morceaux_bruts)
            else ""
        )
        # Un prénom isolé suivi immédiatement d'un marqueur d'enseigne est
        # un préambule client, pas un article autonome.
        if (
            re.fullmatch(r"[a-z][a-z0-9]{2,30}", morceau)
            and re.search(
                r"\b(?:restaurant|resto|bar|hotel|bistrot|brasserie|snack)\b",
                suivant,
            )
        ):
            clauses_initiales.append(f"{morceau} {suivant}")
            index_morceau += 2
            continue
        clauses_initiales.append(morceau)
        index_morceau += 1

    clauses: list[str] = []
    separateur_et = (
        r"\b(?:et|ainsi\s+que|ainsi\s+qu)\s+"
        r"(?=(?:\d+(?:\.\d+)?(?:"
        r"\s*(?:kg|kilos?|kilogrammes?|g|grammes?|"
        r"l|litres?|ml|cl)\b|\b)|"
        r"un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|"
        r"dix|onze|douze|treize|quatorze|quinze|seize|vingt)\b)"
    )

    for clause in clauses_initiales:
        morceaux_principaux = re.split(
            separateur_et,
            clause,
        )
        morceaux: list[str] = []
        separateur_conditionnement_interne = (
            r"(?:(?<=[a-z])|(?<=[a-z]\d)|(?<=[a-z]\d\d))"
            r"(?<!des)(?<!une)(?<!\bx)(?<!\bfois)\s+"
            r"(?=(?!\d+(?:\.\d+)?\s*(?:h|heure|heures)\b)"
            r"(?:(?:\d+(?:\.\d+)?)\s+)?"
            r"(?:des?\s+)?"
            r"(?:boites?|cartons?|poches?|sachets?|"
            r"paquets?|pieces?)"
            r"(?:\s+(?:de|d))?\s+[a-z]|"
            r"\d+(?:\.\d+)?\s*"
            r"(?:kg|kilos?|litres?)\s+(?:de\s+|d\s+)?[a-z])"
        )
        for morceau_principal in morceaux_principaux:
            morceaux_conditionnement = re.split(
                separateur_conditionnement_interne,
                morceau_principal,
            )
            for morceau_conditionnement in morceaux_conditionnement:
                morceaux.extend(
                    re.split(
                        (
                            r"(?<!en)(?<!x)(?<!\bx)(?<!\bfois)\s+"
                            r"(?=(?!\d+(?:\.\d+)?\s*(?:h|heure|heures)\b)"
                            r"\d+(?:\.\d+)?\s+"
                            r"(?!(?:g|grammes?|kg|kilos?|l|litres?)\b)"
                            r"[a-z])"
                        ),
                        morceau_conditionnement,
                    )
                )

        for morceau in morceaux:
            propre = _nettoyer_debut_clause(morceau)
            propre_norm = _normaliser_clause_parse(propre)
            # Une introduction client/livraison peut partager la phrase avec
            # le premier article. Extraire d'abord la sous-clause quantifiee
            # empeche le role CLIENT de faire perdre cet article.
            sous_clause_commande = _couper_avant_quantite_commande(propre_norm)
            if (
                sous_clause_commande != propre_norm
                and re.match(r"^\d+(?:\.\d+)?", sous_clause_commande)
            ):
                propre = sous_clause_commande
                propre_norm = sous_clause_commande

            if (
                propre
                and propre not in {"et", "de", "d"}
                and (
                    not _clause_hors_produit(
                        propre_norm
                    )
                    or _clause_peut_completer_produit_precedent(
                        propre_norm
                    )
                )
            ):
                clauses.append(propre)

    toutes_clauses = clauses_avant_coupe + clauses
    clauses_fusionnees: list[str] = []
    index_clause = 0
    while index_clause < len(toutes_clauses):
        courante = toutes_clauses[index_clause]
        suivante = (
            toutes_clauses[index_clause + 1]
            if index_clause + 1 < len(toutes_clauses)
            else ""
        )
        if courante == "modaliteconditionnelle" and suivante:
            clauses_fusionnees.append(
                f"modaliteconditionnelle {suivante}"
            )
            index_clause += 2
            continue
        debut_emballage = re.match(
            r"^(?:un|une|des\s+)?(?:petits?|petites?|grands?|grandes?|"
            r"gros|grosse|grosses)\s*$",
            courante,
        ) or re.match(
            r"^(?P<quantite>\d+(?:\.\d+)?)\s+"
            r"(?:petits?|petites?|grands?|grandes?|gros|grosse|grosses)$",
            courante,
        )
        if debut_emballage and re.match(
            r"^(?:sachets?|poches?|sacs?|pots?|boites?|cartons?|colis|"
            r"paquets?|barquettes?|bouteilles?|bidons?|seaux?)\b",
            suivante,
        ):
            quantite = (
                debut_emballage.groupdict().get("quantite")
                if hasattr(debut_emballage, "groupdict")
                else None
            ) or "1"
            clauses_fusionnees.append(f"{quantite} {suivante}")
            index_clause += 2
            continue
        clauses_fusionnees.append(courante)
        index_clause += 1

    return clauses_fusionnees


def _normaliser_unite(
    unite_brute: str | None,
) -> str | None:
    if not unite_brute:
        return None

    unite = UNITES_EQUIVALENCES.get(
        unite_brute.strip(),
        unite_brute.strip().upper(),
    )

    return unite or None


def _adapter_quantite_unite(
    quantite: float,
    unite: str | None,
) -> tuple[float, str | None, list[dict[str, Any]]]:
    precisions: list[dict[str, Any]] = []

    if unite == "G":
        precisions.append(
            {
                "type": "conversion_unite",
                "detail": (
                    f"{quantite} G converti en KG"
                ),
            }
        )
        return round(quantite / 1000, 4), "KG", precisions

    return quantite, unite, precisions


def _arrondir_quantite_commande(
    quantite: float,
) -> float:
    arrondi = round(quantite)

    if abs(quantite - arrondi) <= 0.05:
        return float(arrondi)

    return round(quantite, 3)


def _convertir_taille_conditionnement(
    valeur: str,
    unite: str,
) -> tuple[str | None, float | None]:
    brut = valeur.replace(",", ".").strip()

    try:
        quantite = float(brut)
    except ValueError:
        return None, None

    unite_norm = unite.lower().strip()

    if unite_norm in {"kg", "k"}:
        return "KG", quantite

    if unite_norm in {"g"}:
        return "KG", quantite / 1000

    if unite_norm in {"l"}:
        return "L", quantite

    if unite_norm in {"cl"}:
        return "L", quantite / 100

    if unite_norm in {"ml"}:
        return "L", quantite / 1000

    return None, None


def _analyser_conditionnement_article(
    candidat: dict[str, Any],
) -> dict[str, Any]:
    # La normalisation lexicale commune remplace le point decimal par un
    # espace ("2.5L" -> "2 5l"). Elle est adaptee au fuzzy matching mais pas
    # a l'arithmetique de conditionnement. Repartir du libelle brut et ne
    # conserver le point qu'entre deux chiffres.
    libelle = enlever_accents(
        str(
            candidat.get("libelle_article")
            or candidat.get("libelle_normalise")
            or ""
        )
    ).casefold()
    libelle = re.sub(r"(?<=\d)\s*[,\.]\s*(?=\d)", ".", libelle)
    libelle = re.sub(r"[^a-z0-9.]+", " ", libelle)
    libelle = re.sub(r"\s+", " ", libelle).strip()
    ratio_net_par_unite = float(
        candidat.get("ratio_net_par_unite", 0.0)
        or 0.0
    )
    quantite_habituelle = float(
        candidat.get("quantite_habituelle_commande", 0.0)
        or 0.0
    )

    meta = {
        "unite_commande": str(candidat.get("unite_vente") or "PCE").upper(),
        "taille_kg_par_unite": None,
        "taille_l_par_unite": None,
        "nb_sous_unites_colis": None,
        "nb_items_par_unite": None,
        "taille_kg_par_sous_unite": None,
        "taille_l_par_sous_unite": None,
        "source": "defaut_piece",
    }

    motif_multi = re.search(
        (
            r"(?P<count>\d+)\s*x\s*"
            r"(?P<size>\d+(?:[\.,]\d+)?)\s*"
            r"(?P<unit>kg|k|g|l|cl|ml)\b"
        ),
        libelle,
    )
    motif_multi_inverse = re.search(
        (
            r"(?P<size>\d+(?:[\.,]\d+)?)\s*"
            r"(?P<unit>kg|k|g|l|cl|ml)\s*x\s*"
            r"(?P<count>\d+)\s*p?\b"
        ),
        libelle,
    )

    motif_conditionnement_multiple = motif_multi or motif_multi_inverse
    if motif_conditionnement_multiple:
        nb_sous_unites = int(motif_conditionnement_multiple.group("count"))
        unite_base, taille_base = (
            _convertir_taille_conditionnement(
                motif_conditionnement_multiple.group("size"),
                motif_conditionnement_multiple.group("unit"),
            )
        )
        if unite_base == "KG":
            meta["taille_kg_par_unite"] = taille_base
            meta["taille_kg_par_sous_unite"] = taille_base
        elif unite_base == "L":
            meta["taille_l_par_unite"] = taille_base
            meta["taille_l_par_sous_unite"] = taille_base
        meta["nb_sous_unites_colis"] = nb_sous_unites
        meta["source"] = (
            "libelle_multi"
            if motif_multi
            else "libelle_multi_inverse"
        )

        taille_colis = (
            taille_base * nb_sous_unites
            if taille_base is not None
            else None
        )

        # Quand l'article est vendu en pack/carton, ``6X1L`` decrit le
        # contenu total de l'unite commandee et non une bouteille isolee.
        if (
            taille_colis is not None
            and meta["unite_commande"] in UNITES_EMBALLAGE_EXTERIEUR
        ):
            if unite_base == "KG":
                meta["taille_kg_par_unite"] = taille_colis
            elif unite_base == "L":
                meta["taille_l_par_unite"] = taille_colis

        if (
            not candidat.get("unite_vente")
            and ratio_net_par_unite > 0
            and taille_base is not None
            and taille_colis is not None
        ):
            tolerance_unite = max(
                0.05, abs(taille_base) * 0.25
            )
            tolerance_colis = max(
                0.05, abs(taille_colis) * 0.25
            )

            diff_unite = abs(
                ratio_net_par_unite - taille_base
            )
            diff_colis = abs(
                ratio_net_par_unite - taille_colis
            )

            if (
                diff_colis <= tolerance_colis
                and diff_colis + 0.01 < diff_unite
            ):
                meta["unite_commande"] = "COL"
                if unite_base == "KG":
                    meta["taille_kg_par_unite"] = taille_colis
                elif unite_base == "L":
                    meta["taille_l_par_unite"] = taille_colis
            else:
                meta["unite_commande"] = "PCE"

    motif_items = re.search(
        # Les libelles utilisent indifferemment ``X10P``, ``(10P)`` ou
        # simplement ``10P`` pour un compte physique de pieces. Le suffixe P
        # est obligatoire dans la forme sans prefixe afin de ne jamais prendre
        # un poids, un millesime ou une dimension pour un colisage.
        r"(?:(?:x\s*|\(\s*)(?P<count_prefixed>[1-9]\d*)\s*p?\b"
        r"|(?<![a-z0-9])(?P<count_bare>[1-9]\d*)\s*p\b)",
        libelle,
    )

    if motif_items:
        nb_items = int(
            motif_items.group("count_prefixed")
            or motif_items.group("count_bare")
        )
        meta["nb_items_par_unite"] = nb_items
        if meta["source"] == "defaut_piece":
            meta["source"] = "libelle_items"

        if (
            meta["nb_sous_unites_colis"] is None
            and meta["unite_commande"] == "PCE"
        ):
            meta["nb_sous_unites_colis"] = nb_items

        if (
            not candidat.get("unite_vente")
            and quantite_habituelle > 0
            and quantite_habituelle < nb_items
        ):
            meta["unite_commande"] = (
                "CAR"
                if "oeuf" in libelle
                or "seau" in libelle
                or nb_items >= 20
                else "COL"
            )

    if meta["taille_kg_par_unite"] is None and meta["taille_l_par_unite"] is None:
        tailles = list(
            re.finditer(
                r"(?P<size>\d+(?:[\.,]\d+)?)\s*(?P<unit>kg|k|g|l|cl|ml)\b",
                libelle,
            )
        )

        if tailles:
            motif_taille = tailles[-1]
            unite_base, taille_base = (
                _convertir_taille_conditionnement(
                    motif_taille.group("size"),
                    motif_taille.group("unit"),
                )
            )
            if unite_base == "KG":
                meta["taille_kg_par_unite"] = taille_base
            elif unite_base == "L":
                meta["taille_l_par_unite"] = taille_base
            if meta["source"] == "defaut_piece":
                meta["source"] = "libelle_taille_simple"

    if (
        not candidat.get("unite_vente")
        and meta["unite_commande"] == "PCE"
        and meta["taille_l_par_unite"] is not None
        and float(meta["taille_l_par_unite"]) >= 3.0
    ):
        meta["unite_commande"] = "BID"

    if (
        meta["unite_commande"] == "PCE"
        and motif_items
        and quantite_habituelle > 0
        and meta["nb_items_par_unite"] is not None
    ):
        nb_items = int(meta["nb_items_par_unite"])
        if (
            quantite_habituelle >= nb_items
            and abs(
                quantite_habituelle / nb_items
                - round(
                    quantite_habituelle / nb_items
                )
            )
            <= 0.05
        ):
            meta["unite_commande"] = "PCE"

    reference_controle = _charger_references_controle().get(
        str(candidat.get("code_article") or ""),
        {},
    )
    if reference_controle:
        unite_officielle = str(
            reference_controle.get("order_unit") or ""
        ).upper()
        if unite_officielle:
            meta["unite_commande"] = (
                "PCE" if unite_officielle == "PI" else unite_officielle
            )
        try:
            colisage_officiel = float(
                reference_controle.get("pack_size") or 0.0
            )
        except (TypeError, ValueError):
            colisage_officiel = 0.0
        meta["colisage_officiel"] = (
            colisage_officiel if colisage_officiel > 0 else None
        )
        meta["unite_base_officielle"] = str(
            reference_controle.get("base_unit_source") or ""
        ).upper()
        meta["unite_commande_officielle"] = str(
            reference_controle.get("order_unit_source") or ""
        ).upper()

        if (
            colisage_officiel > 1
            and meta["unite_base_officielle"] in {"PCE", "UNI"}
            and meta["unite_commande"] in {"CAR", "COL"}
        ):
            meta["nb_items_par_unite"] = int(
                round(colisage_officiel)
            )

        # Recalcule la capacite apres application de l'unite officielle. Le
        # libelle peut exprimer "6X1L" ou la forme inverse "2K X5P" avant que
        # le code article ne nous apprenne que l'unite ERP est un colis.
        if (
            meta["nb_sous_unites_colis"]
            and meta["unite_commande"] in UNITES_EMBALLAGE_EXTERIEUR
        ):
            nombre = float(meta["nb_sous_unites_colis"])
            if meta["taille_kg_par_sous_unite"] is not None:
                meta["taille_kg_par_unite"] = (
                    float(meta["taille_kg_par_sous_unite"]) * nombre
                )
            if meta["taille_l_par_sous_unite"] is not None:
                meta["taille_l_par_unite"] = (
                    float(meta["taille_l_par_sous_unite"]) * nombre
                )

        # Un libelle simple decrit parfois la poche de base tandis que
        # l'unite officielle est le colis (ex. cossette 2KG, colis de 5).
        if (
            colisage_officiel > 1
            and meta["source"] == "libelle_taille_simple"
            and meta["unite_commande"] in UNITES_EMBALLAGE_EXTERIEUR
            and meta["unite_base_officielle"]
            and meta["unite_commande_officielle"]
            and meta["unite_base_officielle"]
            != meta["unite_commande_officielle"]
        ):
            if meta["taille_kg_par_unite"] is not None:
                meta["taille_kg_par_unite"] = (
                    float(meta["taille_kg_par_unite"]) * colisage_officiel
                )
            if meta["taille_l_par_unite"] is not None:
                meta["taille_l_par_unite"] = (
                    float(meta["taille_l_par_unite"]) * colisage_officiel
                )

        if (
            meta["unite_base_officielle"]
            == meta["unite_commande_officielle"]
        ):
            try:
                poids_moyen = float(
                    reference_controle.get("average_weight") or 0.0
                )
            except (TypeError, ValueError):
                poids_moyen = 0.0
            if poids_moyen > 0:
                meta["taille_kg_par_unite"] = poids_moyen
        meta["source"] = "controle_references_officiel"

    return meta


def _resoudre_quantite_par_taille(
    quantite_voulue: float,
    taille_unite: float | None,
) -> tuple[float | None, float]:
    if taille_unite is None or taille_unite <= 0:
        return None, 0.0

    quantite_theorique = quantite_voulue / taille_unite
    quantite_resolue = max(
        1.0,
        float(round(quantite_theorique)),
    )
    quantite_resolue = _arrondir_quantite_commande(
        quantite_resolue
    )
    quantite_obtenue = quantite_resolue * taille_unite

    ecart_relatif = abs(
        quantite_obtenue - quantite_voulue
    ) / max(quantite_voulue, 0.1)
    score = 30.0 / (1.0 + ecart_relatif)

    return quantite_resolue, round(score, 2)


def _resoudre_quantite_commande_candidat(
    mention: dict[str, Any],
    candidat: dict[str, Any],
) -> dict[str, Any]:
    meta = _analyser_conditionnement_article(
        candidat
    )
    quantite = mention.get("quantite_principale")
    unite = mention.get("unite_principale")
    multiple = mention.get(
        "conditionnement_multiple"
    )
    quantite_habituelle = float(
        candidat.get("quantite_habituelle_commande", 0.0)
        or 0.0
    )
    resolution = {
        "quantite_resolue": None,
        "unite_resolue": meta["unite_commande"],
        "score_conditionnement": 0.0,
        "raisons_resolution": [],
    }

    if quantite is None:
        # L'historique classe les candidats, mais ne constitue jamais une
        # quantite dictee. L'utiliser ici rendait des noms de clients et des
        # commentaires accidentellement commandables.
        resolution["raisons_resolution"].append(
            "quantite_absente_non_resolue"
        )
        return resolution

    code_article = str(candidat.get("code_article") or "")
    reference_controle = _charger_references_controle().get(
        code_article,
        {},
    )
    try:
        colisage_officiel = float(
            reference_controle.get("pack_size") or 0.0
        )
    except (TypeError, ValueError):
        colisage_officiel = 0.0
    unite_base_officielle = str(
        reference_controle.get("base_unit_source") or ""
    ).upper()
    unite_commande_source = str(
        reference_controle.get("order_unit_source") or ""
    ).upper()
    unite_commande_officielle = str(
        reference_controle.get("order_unit")
        or meta["unite_commande"]
    ).upper()
    pack_oral = bool(
        re.search(
            r"\bpacks?\b",
            normaliser_texte(str(mention.get("texte_source") or "")),
        )
    )
    libelle_famille = normaliser_texte(
        str(
            candidat.get("libelle_article")
            or candidat.get("libelle_normalise")
            or ""
        )
    )

    # Beurre/fromage en portions (250g/500g) vendu au KG
    if meta["unite_commande"] == "KG":
        for prec in mention.get("precisions_quantite", []):
            try:
                prec_qte = float(prec.get("quantite") or 0.0)
            except (TypeError, ValueError):
                prec_qte = 0.0
            if prec.get("unite") == "KG" and prec_qte in {0.125, 0.25, 0.5}:
                resolution["quantite_resolue"] = _arrondir_quantite_commande(float(quantite) * prec_qte)
                resolution["unite_resolue"] = "KG"
                resolution["score_conditionnement"] = 38.0
                resolution["raisons_resolution"].append("portions_converties_en_kg")
                return resolution

    # Bacs/boîtes de glace artisanale où la mention '2.5l' ou '5l' désigne la taille du bac
    if meta["unite_commande"] in {"BOITE", "PI", "PCE", "BAC"}:
        try:
            qte_float = float(quantite)
        except (TypeError, ValueError):
            qte_float = 0.0
        taille_l_bac = meta.get("taille_l_par_unite")
        try:
            taille_l_float = float(taille_l_bac)
        except (TypeError, ValueError):
            taille_l_float = 0.0
        est_famille_glace = bool(
            re.search(r"\b(?:glace|glacee|sorbet)\b", libelle_famille)
        )
        valeur_correspond_au_bac = bool(
            taille_l_float > 0
            and abs(qte_float - taille_l_float) <= 0.01
        )
        unite_prononcee = str(unite or "").upper()
        format_volume_explicite = unite_prononcee == "L"
        format_decimal_implicite = bool(
            not unite_prononcee
            and not qte_float.is_integer()
        )
        if (
            est_famille_glace
            and valeur_correspond_au_bac
            and (
                format_volume_explicite
                or format_decimal_implicite
            )
        ):
            resolution["quantite_resolue"] = 1.0
            resolution["unite_resolue"] = "BOITE"
            resolution["score_conditionnement"] = 38.0
            resolution["raisons_resolution"].append("contenance_bac_glace_resolue_en_unite")
            return resolution

    if (
        unite in {"CAR", "COL"}
        and unite_commande_officielle in {"CAR", "COL"}
    ):
        resolution["quantite_resolue"] = _arrondir_quantite_commande(
            float(quantite)
        )
        resolution["unite_resolue"] = unite_commande_officielle
        resolution["score_conditionnement"] = 36.0
        resolution["raisons_resolution"].append(
            "emballage_aligne_controle_references"
        )
        return resolution
    if (
        pack_oral
        and colisage_officiel > 1
        and unite_commande_officielle != "PACK"
        and unite_base_officielle == unite_commande_source
    ):
        resolution["quantite_resolue"] = _arrondir_quantite_commande(
            float(quantite) * colisage_officiel
        )
        resolution["unite_resolue"] = unite_commande_officielle
        resolution["score_conditionnement"] = 36.0
        resolution["raisons_resolution"].append(
            "pack_converti_par_controle_references"
        )
        return resolution
    if (
        unite in {"CAR", "COL"}
        and colisage_officiel > 1
        and unite_base_officielle
        and unite_base_officielle == unite_commande_source
    ):
        resolution["quantite_resolue"] = _arrondir_quantite_commande(
            float(quantite) * colisage_officiel
        )
        resolution["unite_resolue"] = unite_commande_officielle
        resolution["score_conditionnement"] = 36.0
        resolution["raisons_resolution"].append(
            "colisage_controle_references_officiel"
        )
        return resolution

    regles_article = _charger_conditionnements_articles().get(
        code_article,
        {},
    )
    regle_conditionnement = regles_article.get(str(unite or ""))
    if isinstance(regle_conditionnement, dict):
        try:
            facteur = float(regle_conditionnement.get("factor") or 0.0)
        except (TypeError, ValueError):
            facteur = 0.0
        unite_cible = str(
            regle_conditionnement.get("target_unit")
            or meta["unite_commande"]
        ).upper()
        if facteur > 0 and unite_cible:
            resolution["quantite_resolue"] = _arrondir_quantite_commande(
                float(quantite) * facteur
            )
            resolution["unite_resolue"] = unite_cible
            resolution["score_conditionnement"] = 34.0
            resolution["raisons_resolution"].append(
                "conditionnement_article_appris_agrege"
            )
            return resolution

    if unite in {"KG", "L"} and meta["unite_commande"] == unite:
        resolution["quantite_resolue"] = _arrondir_quantite_commande(float(quantite))
        resolution["score_conditionnement"] = 32.0
        resolution["raisons_resolution"].append("unite_metier_deja_alignee")
        return resolution

    if multiple is not None and meta["nb_sous_unites_colis"]:
        nb_sous_unites = float(
            meta["nb_sous_unites_colis"]
        )
        if abs(float(multiple) - nb_sous_unites) <= 0.05:
            if meta["unite_commande"] == "PCE":
                resolution["quantite_resolue"] = (
                    _arrondir_quantite_commande(
                        float(quantite) * nb_sous_unites
                    )
                )
            else:
                resolution["quantite_resolue"] = (
                    _arrondir_quantite_commande(
                        float(quantite)
                    )
                )
            resolution["score_conditionnement"] = 30.0
            resolution["raisons_resolution"].append(
                "multiple_conditionnement_detecte"
            )
            return resolution

    if unite in UNITES_EMBALLAGE:
        unite_article = meta["unite_commande"]
        if unite in {"CAR", "COL"} and unite_article in {"CAR", "COL"}:
            resolution["quantite_resolue"] = _arrondir_quantite_commande(float(quantite))
            resolution["unite_resolue"] = unite
            resolution["score_conditionnement"] = 30.0
            resolution["raisons_resolution"].append("carton_colis_equivalents")
            return resolution

        if unite == "CAR" and unite_article not in {"CAR", "COL"}:
            facteur = None
            if meta.get("nb_items_par_unite"):
                facteur = float(meta["nb_items_par_unite"])
            if facteur:
                resolution["quantite_resolue"] = _arrondir_quantite_commande(
                    float(quantite) * facteur
                )
                resolution["score_conditionnement"] = 28.0
                resolution["raisons_resolution"].append("carton_converti_en_unites_de_vente")
                return resolution
            if unite_article == "PCE":
                resolution["quantite_resolue"] = _arrondir_quantite_commande(float(quantite))
                resolution["unite_resolue"] = "COL"
                resolution["score_conditionnement"] = 25.0
                resolution["raisons_resolution"].append("carton_conserve_en_colis")
                return resolution

        if (
            unite not in {"CAR", "COL"}
            and unite_article in UNITES_EMBALLAGE
        ):
            resolution["quantite_resolue"] = _arrondir_quantite_commande(float(quantite))
            resolution["score_conditionnement"] = 30.0
            resolution["raisons_resolution"].append("emballages_exterieurs_equivalents")
            return resolution

        if unite_article == "PCE" and meta["nb_sous_unites_colis"]:
            resolution["quantite_resolue"] = _arrondir_quantite_commande(
                float(quantite) * float(meta["nb_sous_unites_colis"])
            )
            resolution["score_conditionnement"] = 24.0
            resolution["raisons_resolution"].append("carton_converti_en_pieces")
            return resolution

        resolution["quantite_resolue"] = _arrondir_quantite_commande(float(quantite))
        if unite_article == "PCE" and re.search(r"\bpot\b", str(mention.get("texte_source") or "")):
            resolution["unite_resolue"] = "BOITE"
        resolution["score_conditionnement"] = 24.0
        resolution["raisons_resolution"].append("unite_emballage_alignee")
        return resolution

    if unite == "KG":
        taille = meta["taille_kg_par_unite"]
        quantite_resolue, score = (
            _resoudre_quantite_par_taille(
                float(quantite),
                taille,
            )
        )
        if quantite_resolue is not None:
            resolution["quantite_resolue"] = (
                quantite_resolue
            )
            resolution["score_conditionnement"] = score
            resolution["raisons_resolution"].append(
                "conversion_depuis_kg"
            )
            return resolution
        # ``ratio_net_par_unite`` est une statistique historique sans
        # dimension. Elle ne prouve ni un poids ni une contenance et ne doit
        # jamais transformer, par exemple, 10 litres en 10 boites. Sans
        # dimension ecrite dans le libelle ou issue du referentiel officiel,
        # la quantite reste volontairement a arbitrer.
        resolution["raisons_resolution"].append(
            "dimension_physique_article_inconnue"
        )
        return resolution

    if unite == "L":
        taille = meta["taille_l_par_unite"]
        quantite_resolue, score = (
            _resoudre_quantite_par_taille(
                float(quantite),
                taille,
            )
        )
        if quantite_resolue is not None:
            resolution["quantite_resolue"] = (
                quantite_resolue
            )
            resolution["score_conditionnement"] = score
            resolution["raisons_resolution"].append(
                "conversion_depuis_litre"
            )
            return resolution
        resolution["raisons_resolution"].append(
            "dimension_physique_article_inconnue"
        )
        return resolution

    nb_reference_emballage = (
        meta["nb_items_par_unite"]
        or meta["nb_sous_unites_colis"]
    )

    if (
        meta["unite_commande"] in UNITES_EMBALLAGE
        and nb_reference_emballage
        and float(quantite) >= float(nb_reference_emballage)
        and (
            unite in {None, "PCE"}
            or abs(
                float(quantite) / float(nb_reference_emballage)
                - round(float(quantite) / float(nb_reference_emballage))
            ) <= 0.05
        )
    ):
        quantite_emballages = float(quantite) / float(nb_reference_emballage)
        if unite in {None, "PCE"}:
            quantite_emballages = float(math.ceil(quantite_emballages))
        resolution["quantite_resolue"] = _arrondir_quantite_commande(
            quantite_emballages
        )
        resolution["score_conditionnement"] = 23.0
        resolution["raisons_resolution"].append(
            "quantite_convertie_en_emballage"
        )
        return resolution

    resolution["quantite_resolue"] = (
        _arrondir_quantite_commande(
            float(quantite)
        )
    )
    resolution["score_conditionnement"] = (
        20.0 if unite is None else 18.0
    )
    resolution["raisons_resolution"].append(
        (
            "unite_implicite_cadencier"
            if unite is None
            else "quantite_directe"
        )
    )

    return resolution


def _bonus_preference_metier(
    mention: dict[str, Any],
    candidat: dict[str, Any],
) -> tuple[float, str | None]:
    produit = normaliser_texte(
        mention.get("produit_normalise", "")
    )
    libelle = str(
        candidat.get("libelle_normalise", "")
    )

    source_mention = normaliser_texte(str(mention.get("texte_source") or ""))
    unite_article = str(candidat.get("unite_vente") or "").upper()
    bonus_appris, raison_apprise = _bonus_regle_apprentissage(
        produit=produit,
        source_mention=source_mention,
        libelle=libelle,
        client=str(candidat.get("client_code") or ""),
    )
    if bonus_appris > 0:
        return bonus_appris, raison_apprise
    if (
        any(mot in produit for mot in ("pointes de parmesan", "parmesan en bloc"))
        and any(mot in libelle for mot in ("parmesan", "parmigiano"))
        and not any(mot in libelle for mot in ("rape", "petale", "copeau"))
    ):
        return 55.0, "preference_parmesan_bloc"
    if (
        "copeaux" in produit
        and any(mot in produit for mot in ("parmesan", "parmigiano"))
        and any(mot in libelle for mot in ("petale", "copeau"))
    ):
        return 55.0, "preference_parmesan_copeaux"
    if (
        "cocktail fruits rouges" in produit
        and "fruit rouge" in libelle
        and "melange" in libelle
        and not any(mot in libelle for mot in ("coulis", "puree"))
    ):
        return 45.0, "preference_fruits_rouges_melange"
    if (
        "ail pele" in produit
        and "ail" in libelle
        and any(mot in libelle for mot in ("epluche", "gousse"))
    ):
        return 45.0, "preference_ail_pele"
    if (
        "poulet" in produit
        and re.search(r"\bprets? a cuire\b", produit)
        and "poulet" in libelle
        and not any(mot in libelle for mot in ("filet", "aiguillette", "cuisse"))
    ):
        return 48.0, "preference_poulet_entier_pret_a_cuire"
    if (
        re.search(r"\bcreme\b", produit)
        and "20 pour cent" in produit
        and "creme" in libelle
        and re.search(r"\b20\s*%", libelle)
    ):
        return 52.0, "preference_creme_20_pour_cent"
    if (
        any(mot in produit for mot in ("fiordilatte", "fiordilaste", "fjords dilates"))
        and "mozzarella" in libelle
        and "fiordilatte" in libelle
    ):
        return 58.0, "preference_mozzarella_fiordilatte"
    if (
        "gilles d olive" in produit
        and "gidolive" in libelle
    ):
        return 60.0, "preference_huile_gidolive_phonetique"
    if (
        "caramelle" in produit
        and "caramel" in libelle
        and any(mot in libelle for mot in ("creme glacee", "glace"))
    ):
        return 52.0, "preference_glace_caramel_phonetique"
    if (
        "manchoco" in produit
        and "menthe" in libelle
        and "chocolat" in libelle
    ):
        return 58.0, "preference_menthe_chocolat_phonetique"
    if (
        "semoule moyenne" in produit
        and (
            "couscous grain moyen" in libelle
            or "semoule de ble moyen" in libelle
        )
    ):
        return 70.0, "preference_semoule_moyenne_couscous"
    if (
        re.search(r"\bcerises? noires?\b", produit)
        and "cerise noire" in libelle
        and any(mot in libelle for mot in ("puree", "pulpe"))
    ):
        return 68.0, "preference_puree_cerise_noire"
    if (
        "thym" in produit
        and "thym" in libelle
    ):
        return 65.0, "preference_thym_explicite"
    if (
        "chicken wings" in produit
        and any(mot in libelle for mot in ("wings", "aileron"))
        and any(mot in libelle for mot in ("tex mex", "mexic"))
    ):
        return 62.0, "preference_wings_tex_mex"
    if (
        "artichaut" in produit
        and any(mot in produit for mot in ("bonduelle", "bon duel"))
        and "artichaut" in libelle
        and "bonduelle" in libelle
    ):
        return 62.0, "preference_artichaut_bonduelle"
    if (
        "madere cuisine" in produit
        and "madere" in libelle
    ):
        return 62.0, "preference_madere_cuisine"
    if (
        "filet de poulet sous vide" in produit
        and "filet de poulet" in libelle
        and "s v" in libelle
        and "roti" not in libelle
    ):
        return 58.0, "preference_filet_poulet_cru_sous_vide"
    if (
        "mozzarella" in produit
        and any(mot in produit for mot in ("pas la rapee", "morceaux"))
        and "mozzarella" in libelle
        and "cossette" in libelle
    ):
        return 62.0, "preference_mozzarella_cossette_non_rapee"
    if (
        "piquill" in produit
        and re.search(r"\b3[\s/]1\b", source_mention)
        and "piquill" in libelle
        and re.search(r"\b3[\s/]1\b", libelle)
    ):
        return 60.0, "preference_piquillos_3_1"
    if (
        re.search(r"\bolives? noires?\b", produit)
        and (
            re.search(r"\b4[\s/]4\b", source_mention)
            or "4 quarts" in source_mention
        )
        and re.search(r"\bolives? noires?\b", libelle)
        and re.search(r"\b4[\s/]4\b", libelle)
    ):
        return 60.0, "preference_olive_noire_4_4"
    if (
        "jambon blanc italien" in produit
        and "prosciutto cotto" in libelle
    ):
        return 62.0, "preference_prosciutto_cotto_italien"
    if (
        any(mot in produit for mot in ("gruyere rapee", "emmental rape"))
        and "emmental" in libelle
        and "rape" in libelle
    ):
        return 55.0, "preference_emmental_rape"
    if (
        "cacao poudre" in produit
        and "cacao" in libelle
        and any(mot in libelle for mot in ("poudre", "extra brut"))
    ):
        return 52.0, "preference_cacao_poudre"
    if (
        "jambon serrano" in produit
        and "reserva" in produit
        and "jambon serrano" in libelle
        and "reserva" in libelle
    ):
        return 58.0, "preference_jambon_serrano_reserva"
    if (
        "pitadessia" in produit
        and "philadelphia" in libelle
    ):
        return 65.0, "preference_philadelphia_phonetique"
    if (
        "tortilla" in produit
        and "preparation tortilla" in libelle
        and unite_article == "POC"
    ):
        return 60.0, "preference_tortilla_en_poche"
    if (
        "jambon blanc" in produit
        and (
            "jambon cuit" in libelle
            or "prosciutto cotto" in libelle
            or "au torchon" in libelle
        )
    ):
        return 28.0, "preference_jambon_blanc_cuit"
    if (
        re.search(r"\boeufs?\b", produit)
        and not any(
            mot in produit
            for mot in ("dur", "ecale", "liquide", "blanc", "jaune")
        )
        and re.search(r"\boeufs?\b", libelle)
        and not any(
            mot in libelle
            for mot in ("dur", "ecale", "liquide", "blanc", "jaune")
        )
    ):
        bonus_oeuf = 26.0
        try:
            quantite_oeufs = float(mention.get("quantite_principale") or 0.0)
        except (TypeError, ValueError):
            quantite_oeufs = 0.0
        colisage = re.search(r"\bx\s*(?P<nombre>\d{2,4})\s*p\b", libelle)
        if colisage and quantite_oeufs > 0:
            nombre = float(colisage.group("nombre"))
            ecart_relatif = abs(nombre - quantite_oeufs) / max(quantite_oeufs, 1.0)
            bonus_oeuf += max(0.0, 28.0 - 8.0 * ecart_relatif)
        return round(bonus_oeuf, 2), "preference_oeuf_coquille_par_defaut"
    if (
        "jaune d oeuf" in produit
        and "jaune" in libelle
        and "oeuf" in libelle
    ):
        return 30.0, "preference_jaune_oeuf_explicite"
    if (
        "ketchup" in produit
        and "ketchup" in libelle
        and "dosette" not in libelle
    ):
        return 38.0, "preference_ketchup_hors_dosette"
    if (
        "mutti polpa" in produit
        and "pulpe" in libelle
        and "mutti" in libelle
    ):
        return 30.0, "preference_mutti_polpa"
    if (
        any(mot in produit for mot in ("mozzadille", "mozza bille"))
        and "mozzarella" in libelle
        and "bille" in libelle
    ):
        return 26.0, "preference_mozzarella_billes"
    if (
        "bobine" in produit
        and any(mot in produit for mot in ("sopalin", "essuie", "devidoir"))
        and "bobine" in libelle
        and "essuie mains" in libelle
    ):
        return 60.0, "preference_bobine_essuie_mains"
    if (
        re.search(r"\b1\s*(?:l|litre)\b", source_mention)
        and re.search(r"\b1\s*l\b", libelle)
    ):
        return 38.0, "preference_volume_unitaire_1l_explicite"
    if mention.get("unite_principale") == "CAR" and unite_article in {"CAR", "COL"}:
        return 22.0, "preference_carton_colis_explicite"
    if re.search(r"\bpoches?\b", source_mention) and unite_article == "POC":
        return 18.0, "preference_poche_explicite"
    if (
        re.search(r"\bbloc\b", source_mention)
        and unite_article in {"PI", "PCE"}
        and not any(mot in libelle for mot in ("cube", "tranche"))
    ):
        return 14.0, "preference_bloc_entier"

    if produit == "beurre" and "beurre doux" in libelle:
        return 4.0, "preference_beurre_doux"

    dimension = re.search(
        r"\b(?P<taille>\d{1,3})\s*cm\b",
        produit,
    )
    if dimension:
        taille = dimension.group("taille")
        libelle_compact = re.sub(r"\s+", "", libelle)
        if f"{taille}cm" in libelle_compact:
            return 12.0, f"preference_dimension_{taille}cm"

    libelle_brut = enlever_accents(
        str(candidat.get("libelle_article") or "")
    ).lower().replace(",", ".")
    dimensions_libelle = [
        int(match.group("taille"))
        for match in re.finditer(r"(?P<taille>\d{1,3})\s*cm\b", libelle_brut)
    ]
    if dimensions_libelle and re.search(r"\bpetit(?:e)?\b", produit):
        taille = min(dimensions_libelle)
        return max(2.0, 24.0 - taille / 2.0), "preference_petit_format"
    if dimensions_libelle and re.search(r"\bgrand(?:e)?\b", produit):
        taille = max(dimensions_libelle)
        return min(10.0, taille / 10.0), "preference_grand_format"

    volumes_litres = [
        float(match.group("taille"))
        for match in re.finditer(
            r"(?P<taille>\d+(?:\.\d+)?)\s*(?:l|litres?)\b",
            libelle_brut,
        )
    ]
    if "grand format" in produit and any(volume >= 4.0 for volume in volumes_litres):
        return 18.0, "preference_grand_format_volume"
    if "petit format" in produit and any(volume < 4.0 for volume in volumes_litres):
        return 18.0, "preference_petit_format_volume"

    unite_principale = str(mention.get("unite_principale") or "").upper()
    try:
        quantite_principale = float(mention.get("quantite_principale"))
    except (TypeError, ValueError):
        quantite_principale = 0.0
    if unite_principale == "L" and quantite_principale > 0 and any(
        abs(quantite_principale - volume) <= max(0.15, quantite_principale * 0.15)
        for volume in volumes_litres
    ):
        return 32.0, "preference_volume_unitaire_proche"

    precisions = list(mention.get("precisions_quantite", []) or [])
    for precision in precisions:
        unite_precision = str(precision.get("unite") or "").upper()
        try:
            quantite_precision = float(precision.get("quantite"))
        except (TypeError, ValueError):
            continue
        if quantite_precision <= 0:
            continue
        if unite_precision == "KG":
            grammes = int(round(quantite_precision * 1000))
            correspond = any(
                abs(quantite_precision - valeur) <= 0.02
                for valeur in [
                    float(match.group("taille"))
                    for match in re.finditer(
                        r"(?P<taille>\d+(?:\.\d+)?)\s*(?:kg|k)\b",
                        libelle_brut,
                    )
                ]
            ) or bool(re.search(rf"(?<!\d){grammes}\s*g\b", libelle_brut))
            if correspond:
                return 14.0, f"preference_conditionnement_{grammes}g"
        elif unite_precision == "L":
            if any(abs(quantite_precision - valeur) <= 0.02 for valeur in volumes_litres):
                return 14.0, f"preference_conditionnement_{quantite_precision:g}l"

    if (
        "oeuf" in produit
        and "liquide" in produit
        and not any(mot in produit for mot in ("blanc", "jaune", "entier"))
        and "entier oeuf liquide" in libelle
    ):
        return 15.0, "preference_oeuf_entier_par_defaut"

    return 0.0, None


def extraire_mentions_produits(
    transcription: str,
) -> list[dict[str, Any]]:
    transcription_normalisee = (
        normaliser_transcription_produits(transcription)
    )
    recapitulatif = re.search(
        (
            r"\b(?:donc\s+)?je\s+(?:vous\s+)?repete\s+"
            r"(?:la\s+)?commande\b"
        ),
        transcription_normalisee,
    )
    if recapitulatif:
        avant_recapitulatif = transcription_normalisee[
            : recapitulatif.start()
        ].strip()
        quantites_avant = re.findall(
            (
                r"\b(?:\d+(?:\.\d+)?|un|une|deux|trois|"
                r"quatre|cinq|six|sept|huit|neuf|dix|"
                r"onze|douze|treize|quatorze|quinze|"
                r"seize|vingt|trente|quarante|cinquante)\b"
            ),
            avant_recapitulatif,
        )
        if len(quantites_avant) >= 2:
            transcription = avant_recapitulatif
    clauses = decouper_clauses_produits(
        transcription,
        preserver_modalites=True,
    )

    mentions: list[dict[str, Any]] = []

    motif_principal = re.compile(
        (
            r"^(?P<quantite>\d+(?:\.\d+)?)"
            r"\s*"
            rf"(?:(?P<unite>{UNITES_REGEX})\b)?"
            r"\s*"
            r"(?:(?:de|d)\b)?\s*"
            r"(?P<produit>.*)$"
        )
    )

    motif_complement_seul = re.compile(
        (
            r"^(?P<quantite>\d+(?:\.\d+)?)"
            r"\s*"
            rf"(?P<unite>{UNITES_REGEX})\b\s*$"
        )
    )

    motif_multiple = re.compile(
        (
            r"^(?P<quantite>\d+(?:\.\d+)?)"
            r"\s*x\s*"
            r"(?P<multiple>\d+(?:\.\d+)?)"
            r"\s*"
            rf"(?:(?P<unite>{UNITES_REGEX})\b)?"
            r"\s*(?:(?:de|d)\b)?\s*"
            r"(?P<produit>.*)$"
        )
    )

    motif_quantite_fin = re.compile(
        (
            r"^(?P<produit>.*?)"
            r"\s+"
            r"(?P<quantite>\d+(?:\.\d+)?)"
            r"\s*"
            rf"(?P<unite>{UNITES_REGEX})\b\s*$"
        )
    )

    for index_clause, clause in enumerate(clauses):
        clause_norm = _normaliser_clause_parse(
            clause
        )
        modalite_clause = "CERTAINE"
        if clause_norm.startswith("modaliteconditionnelle "):
            modalite_clause = "CONDITIONNELLE"
            clause_norm = clause_norm[len("modaliteconditionnelle ") :].strip()
            clause = re.sub(
                r"^modaliteconditionnelle\s+",
                "",
                clause,
            ).strip()
        clause_norm = _couper_avant_quantite_commande(
            clause_norm
        )

        if not clause_norm:
            continue

        quantite_apres_produit = re.match(
            r"^(?P<produit>.+?)\s+(?:je|j|on|nous)\s+(?:en\s+)?"
            r"(?:veux|voudrais|prends?|prendrais)\s+(?:bien\s+)?"
            r"(?P<quantite>\d+(?:\.\d+)?)\s*"
            rf"(?P<unite>{UNITES_REGEX})?\s*$",
            clause_norm,
        )
        if quantite_apres_produit:
            unite_apres = quantite_apres_produit.group("unite") or ""
            clause_norm = (
                f"{quantite_apres_produit.group('quantite')} "
                f"{unite_apres} {quantite_apres_produit.group('produit')}"
            ).strip()

        if _est_entete_enumeration_sans_article(
            clause_norm,
            clauses[index_clause + 1 :],
        ):
            continue

        if _rattacher_precision_produit_precedent(
            clause_norm=clause_norm,
            mentions=mentions,
        ):
            continue

        if _clause_hors_produit(clause_norm):
            continue

        if clause_norm in {
            "en fait non",
            "non en fait",
            "finalement non",
        }:
            if mentions:
                mentions.pop()
            continue

        for prefixe_annulation in (
            "en fait non ",
            "non en fait ",
            "finalement non ",
        ):
            if clause_norm.startswith(prefixe_annulation):
                if mentions:
                    mentions.pop()
                clause_norm = clause_norm[
                    len(prefixe_annulation) :
                ].strip()
                if not clause_norm:
                    continue
                break

        match_quantite_reference = re.match(
            r"^(?:(?:il\s+)?(?:m\s+|nous\s+)?en\s+faudrait|"
            r"(?:je|j|on|nous)\s+(?:en\s+)?(?:veux|voudrais|prends?|"
            r"prendrais)(?:\s+bien)?|environ|a\s+peu\s+pres)\s+"
            r"(?P<quantite>\d+(?:\.\d+)?)"
            r"(?:\s*(?P<unite>"
            + UNITES_REGEX
            + r")\b)?$",
            clause_norm,
        )

        if match_quantite_reference and mentions:
            quantite = float(
                match_quantite_reference.group("quantite")
            )
            unite = _normaliser_unite(
                match_quantite_reference.group("unite")
            )
            quantite, unite, precisions_conv = (
                _adapter_quantite_unite(
                    quantite,
                    unite,
                )
            )
            precedente = mentions[-1]

            if precedente.get("quantite") is None:
                precedente["quantite_principale"] = quantite
                precedente["quantite"] = quantite
                precedente["unite_principale"] = unite
                precedente["unite_detectee"] = unite
            else:
                precedente["precisions_quantite"].append(
                    {
                        "quantite": quantite,
                        "unite": unite,
                        "texte_source": clause,
                        "origine": "quantite_reference_precedente",
                        "precisions": precisions_conv,
                    }
                )
                precedente["ambigu"] = True
                precedente["raisons_ambiguite"].append(
                    "quantite_reference_precedente"
                )
            continue

        match_multiple = motif_multiple.match(
            clause_norm
        )

        if match_multiple:
            quantite = float(
                match_multiple.group("quantite")
            )
            multiple = float(
                match_multiple.group("multiple")
            )
            produit = (
                match_multiple.group("produit") or ""
            ).strip()
            produit = _normaliser_produit_extrait(produit)

            if produit:
                mentions.append(
                    {
                        "texte_source": clause,
                        "texte_normalise": clause_norm,
                        "produit_normalise": produit,
                        "texte_produit": produit,
                        "quantite_principale": quantite,
                        "quantite": quantite,
                        "unite_principale": None,
                        "unite_detectee": None,
                        "precisions_quantite": [],
                        "ambigu": False,
                        "raisons_ambiguite": [
                            "conditionnement_multiple"
                        ],
                        "conditionnement_multiple": multiple,
                        "modalite_demande": modalite_clause,
                        "demande_conditionnelle": (
                            modalite_clause == "CONDITIONNELLE"
                        ),
                    }
                )
                continue

        match_complement = motif_complement_seul.match(
            clause_norm
        )

        if match_complement and mentions:
            quantite = float(
                match_complement.group("quantite")
            )
            unite = _normaliser_unite(
                match_complement.group("unite")
            )
            quantite, unite, precisions_conv = (
                _adapter_quantite_unite(
                    quantite,
                    unite,
                )
            )

            details = {
                "quantite": quantite,
                "unite": unite,
                "texte_source": clause,
                "origine": "complement_seul",
            }

            if precisions_conv:
                details["precisions"] = precisions_conv

            precedente = mentions[-1]
            unite_precedente = precedente.get(
                "unite_principale"
            )
            quantite_precedente_brute = precedente.get(
                "quantite_principale",
                0.0,
            )
            quantite_precedente = float(
                quantite_precedente_brute
                if quantite_precedente_brute
                is not None
                else 0.0
            )

            if precedente.get("quantite") is None:
                precedente["quantite_principale"] = quantite
                precedente["quantite"] = quantite
                precedente["unite_principale"] = unite
                precedente["unite_detectee"] = unite
                precedente["ambigu"] = False
                precedente["raisons_ambiguite"] = []
            elif (
                unite in {"L", "KG"}
                and unite_precedente in {None, "PCE"}
                and quantite > quantite_precedente
            ):
                precedente["precisions_quantite"].append(
                    {
                        "quantite": quantite_precedente,
                        "unite": unite_precedente,
                        "texte_source": precedente.get(
                            "texte_source", ""
                        ),
                        "origine": "quantite_initiale",
                    }
                )
                precedente["quantite_principale"] = quantite
                precedente["quantite"] = quantite
                precedente["unite_principale"] = unite
                precedente["unite_detectee"] = unite
                precedente["raisons_ambiguite"].append(
                    "quantite_principale_ajustee_par_complement"
                )
            else:
                precedente["precisions_quantite"].append(
                    details
                )
                precedente["ambigu"] = True
                precedente["raisons_ambiguite"].append(
                    "complement_quantite_ajoute"
                )
            continue

        correspondance = motif_principal.match(
            clause_norm
        )

        if not correspondance:
            if _clause_ressemble_a_produit(
                clause_norm
            ):
                if (
                    not mentions
                    and len(clause_norm.split()) > 10
                ):
                    continue

                produit_sans_quantite = (
                    _normaliser_produit_extrait(
                        clause_norm
                    )
                )
                mentions.append(
                    {
                        "texte_source": clause,
                        "texte_normalise": clause_norm,
                        "produit_normalise": produit_sans_quantite,
                        "texte_produit": produit_sans_quantite,
                        "quantite_principale": None,
                        "quantite": None,
                        "unite_principale": None,
                        "unite_detectee": None,
                        "precisions_quantite": [],
                        "ambigu": False,
                        "raisons_ambiguite": [
                            "quantite_absente_a_resoudre"
                        ],
                        "conditionnement_multiple": None,
                        "modalite_demande": modalite_clause,
                        "demande_conditionnelle": (
                            modalite_clause == "CONDITIONNELLE"
                        ),
                    }
                )
            continue

        quantite = float(
            correspondance.group("quantite")
        )
        unite = _normaliser_unite(
            correspondance.group("unite")
        )

        produit = (
            correspondance.group("produit") or ""
        ).strip()

        precisions_quantite: list[dict[str, Any]] = []
        ambigu = False
        raisons_ambiguite: list[str] = []

        quantite, unite, precision_conversion = (
            _adapter_quantite_unite(
                quantite,
                unite,
            )
        )

        if precision_conversion:
            precisions_quantite.extend(
                precision_conversion
            )

        quantite_fin = motif_quantite_fin.match(
            produit
        )

        if quantite_fin:
            produit = quantite_fin.group("produit").strip()
            quantite_precision = float(
                quantite_fin.group("quantite")
            )
            unite_precision = _normaliser_unite(
                quantite_fin.group("unite")
            )
            (
                quantite_precision,
                unite_precision,
                precision_conversion_fin,
            ) = _adapter_quantite_unite(
                quantite_precision,
                unite_precision,
            )
            precisions_quantite.append(
                {
                    "quantite": quantite_precision,
                    "unite": unite_precision,
                    "texte_source": quantite_fin.group(0),
                    "origine": "quantite_fin_de_mention",
                    "precisions": precision_conversion_fin,
                }
            )

        produit = _normaliser_produit_extrait(produit)

        if produit and not _clause_ressemble_a_produit(
            produit
        ):
            continue

        if not produit:
            if mentions:
                precedente = mentions[-1]
                if precedente.get("quantite_principale") is None:
                    precedente["quantite_principale"] = quantite
                    precedente["quantite"] = quantite
                    precedente["unite_principale"] = unite
                    precedente["unite_detectee"] = unite
                    precedente["raisons_ambiguite"] = [
                        raison
                        for raison in precedente.get("raisons_ambiguite", [])
                        if raison != "quantite_absente_a_resoudre"
                    ]
                    precedente["ambigu"] = bool(
                        precedente["raisons_ambiguite"]
                    )
                else:
                    precedente["precisions_quantite"].append(
                        {
                            "quantite": quantite,
                            "unite": unite,
                            "texte_source": clause,
                            "origine": "clause_sans_produit",
                        }
                    )
                    precedente["ambigu"] = True
                    precedente["raisons_ambiguite"].append(
                        "quantite_sans_produit_rattachee"
                    )
            continue

        if unite is None:
            if not quantite.is_integer():
                ambigu = True
                raisons_ambiguite.append("unite_absente")
            else:
                raisons_ambiguite.append(
                    "unite_absente_a_resoudre"
                )

        if quantite <= 0:
            ambigu = True
            raisons_ambiguite.append("quantite_invalide")

        mentions.append(
            {
                "texte_source": clause,
                "texte_normalise": clause_norm,
                "produit_normalise": produit,
                "texte_produit": produit,
                "quantite_principale": quantite,
                "quantite": quantite,
                "unite_principale": unite,
                "unite_detectee": unite,
                "precisions_quantite": precisions_quantite,
                "ambigu": ambigu,
                "raisons_ambiguite": raisons_ambiguite,
                "conditionnement_multiple": None,
                "modalite_demande": modalite_clause,
                "demande_conditionnelle": (
                    modalite_clause == "CONDITIONNELLE"
                ),
            }
        )

    mentions = _fusionner_alternatives_mentions(mentions)
    mentions = _annoter_modalites_demande(transcription, mentions)
    mentions = _appliquer_contexte_glace(transcription, mentions)
    mentions = _dedupliquer_repetitions_mentions(mentions)
    # Une longue hallucination Whisper peut laisser deux blocs identiques
    # apres une premiere reduction. Une seconde passe rend l'operation stable.
    mentions = _dedupliquer_repetitions_mentions(mentions)
    mentions = _dedupliquer_repetitions_differees(mentions)
    return _fusionner_mentions_dupliquees_proches(mentions)


def _appliquer_contexte_glace(
    transcription: str,
    mentions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    texte_global = _normaliser_oraux_decimaux(
        remplacer_nombres_en_chiffres(
            normaliser_transcription_produits(transcription)
        )
    )
    if not re.search(r"\b(?:glace|glaces|sorbet|sorbets|glacant)\b", texte_global):
        return mentions

    saveurs = {
        "vanille",
        "chocolat",
        "yaourt",
        "framboise",
        "citron",
        "caramel",
        "fraise",
        "fraises",
        "mangue",
        "mangues",
        "pistache",
        "pistaches",
        "cafe",
        "cafes",
        "coco",
        "noisette",
        "passion",
        "kinder",
        "fleur",
        "fleurs",
        "orange",
        "oranger",
    }
    normaliser_saveurs_flechies = business_rule_enabled(
        "normalisation_saveurs_flechies"
    )

    def saveurs_contextuelles(produit: str) -> set[str]:
        """Retourne les saveurs reconnaissables par flexion simple.

        Cette normalisation est volontairement lexicale : elle ne fait ni
        fuzzy global ni correction phonétique. Elle couvre seulement les
        pluriels/accords usuels d'une saveur déjà connue, par exemple
        ``carameles`` -> ``caramel``, et reste ensuite bornée à une vraie
        énumération de glaces.
        """
        if not normaliser_saveurs_flechies:
            return set(_tokens_produit(produit)) & saveurs

        resultat_saveurs: set[str] = set()
        for token in _tokens_produit(produit):
            formes = {token}
            if token.endswith("s"):
                formes.add(token[:-1])
            if token.endswith("es"):
                formes.add(token[:-2])
            if token.endswith("ee"):
                formes.add(token[:-2])
            if token.endswith("ees"):
                formes.add(token[:-3])
            resultat_saveurs.update(formes & saveurs)
        return resultat_saveurs

    def canoniser_saveurs_contextuelles(produit: str) -> str:
        # Conserver le pluriel prononce quand il est deja exploitable
        # (``fraises``). Seules les flexions qui masquent la racine connue
        # sont canonisees (``carameles`` -> ``caramel``).
        if not normaliser_saveurs_flechies:
            return normaliser_texte(produit)

        tokens = normaliser_texte(produit).split()
        resultat_tokens: list[str] = []
        for token in tokens:
            formes = [token]
            if token.endswith("es"):
                formes.append(token[:-2])
            if token.endswith("ee"):
                formes.append(token[:-2])
            if token.endswith("ees"):
                formes.append(token[:-3])
            resultat_tokens.append(
                next((forme for forme in formes if forme in saveurs), token)
            )
        return " ".join(resultat_tokens)
    multiples_glaces: dict[str, tuple[float, float, str]] = {}
    motif_multiple_glace = re.compile(
        r"\b(?P<nombre>\d+(?:\.\d+)?)\s+(?:fois|x)\s+"
        r"(?P<taille>\d+(?:\.\d+)?)\s*(?:l|litres?)?\s+"
        r"(?P<saveur>[a-z][a-z\s]{0,35}?)"
        r"(?=\s+(?:et\s+)?\d+(?:\.\d+)?\s+(?:fois|x)|[,.;]|$)"
    )
    for correspondance in motif_multiple_glace.finditer(texte_global):
        saveur_entendue = normaliser_texte(correspondance.group("saveur"))
        saveur = {
            "patient": "passion",
            "patients": "passion",
        }.get(saveur_entendue, saveur_entendue)
        multiples_glaces[saveur_entendue] = (
            float(correspondance.group("nombre")),
            float(correspondance.group("taille")),
            saveur,
        )
    motifs_formats = (
        re.compile(
            r"\b(?P<saveur>[a-z]+)\s+(?P<format>grand|petit)\s+"
            r"format\s+(?P<quantite>\d+(?:\.\d+)?)\b"
        ),
        re.compile(
            r"\b(?P<format>grand|petit)\s+format\s+"
            r"(?P<quantite>\d+(?:\.\d+)?)\s+(?P<saveur>[a-z]+)\b"
        ),
    )

    formats_presents: set[tuple[str, str, float]] = set()
    for mention in mentions:
        produit_existant = normaliser_texte(
            mention.get("produit_normalise", "")
        )
        for motif in motifs_formats:
            correspondance = motif.fullmatch(produit_existant)
            if correspondance and correspondance.group("saveur") in saveurs:
                formats_presents.add(
                    (
                        correspondance.group("saveur"),
                        correspondance.group("format"),
                        float(correspondance.group("quantite")),
                    )
                )
                break

    # Le parseur principal exige normalement une quantite en debut de clause.
    # Dans une liste de glaces, le client place souvent la quantite apres le
    # format ("vanille grand format quatre"). On recupere uniquement ces
    # motifs tres contraints quand le contexte glace est explicite.
    for motif in motifs_formats:
        for correspondance in motif.finditer(texte_global):
            saveur = correspondance.group("saveur")
            if saveur not in saveurs:
                continue
            format_glace = correspondance.group("format")
            quantite = float(correspondance.group("quantite"))
            cle = (saveur, format_glace, quantite)
            if cle in formats_presents:
                continue
            produit = f"{saveur} {format_glace} format {quantite:g}"
            mentions.append(
                {
                    "texte_source": correspondance.group(0),
                    "texte_normalise": correspondance.group(0),
                    "produit_normalise": produit,
                    "texte_produit": produit,
                    "quantite_principale": None,
                    "quantite": None,
                    "unite_principale": None,
                    "unite_detectee": None,
                    "precisions_quantite": [],
                    "ambigu": True,
                    "raisons_ambiguite": ["quantite_absente"],
                    "conditionnement_multiple": None,
                }
            )
            formats_presents.add(cle)

    resultat: list[dict[str, Any]] = []
    contexte_ambigu_seulement = business_rule_enabled(
        "contexte_enumeration_ambigu"
    )
    noyaux_explicites_non_glace = {
        "boisson", "coulis", "confiture", "creme", "huile", "jus",
        "pate", "poivron", "poivrons", "puree", "sauce", "sirop",
        "vinaigre",
    }

    def noyau_explicite_avant_saveur(produit: str) -> bool:
        """Détecte un nom de produit exprimé avant une saveur.

        Une famille implicite ``glaces`` ne peut compléter qu'une saveur
        isolée. Ainsi ``muffin au chocolat`` garde ``muffin`` comme noyau,
        tout comme ``sauce caramel`` ou ``poivrons caramélisés``. Cette
        détection repose sur la structure de la mention, pas sur des codes
        article ou des exceptions de produits.
        """
        tokens = _tokens_produit(produit)
        positions_saveurs = [
            index for index, token in enumerate(tokens)
            if token in saveurs_contextuelles(produit)
        ]
        if not positions_saveurs:
            return False
        premier_saveur = min(positions_saveurs)
        mots_liaison = {
            "a", "au", "aux", "avec", "d", "de", "des", "du", "en",
            "et", "la", "le", "les", "l", "pour", "sans", "sur",
        }
        return any(
            token not in mots_liaison and token not in saveurs
            for token in tokens[:premier_saveur]
        )

    def est_saveur_isolee_ambigue(produit: str) -> bool:
        tokens = set(_tokens_produit(produit))
        return bool(
            saveurs_contextuelles(produit)
            and not (tokens & noyaux_explicites_non_glace)
            and not noyau_explicite_avant_saveur(produit)
        )
    nb_mentions_saveur_ambiguës = sum(
        1
        for mention in mentions
        if est_saveur_isolee_ambigue(
            normaliser_texte(mention.get("produit_normalise", ""))
        )
    )
    enumeration_glace_etablie = nb_mentions_saveur_ambiguës >= 2
    for original in mentions:
        mention = dict(original)
        produit = normaliser_texte(mention.get("produit_normalise", ""))
        tokens_produit = set(_tokens_produit(produit))
        multiple_glace = multiples_glaces.get(produit)
        if multiple_glace:
            nombre, taille, saveur = multiple_glace
            produit = f"glace {saveur} {taille:g}l"
            mention["quantite_principale"] = nombre
            mention["quantite"] = nombre
            mention["unite_principale"] = None
            mention["unite_detectee"] = None
            mention["conditionnement_multiple"] = taille
            mention["precisions_quantite"] = [
                {
                    "quantite": taille,
                    "unite": "L",
                    "texte_source": mention.get("texte_source", ""),
                    "origine": "taille_unitaire_multiple_glace",
                    "nombre_unites": nombre,
                }
            ]
            mention["produit_normalise"] = produit
            mention["texte_produit"] = produit
            raisons = [
                raison
                for raison in (mention.get("raisons_ambiguite") or [])
                if raison
                not in {
                    "unite_absente",
                    "unite_absente_a_resoudre",
                    "conditionnement_multiple",
                }
            ]
            mention["raisons_ambiguite"] = raisons
            mention["ambigu"] = bool(raisons)
            resultat.append(mention)
            continue
        format_fin = re.fullmatch(
            r"(?P<saveur>[a-z]+)\s+(?P<format>grand|petit)\s+format\s+(?P<quantite>\d+(?:\.\d+)?)",
            produit,
        )
        format_debut = re.fullmatch(
            r"(?P<format>grand|petit)\s+format\s+(?P<quantite>\d+(?:\.\d+)?)\s+(?P<saveur>[a-z]+)",
            produit,
        )
        format_match = format_fin or format_debut
        if format_match and format_match.group("saveur") in saveurs:
            quantite = float(format_match.group("quantite"))
            produit = (
                f"glace {format_match.group('saveur')} "
                f"{format_match.group('format')} format"
            )
            mention["quantite_principale"] = quantite
            mention["quantite"] = quantite
            mention["unite_principale"] = None
            mention["unite_detectee"] = None
            mention["produit_normalise"] = produit
            mention["texte_produit"] = produit
            raisons = [
                raison
                for raison in (mention.get("raisons_ambiguite") or [])
                if raison != "quantite_absente"
            ]
            mention["raisons_ambiguite"] = raisons
            mention["ambigu"] = bool(raisons)
        elif (
            saveurs_contextuelles(produit)
            and not (tokens_produit & noyaux_explicites_non_glace)
            and not noyau_explicite_avant_saveur(produit)
            and not re.search(
                r"\b(?:surgele|congele|frais|fraiche|liquide|jus|puree|coulis|confiture|sirop)\b",
                produit,
            )
            and "glace" not in produit
            and "sorbet" not in produit
            and (
                not contexte_ambigu_seulement
                or enumeration_glace_etablie
            )
        ):
            produit = f"glace {canoniser_saveurs_contextuelles(produit)}"
            mention["produit_normalise"] = produit
            mention["texte_produit"] = produit
            if contexte_ambigu_seulement:
                mention.setdefault("raisons_ambiguite", []).append(
                    "famille_glace_heritee_contexte_enumeration_ambigu"
                )
        resultat.append(mention)
    return resultat


def _cle_repetition_mention(mention: dict[str, Any]) -> tuple[str, str, str]:
    quantite = mention.get("quantite_principale")
    try:
        quantite_cle = f"{float(quantite):.4f}"
    except (TypeError, ValueError):
        quantite_cle = ""
    return (
        normaliser_texte(mention.get("produit_normalise", "")),
        quantite_cle,
        str(mention.get("unite_principale") or ""),
    )


def _dedupliquer_repetitions_mentions(
    mentions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Retire seulement les blocs adjacents strictement repetes par Whisper."""
    if len(mentions) < 2:
        return mentions

    resultat: list[dict[str, Any]] = []
    index = 0
    cles = [_cle_repetition_mention(item) for item in mentions]
    while index < len(mentions):
        taille_max = min(8, (len(mentions) - index) // 2)
        taille_repetee = 0
        for taille in range(taille_max, 0, -1):
            bloc = cles[index : index + taille]
            suivant = cles[index + taille : index + 2 * taille]
            if bloc == suivant:
                taille_repetee = taille
                break

        if not taille_repetee:
            resultat.append(mentions[index])
            index += 1
            continue

        bloc_mentions = [dict(item) for item in mentions[index : index + taille_repetee]]
        for mention in bloc_mentions:
            mention["ambigu"] = True
            raisons = list(mention.get("raisons_ambiguite") or [])
            raisons.append("repetition_transcription_supprimee")
            mention["raisons_ambiguite"] = sorted(set(raisons))
        resultat.extend(bloc_mentions)

        bloc_cles = cles[index : index + taille_repetee]
        index += 2 * taille_repetee
        while cles[index : index + taille_repetee] == bloc_cles:
            index += taille_repetee

    return resultat


def _dedupliquer_repetitions_differees(
    mentions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Nettoie la fin d'une tempete de repetitions deja attestee."""
    if not any(
        "repetition_transcription_supprimee" in (item.get("raisons_ambiguite") or [])
        for item in mentions
    ):
        return mentions

    produits = [
        normaliser_texte(item.get("produit_normalise", ""))
        for item in mentions
    ]
    repetes = {
        produit for produit in set(produits) if produit and produits.count(produit) >= 2
    }
    if len(repetes) < 2:
        return mentions

    vus: set[str] = set()
    resultat: list[dict[str, Any]] = []
    for item, produit in zip(mentions, produits):
        if produit in repetes and produit in vus:
            continue
        resultat.append(item)
        vus.add(produit)
    return resultat


def _fusionner_mentions_dupliquees_proches(
    mentions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fusionne une reformulation proche quand elle precise la meme ligne."""
    discriminants = {
        "blanc", "jaune", "entier", "liquide", "dur", "ecale",
        "rape", "rapee", "copeau", "copeaux", "bloc", "tranche",
        "tranches", "laniere", "lanieres", "rondelle", "rondelles",
    }
    groupes_exclusifs = (
        {"blanc", "jaune", "entier"},
        {"rape", "rapee", "copeau", "copeaux", "bloc", "tranche", "tranches"},
    )
    liaisons = {"d", "de", "des", "du", "l", "la", "le", "les"}

    def meme_noyau_avec_precision(a: str, b: str) -> bool:
        tokens_a = set(a.split())
        tokens_b = set(b.split())
        noyau_a = tokens_a - discriminants - liaisons
        noyau_b = tokens_b - discriminants - liaisons
        if not noyau_a or noyau_a != noyau_b:
            return False
        attributs_a = tokens_a & discriminants
        attributs_b = tokens_b & discriminants
        return not any(
            (attributs_a & groupe)
            and (attributs_b & groupe)
            and not ((attributs_a & groupe) & (attributs_b & groupe))
            for groupe in groupes_exclusifs
        )

    resultat: list[dict[str, Any]] = []
    for original in mentions:
        mention = dict(original)
        produit = normaliser_texte(mention.get("produit_normalise", ""))
        quantite = mention.get("quantite_principale")
        position: int | None = None

        for index in range(len(resultat) - 1, max(-1, len(resultat) - 4), -1):
            existante = resultat[index]
            produit_existant = normaliser_texte(
                existante.get("produit_normalise", "")
            )
            if not produit or not produit_existant:
                continue
            reformulation_precision = meme_noyau_avec_precision(
                produit, produit_existant
            )
            if (
                fuzz.token_set_ratio(produit, produit_existant) < 94
                and not reformulation_precision
            ):
                continue
            if (
                set(produit.split()) & discriminants
                != set(produit_existant.split()) & discriminants
                and not reformulation_precision
            ):
                continue
            quantite_existante = existante.get("quantite_principale")
            if quantite is not None and quantite_existante is not None:
                if abs(float(quantite) - float(quantite_existante)) > 0.001:
                    continue
            unite_mention = mention.get("unite_principale") or mention.get("unite_detectee")
            unite_existante = existante.get("unite_principale") or existante.get("unite_detectee")
            if unite_mention and unite_existante and unite_mention != unite_existante:
                continue
            if mention.get("conditionnement_multiple") != existante.get("conditionnement_multiple"):
                continue
            position = index
            break

        if position is None:
            resultat.append(mention)
            continue

        existante = resultat[position]
        if existante.get("quantite_principale") is None and quantite is not None:
            # La reformulation quantifiee porte la structure utile de la
            # commande ("4 cartons de X").  Conserver son texte source est
            # essentiel : si X figure aussi dans le nom du client, garder le
            # texte de presentation non quantifie ferait ensuite exclure a
            # tort la ligne comme une enseigne.
            existante["texte_source"] = mention.get("texte_source", "")
            # La representation produit doit venir de la meme occurrence que
            # la quantite. Sinon la ligne garderait les mots de presentation
            # (par exemple "SAS X") tout en portant la quantite de "4
            # cartons de X", ce qui la ferait encore exclure comme client.
            for champ in (
                "texte_normalise",
                "produit_normalise",
                "texte_produit",
            ):
                existante[champ] = mention.get(champ, "")
            for champ in (
                "quantite_principale",
                "quantite",
                "unite_principale",
                "unite_detectee",
                "conditionnement_multiple",
            ):
                existante[champ] = mention.get(champ)
        if len(produit.split()) > len(
            normaliser_texte(existante.get("produit_normalise", "")).split()
        ):
            existante["produit_normalise"] = mention.get("produit_normalise")
            existante["texte_produit"] = mention.get("texte_produit")
            if quantite is not None:
                existante["texte_source"] = mention.get("texte_source", "")
        elif meme_noyau_avec_precision(
            produit,
            normaliser_texte(existante.get("produit_normalise", "")),
        ):
            # Deux clauses complementaires comme ``oeuf liquide`` puis
            # ``oeuf entier`` decrivent une seule ligne. On conserve l'union
            # des attributs sans additionner les quantites.
            tokens_existants = normaliser_texte(
                existante.get("produit_normalise", "")
            ).split()
            for token in produit.split():
                if token not in tokens_existants:
                    tokens_existants.append(token)
            produit_fusionne = " ".join(tokens_existants)
            existante["produit_normalise"] = produit_fusionne
            existante["texte_produit"] = produit_fusionne
        existante.setdefault("precisions_quantite", []).extend(
            mention.get("precisions_quantite", []) or []
        )
        existante.setdefault("exclusions_produit", []).extend(
            valeur
            for valeur in (mention.get("exclusions_produit", []) or [])
            if valeur not in existante.get("exclusions_produit", [])
        )
        raisons = set(existante.get("raisons_ambiguite", []) or [])
        raisons.update(mention.get("raisons_ambiguite", []) or [])
        raisons.discard("quantite_absente_a_resoudre")
        raisons.add("reformulation_proche_fusionnee")
        existante["raisons_ambiguite"] = sorted(raisons)
        existante["ambigu"] = bool(raisons)

    return resultat


def construire_catalogue_global(
    cadencier: dict[str, list[dict[str, Any]]],
    articles_reference: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Agrege les ventes de tous les clients puis complete par le referentiel."""
    catalogue: dict[str, dict[str, Any]] = {}

    for produits_client in cadencier.values():
        for produit in produits_client:
            code = str(produit["code_article"])
            if code not in catalogue:
                catalogue[code] = dict(produit)
                catalogue[code]["source_article"] = "historique_cadenciers"
                continue

            courant = catalogue[code]
            courant["nb_ventes_article_total"] = int(
                courant.get("nb_ventes_article_total", 0)
            ) + int(produit.get("nb_ventes_article_total", 0))
            courant["nb_ventes_article_recentes"] = int(
                courant.get("nb_ventes_article_recentes", 0)
            ) + int(produit.get("nb_ventes_article_recentes", 0))
            if int(produit.get("derniere_vente_article_ordinal", -1)) > int(
                courant.get("derniere_vente_article_ordinal", -1)
            ):
                courant["derniere_vente_article_ordinal"] = produit.get(
                    "derniere_vente_article_ordinal", -1
                )
                courant["derniere_vente_article_iso"] = produit.get(
                    "derniere_vente_article_iso", ""
                )
            if not courant.get("prix") and produit.get("prix"):
                courant["prix"] = produit.get("prix")

    for article in articles_reference or []:
        code = str(article.get("code_article") or "").strip()
        libelle = str(article.get("libelle_article") or "").strip()
        if not code or not libelle or code in catalogue:
            continue
        catalogue[code] = {
            "code_article": code,
            "libelle_article": libelle,
            "libelle_normalise": normaliser_texte(libelle),
            "prix": None,
            "nb_ventes_article_total": 0,
            "nb_ventes_article_recentes": 0,
            "derniere_vente_article_iso": "",
            "derniere_vente_article_ordinal": -1,
            "quantite_habituelle_commande": 0.0,
            "ratio_net_par_unite": 0.0,
            "unite_vente": article.get("unite_vente", ""),

            "source_article": "referentiel_articles",
        }

    return list(catalogue.values())


def _tokens_produit(
    texte: str,
) -> list[str]:
    tokens = normaliser_texte(texte).split()
    normalisations = {
        "uf": "oeuf",
        "ajouter": "",
        "rajouter": "",
        "talouac": "taloa",
        "talouak": "taloa",
        "talouaz": "taloa",
        "taloak": "taloa",
        "temperature": "temp",
        "bague": "bac",
        "bagues": "bac",
        "bacs": "bac",
        "barquette": "bac",
        "barquettes": "bac",
        "glaces": "glace",
        "glacee": "glace",
        "glacees": "glace",
        "sorbet": "glace",
        "sorbets": "glace",
        "fraises": "fraise",
        "framboises": "framboise",
        "surgele": "",
        "surgeles": "",
        "surgelee": "",
        "surgelees": "",
        "congele": "",
        "congeles": "",
        "congelee": "",
        "congelees": "",
        "mangues": "mangue",
        "pistaches": "pistache",
        "cafes": "cafe",
        "poudre": "rape",
        "poudres": "rape",
        "chipot": "chipolata",
        "chipots": "chipolata",
        "chipolatas": "chipolata",
        "amandes": "amande",
        "patagoni": "patagonica",
        "muties": "mutti",
        "contador": "cantadora",
        "teglatel": "tagliatelle",
        "seco": "cecco",
        "rabaz": "rabas",
        "rabats": "rabas",
        "oeufs": "oeuf",
        "ufs": "oeuf",
        "calibre": "",
        "calibres": "",
        "moyens": "moyen",
        "cubes": "cube",
        "pots": "pot",
        "seaux": "seau",
        "paquets": "paquet",
        "bouteilles": "bouteille",
        "sacs": "sac",
        "bidons": "bidon",
        "cartons": "carton",
    }
    tokens_normalises_resultat: list[str] = []
    for token in tokens:
        token = normalisations.get(token, token)
        motif_nombre_items = re.match(
            r"^x?(?P<nombre>\d{1,3})p?$",
            token,
        )
        if motif_nombre_items:
            token = motif_nombre_items.group("nombre")
        tokens_normalises_resultat.append(token)
    tokens = tokens_normalises_resultat

    return [
        token
        for token in tokens
        if token
        and token not in STOPWORDS_PRODUIT
        and len(token) >= 2
    ]


@lru_cache(maxsize=200_000)
def _cles_phonetiques_produit(token: str) -> frozenset[str]:
    """Variantes phonetiques prudentes pour les mots de catalogue."""
    base = normaliser_texte(token)
    if len(base) < 4 or not base.isalpha():
        return frozenset({base}) if base else frozenset()

    def commun(valeur: str) -> str:
        valeur = valeur.replace("eau", "o").replace("au", "o")
        valeur = valeur.replace("ph", "f").replace("qu", "k")
        valeur = valeur.replace("ck", "k").replace("y", "i")
        valeur = valeur.replace("h", "")
        valeur = re.sub(r"(.)\1+", r"\1", valeur)
        return valeur

    variantes = {
        commun(base),
        commun(base.replace("ch", "k")),
        commun(base.replace("ch", "sh")),
    }
    return frozenset(valeur for valeur in variantes if valeur)


@lru_cache(maxsize=500_000)
def _score_token_produit(token: str, token_libelle: str) -> float:
    # Flexion plurielle reguliere. Elle est traitee avant le fuzzy pour que
    # les noyaux courts mais autonomes (``miels`` -> ``miel``) restent des
    # preuves exactes, sans dictionnaire produit specifique.
    invariants_fin_s = {"jus", "mais", "poids", "riz"}
    if (
        min(len(token), len(token_libelle)) >= 4
        and token not in invariants_fin_s
        and token_libelle not in invariants_fin_s
        and (
            token == f"{token_libelle}s"
            or token_libelle == f"{token}s"
        )
    ):
        return 100.0
    # Une troncature orale naturelle (``mozza`` pour un mot catalogue plus
    # long, par exemple) est un signal lexical fort : elle conserve la racine
    # exacte du mot, contrairement a une simple similarite fuzzy.  On exige
    # au moins quatre caracteres et une racine couvrant la moitie du mot de
    # catalogue afin de ne pas transformer les tres courts debuts de mots en
    # equivalences generiques.
    if (
        len(token) >= 4
        and len(token_libelle) > len(token)
        and len(token) / len(token_libelle) >= 0.5
        and token_libelle.startswith(token)
        # Un contenant ou une unite n'est jamais, a lui seul, une racine
        # produit distinctive (ex. ``cart`` / ``carton``).
        and token_libelle not in UNITES_EQUIVALENCES
        and token_libelle not in TOKENS_CONDITIONNEMENT_SANS_PRODUIT
    ):
        return 100.0

    score_brut = float(fuzz.ratio(token, token_libelle))
    if score_brut >= 90.0 or min(len(token), len(token_libelle)) < 4:
        return score_brut

    score_phonetique = max(
        (
            float(fuzz.ratio(cle_mention, cle_libelle))
            for cle_mention in _cles_phonetiques_produit(token)
            for cle_libelle in _cles_phonetiques_produit(token_libelle)
        ),
        default=0.0,
    )
    return max(score_brut, score_phonetique if score_phonetique >= 96.0 else 0.0)


def _clause_ressemble_a_produit(
    clause_norm: str,
) -> bool:
    texte = normaliser_texte(clause_norm)

    if not texte:
        return False

    if any(
        texte == expression
        or texte.startswith(f"{expression} ")
        for expression in EXPRESSIONS_NON_PRODUIT
    ):
        return False
    tokens = _tokens_produit(texte)

    if not tokens:
        return False

    tokens_generiques = {
        "bonjour",
        "bonsoir",
        "merci",
        "salut",
        "ciao",
        "bye",
        "client",
        "restaurant",
        "voudrais",
        "souhaite",
        "commande",
        "commandes",
        "appareil",
        "demain",
        "alors",
        "oui",
        "non",
        "donc",
        "ensuite",
        "suivre",
        "fois",
        "litre",
        "litres",
        "kilo",
        "kilos",
        "gramme",
        "grammes",
        "piece",
        "pieces",
        "carton",
        "cartons",
        "colis",
        "poche",
        "poches",
        "boite",
        "boites",
        "barquette",
        "barquettes",
        "paquet",
        "paquets",
        "bidon",
        "bidons",
        "seau",
        "seaux",
        "bouteille",
        "bouteilles",
        "unite",
        "unites",
        "portion",
        "portions",
        "pot",
        "pots",
        "un",
        "une",
        "deux",
        "trois",
        "quatre",
        "cinq",
        "six",
        "sept",
        "huit",
        "neuf",
        "dix",
        "onze",
        "douze",
        "treize",
        "quatorze",
        "quinze",
        "seize",
        "vingt",
        "trente",
        "quarante",
        "cinquante",
        "soixante",
        "cent",
        "mille",
        "voila",
        "petit",
        "petite",
        "petits",
        "petites",
        "grand",
        "grande",
        "grands",
        "grandes",
        "groupe",
        "groupes",
        "aout",
        "matin",
        "soir",
        "midi",
        "pourcent",
        "marque",
        "comment",
        "appelle",
        "appelles",
        "appeler",
        "dire",
        "dis",
        "mettez",
        "mettez-moi",
        "rajoute",
        "rajoutez",
        "ajoutez",
        "livrez",
        "prendrez",
        "prendrai",
        "prendre",
        "prenons",
        "crois",
        "pense",
        "preferez",
        "preferes",
        "benoit",
        "excusez",
        "pardon",
        "autre",
        "autres",
        "nouveau",
        "nouveaux",
        "produit",
        "produits",
        "prix",
        "meilleur",
        "cadencier",
    } | TOKENS_SANS_NOYAU_PRODUIT | TOKENS_CONDITIONNEMENT_SANS_PRODUIT | (
        FORMES_DISCOURS_COMMANDE | NOMS_DISCOURS_COMMANDE | TOKENS_CALENDRIER
    )

    return any(
        token not in tokens_generiques
        for token in tokens
    )


def _preuve_positive_noyau_produit(
    texte_source: str,
    candidat: dict[str, Any],
    variantes_recherche: list[str] | None = None,
    mention: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """Exige une preuve lexicale positive avant de creer une ligne.

    Le score global et l'historique client ne prouvent pas qu'une clause est
    un article. La preuve vient soit d'un mot produit effectivement partage,
    soit d'une variante issue du dictionnaire lexical autorise, soit d'une
    forme ASR longue et tres proche. Les fragments courts comme ``saut`` ne
    peuvent ainsi plus devenir ``saute de porc`` par simple prefixe fuzzy,
    tandis qu'un vrai nom court exact (``riz``, ``feta``) reste valide.
    """
    if candidat.get("code_article_prononce_exact"):
        return True, ["preuve_code_article_prononce"]
    if candidat.get("noyau_phonetique_cadencier_prouve"):
        return True, ["preuve_noyau_phonetique_cadencier_bornee"]

    mention = mention or {}
    source_norm = normaliser_texte(texte_source)
    tokens_discours_stricts = {
        "belle", "bon", "bonne", "bonjour", "comment", "detail",
        "direct", "egalement", "importe", "journee", "merci", "pareil",
        "pareille", "point", "question", "rebonjour", "sinon", "soiree",
        "voila",
    }
    tokens_source_bruts = set(_tokens_produit(source_norm))
    clause_incomplete = bool(
        re.search(r"\b(?:de|d|avec|pour|et|sans|en)\s*$", source_norm)
        and mention.get("unite_principale") is None
        and not mention.get("precisions_quantite")
    )
    if (
        tokens_source_bruts
        and tokens_source_bruts <= tokens_discours_stricts
    ):
        return False, ["clause_discursive_ou_incomplete"]

    libelle = str(
        candidat.get("libelle_normalise")
        or candidat.get("libelle_article")
        or ""
    )
    tokens_libelle = _tokens_produit(libelle)
    if not tokens_libelle:
        return False, []

    tokens_non_noyau = (
        TOKENS_SANS_NOYAU_PRODUIT
        | TOKENS_CONDITIONNEMENT_SANS_PRODUIT
        | QUALIFICATIFS_PRODUIT
        | FORMES_DISCOURS_COMMANDE
        | NOMS_DISCOURS_COMMANDE
        | TOKENS_CALENDRIER
    )

    def tokens_significatifs(texte: str) -> list[str]:
        return [
            token
            for token in _tokens_produit(texte)
            if token not in tokens_non_noyau
            and not token.isdigit()
            and not re.fullmatch(r"\d+(?:[.,]\d+)?[a-z]*", token)
        ]

    tokens_source = tokens_significatifs(texte_source)
    exacts = sorted(set(tokens_source) & set(tokens_libelle))
    if exacts:
        return True, [f"preuve_noyau_exact={token}" for token in exacts]

    def racine_flexion(token: str) -> str:
        if len(token) >= 5 and token.endswith("es"):
            return token[:-1]
        if (
            len(token) >= 5
            and token.endswith("s")
            and not token.endswith(("is", "ss", "us"))
        ):
            return token[:-1]
        return token

    racines_source = {racine_flexion(token) for token in tokens_source}
    racines_libelle = {racine_flexion(token) for token in tokens_libelle}
    racines_communes = sorted(racines_source & racines_libelle)
    if racines_communes:
        return True, [
            f"preuve_noyau_flexion={token}"
            for token in racines_communes
        ]

    # Les equivalences explicites de la table de synonymes sont des preuves
    # autorisees : elles restent lexicales et ne contiennent aucune verite
    # ERP cible. On ignore la variante identique a la source, deja testee.
    for variante in variantes_recherche or []:
        if normaliser_texte(variante) == source_norm:
            continue
        ancres_variante = sorted(
            set(tokens_significatifs(variante)) & set(tokens_libelle)
        )
        if ancres_variante:
            return True, [
                f"preuve_noyau_synonyme={token}"
                for token in ancres_variante
            ]

    famille_source = primary_product_family(texte_source)
    famille_libelle = primary_product_family(libelle)
    if famille_source and famille_source == famille_libelle:
        return True, [f"preuve_famille_produit={famille_source}"]

    for token in tokens_source:
        if len(token) < 5:
            continue
        for token_libelle in tokens_libelle:
            if len(token_libelle) < 5:
                continue
            # Troncature orale longue, couvrant au moins la moitie du terme.
            if (
                token_libelle.startswith(token)
                and len(token) / len(token_libelle) >= 0.5
            ):
                return True, [f"preuve_noyau_racine={token}"]
            # La phonétique n'est admise ici qu'a un seuil plus strict que le
            # ranking. Elle confirme une famille plausible, elle ne la cree
            # pas a partir d'un mot court ou generique.
            if _score_token_produit(token, token_libelle) >= 96.0:
                return True, [f"preuve_noyau_phonetique={token}"]

    # Les mots de liaison, d'interface ou de politesse ne deviennent jamais
    # une preuve simplement parce qu'une quantité a été extraite devant eux.
    # Cette vérification intervient après les correspondances exactes : un
    # vrai article court reste donc reconnu, mais une clause composée
    # uniquement de ``point / direct / comment / journée`` ne peut plus
    # emprunter la crédibilité du cadencier.
    if tokens_source and set(tokens_source) <= tokens_discours_stricts:
        return False, ["clause_sans_noyau_apres_nettoyage_discours"]

    if clause_incomplete:
        return False, ["clause_discursive_ou_incomplete"]

    # Reconstitue uniquement un noyau long coupe/soude par l'ASR, dans le
    # candidat deja selectionne du cadencier. Exemples generiques :
    # ``sacoubelle`` -> ``sacs poubelle`` et ``souris mi`` -> ``surimi``.
    # Le seuil eleve et la longueur minimale interdisent qu'un fragment de
    # discours court suffise a inventer une famille produit.
    if candidat.get("dans_cadencier_client"):
        groupes_source = [
            token for token in tokens_source if len(token) >= 6
        ] + [
            "".join(tokens_source[index:index + 2])
            for index in range(max(0, len(tokens_source) - 1))
            if len("".join(tokens_source[index:index + 2])) >= 7
        ]
        groupes_libelle = [
            token for token in tokens_libelle if len(token) >= 6
        ] + [
            "".join(tokens_libelle[index:index + 2])
            for index in range(max(0, len(tokens_libelle) - 1))
            if len("".join(tokens_libelle[index:index + 2])) >= 7
        ]
        meilleur_compose = max(
            (
                _score_token_produit(source, cible)
                for source in groupes_source
                for cible in groupes_libelle
            ),
            default=0.0,
        )
        if meilleur_compose >= 85.0:
            return True, [
                f"preuve_noyau_asr_compose_cadencier={meilleur_compose:.2f}"
            ]

    # Whisper peut deformer un vrai noyau, mais la structure ``quantite +
    # contenant`` ne prouve jamais un produit a elle seule. Le secours
    # cadencier exige donc encore un rapprochement lexical substantiel.
    quantite_explicite = mention.get("quantite_principale") is not None
    structure_nominale = bool(
        mention.get("unite_principale") is not None
        or len(tokens_source) >= 2
        or any(len(token) >= 5 for token in tokens_source)
    )
    meilleur_rapprochement_substantiel = max(
        (
            _score_token_produit(token, token_libelle)
            for token in tokens_source
            if len(token) >= 4
            for token_libelle in tokens_libelle
            if len(token_libelle) >= 4
        ),
        default=0.0,
    )
    if (
        candidat.get("dans_cadencier_client")
        and quantite_explicite
        and structure_nominale
        and candidat.get("semantiquement_compatible", True)
        and float(candidat.get("score_texte") or 0.0) >= 42.0
        and meilleur_rapprochement_substantiel >= 82.0
    ):
        return True, ["preuve_asr_substantielle_cadencier_quantifiee"]

    return False, []


def _incompatibilites_semantiques(
    texte_mention: str,
    texte_libelle: str,
    exclusions: list[str] | None = None,
) -> list[str]:
    """Detecte les variantes explicitement contradictoires entre elles."""
    mention = normaliser_texte(texte_mention)
    libelle = normaliser_texte(texte_libelle)
    raisons: list[str] = []

    def mention_contient(*termes: str) -> bool:
        return any(terme in mention for terme in termes)

    def libelle_contient(*termes: str) -> bool:
        return any(terme in libelle for terme in termes)

    demande_surgele = bool(re.search(r"\b(?:surgele|congele)(?:e|es|s)?\b", mention))
    demande_frais = bool(re.search(r"\b(?:frais|fraiche|fraiches)\b", mention))
    if demande_surgele and re.search(r"\b(?:frais|fraiche|fraiches)\b", libelle):
        raisons.append("etat_produit_contradictoire")
    if demande_frais and re.search(r"\b(?:surgele|congele)(?:e|es|s)?\b", libelle):
        raisons.append("etat_produit_contradictoire")
    demande_cru = bool(re.search(r"\bcru(?:e|es|s)?\b", mention))
    if demande_cru and re.search(
        r"\b(?:pane|panee|panees|panes|cuit|cuite|cuites|cuits|"
        r"precuit|precuite|precuites|precuits|frit|frite|frites|frits|"
        r"croute|croquettes?)\b",
        libelle,
    ):
        # L'etat explicitement demande est une contrainte de produit, quelle
        # que soit sa famille. Une preparation panee/cuite ne peut donc pas
        # gagner sur un aliment demande cru par l'effet du seul cadencier.
        raisons.append("etat_transformation_contradictoire")
    demande_farinee = bool(
        re.search(r"\b(?:farine|farinee|farinees|farines|farinata)\b", mention)
    )
    demande_panee = bool(
        re.search(r"\b(?:pane|panee|panees|panes)\b", mention)
    )
    libelle_farine = bool(
        re.search(r"\b(?:farine|farinee|farinees|farines|farinata)\b", libelle)
    )
    libelle_pane = bool(
        re.search(r"\b(?:pane|panee|panees|panes)\b", libelle)
    )
    if demande_farinee and libelle_pane and not libelle_farine:
        raisons.append("preparation_farine_panee_contradictoire")
    if demande_panee and libelle_farine and not libelle_pane:
        raisons.append("preparation_farine_panee_contradictoire")
    if demande_surgele:
        formes_transformees = {
            "sorbet", "glace", "puree", "coulis", "vinaigre",
            "jus", "confiture", "sirop",
        }
        if any(forme in _tokens_produit(libelle) for forme in formes_transformees):
            raisons.append("forme_produit_surgele_contradictoire")
        familles_fruits = {
            "fraise", "framboise", "mangue", "ananas", "myrtille",
            "cerise", "peche", "abricot", "mure", "cassis",
        }
        fruits_demandes = set(_tokens_produit(mention)) & familles_fruits
        if fruits_demandes and not (
            set(_tokens_produit(libelle)) & fruits_demandes
        ):
            raisons.append("famille_fruit_surgele_absente")

    sucre_explicitement_exclu = bool(
        re.search(
            r"\b(?:sans|pas\s+de|non)\s+sucre\b|\b0\s*%?\s+sucre\b",
            mention,
        )
    )
    if sucre_explicitement_exclu and re.search(
        r"\bsucre\b", libelle
    ) and not libelle_contient("sans sucre", "non sucre", "0 sucre"):
        raisons.append("sucre_explicitement_exclu")

    if "sucre" in mention and not sucre_explicitement_exclu:
        if "creme" not in mention and "chantilly" not in mention and libelle_contient("creme", "chantilly"):
            raisons.append("famille_creme_contradictoire_avec_sucre")
        if not mention_contient("puree", "coulis", "fruit") and libelle_contient("puree", "coulis"):
            raisons.append("famille_puree_contradictoire_avec_sucre")
        if not mention_contient("crepe", "gaufre", "beignet") and libelle_contient("crepe", "gaufre", "beignet"):
            raisons.append("famille_crepe_contradictoire_avec_sucre")
        variantes_sucre = {
            "semoule": ("semoule",),
            "glace": ("glace",),
            "roux": ("roux", "cassonade"),
        }
        variantes_demandees = {
            nom for nom, termes in variantes_sucre.items()
            if mention_contient(*termes)
        }
        if re.search(r"\bsucre\b[^,;.]*\ben\s+poudre\b", mention):
            variantes_demandees.add("semoule")
        variantes_libelle = {
            nom for nom, termes in variantes_sucre.items()
            if libelle_contient(*termes)
        }
        if variantes_demandees and variantes_libelle and not (
            variantes_demandees & variantes_libelle
        ):
            raisons.append("variante_sucre_contradictoire")

    if "creme" in mention:
        if not libelle_contient(
            "creme", "cream cheese", "fromage", "philadelphia"
        ):
            raisons.append("famille_creme_absente")
        if "cheese" in mention and not libelle_contient(
            "cream cheese", "creme cheese", "fromage"
        ):
            raisons.append("cream_cheese_absent")
        if "liquide" in mention and "epaisse" in libelle:
            raisons.append("texture_creme_contradictoire")
        if "epaisse" in mention and "liquide" in libelle:
            raisons.append("texture_creme_contradictoire")
        taux_mention = re.search(
            r"\b(?P<taux>\d{1,2})\s*(?:%|pour cent)\b", mention
        )
        taux_libelle = re.search(r"\b(?P<taux>\d{1,2})\s*%", libelle)
        if (
            taux_mention
            and taux_libelle
            and taux_mention.group("taux") != taux_libelle.group("taux")
        ):
            raisons.append("taux_creme_contradictoire")

    if "glace" in _tokens_produit(mention) and not libelle_contient(
        "glace", "glacee", "sorbet"
    ):
        raisons.append("categorie_glace_absente")
    libelle_est_glace = libelle_contient("creme glacee", "sorbet artisanal")
    if (
        not mention_contient("glace", "glacee", "sorbet")
        and mention_contient("fromage", "creme", "liquide", "philadelphia")
        and libelle_est_glace
    ):
        raisons.append("categorie_glace_non_demandee")

    if "nuggets" in mention and "nuggets" not in libelle:
        raisons.append("famille_nuggets_absente")

    if "burrata" in mention and "burrata" not in libelle:
        raisons.append("famille_burrata_absente")
    if (
        "mozzarella" in mention
        and "burrata" not in mention
        and "burrata" in libelle
    ):
        raisons.append("mozzarella_confondue_avec_burrata")
    if mention_contient("bufala", "buffala", "bufflonne") and libelle_contient(
        "vache", "bovin"
    ):
        raisons.append("lait_mozzarella_contradictoire")
    if "mozzarella" in mention:
        if mention_contient("rapee", "rape") and not libelle_contient(
            "rapee", "rape"
        ):
            raisons.append("forme_mozzarella_contradictoire")
        if mention_contient("pas la rapee", "non rapee", "morceaux") and libelle_contient(
            "rapee", "rape"
        ):
            raisons.append("forme_mozzarella_contradictoire")

    if mention_contient("parmesan", "parmigiano"):
        if mention_contient("copeau", "copeaux", "petale", "petales") and not libelle_contient(
            "copeau", "copeaux", "petale", "petales"
        ):
            raisons.append("forme_parmesan_contradictoire")
        if mention_contient("rape", "rapee") and libelle_contient(
            "copeau", "petale", "bloc", "pointe"
        ):
            raisons.append("forme_parmesan_contradictoire")
        if mention_contient("bloc", "pointe") and libelle_contient(
            "rape", "copeau", "petale"
        ):
            raisons.append("forme_parmesan_contradictoire")

    if "piquill" in mention and "piquill" not in libelle:
        raisons.append("famille_piquillos_absente")

    if "sriracha" in mention:
        if "sriracha" not in libelle:
            raisons.append("famille_sriracha_absente")
        if "rouge" in mention and libelle_contient(
            "mayonnaise", "vert", "chanvre", "kimchi"
        ):
            raisons.append("variante_sriracha_contradictoire")

    if mention_contient("tomate", "tomates") and mention_contient(
        "seche", "seches", "sechee", "sechees"
    ) and not libelle_contient("seche", "seches", "confite", "confites"):
        raisons.append("forme_tomate_sechee_absente")

    if "riz" in mention and "complet" in mention and not libelle_contient(
        "complet", "integral"
    ):
        raisons.append("variante_riz_complet_absente")
    if "riz" in mention and "riz" not in libelle:
        raisons.append("famille_riz_absente")

    if "lasagne" in mention and "halal" in mention and "halal" not in libelle:
        raisons.append("certification_halal_absente")
    if "lasagne" in mention and "lasagne" not in libelle:
        raisons.append("famille_lasagne_absente")

    if "poche" in mention and "sous vide" in mention and not (
        "poche" in libelle and "sous vide" in libelle
    ):
        raisons.append("categorie_emballage_sous_vide_absente")

    if "huile" in mention:
        if "olive" in mention and libelle_contient("tournesol", "colza", "friture"):
            raisons.append("type_huile_contradictoire")
        if mention_contient("friture", "tournesol", "colza") and "olive" in libelle:
            raisons.append("type_huile_contradictoire")

    if "lait" in mention:
        familles_lait_qualificatif = {
            "burrata",
            "fromage",
            "mozzarella",
            "yaourt",
        }
        famille_qualifiee = (
            set(_tokens_produit(mention))
            & set(_tokens_produit(libelle))
            & familles_lait_qualificatif
        )
        variante_animale_preservee = not mention_contient(
            "vache", "bovin", "bufala", "buffala", "bufflonne", "brebis", "chevre"
        ) or libelle_contient(
            "vache", "bovin", "bufala", "buffala", "bufflonne", "brebis", "chevre"
        )
        if (
            "lait" not in libelle
            and not (famille_qualifiee and variante_animale_preservee)
        ):
            raisons.append("famille_lait_absente")
        if "coco" in mention and "coco" not in libelle:
            raisons.append("variante_lait_coco_absente")
        if "entier" in mention and libelle_contient(
            "demi ecreme", "1 2 ecreme", "ecreme"
        ):
            raisons.append("type_lait_contradictoire")
        if mention_contient("demi ecreme", "1 2 ecreme") and "entier" in libelle:
            raisons.append("type_lait_contradictoire")

    familles_obligatoires = {
        "tartare": ("tartare",),
        "croque": ("croque",),
        "cornichon": ("cornichon",),
        "harissa": ("harissa",),
        "nachos": ("nachos",),
        "coulis": ("coulis", "puree"),
    }
    for ancre, formes_libelle in familles_obligatoires.items():
        if ancre in mention and not libelle_contient(*formes_libelle):
            raisons.append(f"famille_{ancre}_absente")

    if "poisson" in mention and not libelle_contient(
        "poisson", "cabillaud", "colin", "merlu", "saumon", "thon",
        "dorade", "lieu", "sole", "hoki", "eglefin", "bar"
    ):
        raisons.append("famille_poisson_absente")

    if "chocolat" in mention:
        if "chocolat" not in libelle:
            raisons.append("famille_chocolat_absente")
        if not mention_contient("mousse") and "mousse" in libelle:
            raisons.append("forme_chocolat_contradictoire")
        if (
            mention_contient("pistole", "pistoles", "pastille", "pastilles")
            and libelle_contient(
                "mousse", "poudre", "tablette", "copeau", "copeaux"
            )
            and not libelle_contient(
                "pistole", "pistoles", "pastille", "pastilles"
            )
        ):
            raisons.append("forme_chocolat_contradictoire")

    if "vinaigre" in mention:
        if "vinaigre" not in libelle:
            raisons.append("famille_vinaigre_absente")
        types_vinaigre = {
            "cidre": ("cidre",),
            "alcool": ("alcool",),
            "balsamique": ("balsamique",),
            "vin blanc": ("vin blanc",),
            "vin rouge": ("vin rouge",),
        }
        demandes = {
            nom for nom, formes in types_vinaigre.items()
            if mention_contient(*formes)
        }
        presents = {
            nom for nom, formes in types_vinaigre.items()
            if libelle_contient(*formes)
        }
        if demandes and presents and not (demandes & presents):
            raisons.append("type_vinaigre_contradictoire")

    if "jambon" in mention:
        if mention_contient("tranche", "tranches") and libelle_contient("bloc", "demi"):
            raisons.append("forme_jambon_contradictoire")
        if mention_contient("bloc", "entier") and libelle_contient("tranche", "tranches"):
            raisons.append("forme_jambon_contradictoire")

    animaux = {
        "veau", "boeuf", "porc", "agneau", "canard", "poulet", "dinde"
    }
    animaux_demandes = set(_tokens_produit(mention)) & animaux
    if animaux_demandes and not (
        set(_tokens_produit(libelle)) & animaux_demandes
    ):
        raisons.append("espece_animale_absente")

    # Les morceaux anatomiques explicitement prononces sont des contraintes
    # de variante : une cotelette d'agneau ne peut pas devenir une epaule
    # parce que celle-ci est plus achetee. Cette verification reste ici, dans
    # le filtre de compatibilite, et non dans l'ontologie des attributs : elle
    # ne doit jamais elargir la recherche Reapro aux libelles qui contiennent
    # incidentalement le mot "cote" (ex. boeuf bourguignon dessus de cotes).
    morceaux_animaux = {
        "cote": ("cote", "cotes", "cotelette", "cotelettes"),
        "epaule": ("epaule", "epaules"),
        "gigot": ("gigot", "gigots"),
        "joue": ("joue", "joues"),
        "carre": ("carre", "carres"),
        "collier": ("collier", "colliers"),
        "jarret": ("jarret", "jarrets"),
        "souris": ("souris",),
    }
    morceaux_demandes = {
        canonique
        for canonique, formes in morceaux_animaux.items()
        if mention_contient(*formes)
    }
    morceaux_libelle = {
        canonique
        for canonique, formes in morceaux_animaux.items()
        if libelle_contient(*formes)
    }
    # Sans espece explicite, certains termes sont trop ambigus pour devenir
    # une contrainte anatomique (Whisper peut par exemple ecrire "souris mi"
    # pour *surimi*). Le filtre reste donc reserve aux mentions de viande
    # telles que "cotelette d'agneau" ou "gigot de porc".
    if animaux_demandes and morceaux_demandes and not (
        morceaux_demandes & morceaux_libelle
    ):
        raisons.append(
            "morceau_animal_contradictoire"
            if morceaux_libelle
            else "morceau_animal_explicite_absent"
        )

    if "beurre" in mention:
        if "tourage" in mention and "tourage" not in libelle:
            raisons.append("usage_beurre_contradictoire")
        if "demi sel" in mention and "doux" in libelle:
            raisons.append("type_beurre_contradictoire")

    for exclusion in exclusions or []:
        exclusion_norm = normaliser_texte(exclusion)
        alias = {
            "pulqueau": "pulco",
            "pulko": "pulco",
            "pulque": "pulco",
        }.get(exclusion_norm, exclusion_norm)
        tokens_exclusion = [
            token for token in _tokens_produit(alias) if len(token) >= 4
        ]
        tokens_libelle = _tokens_produit(libelle)
        if any(
            max(
                (fuzz.ratio(token, token_libelle) for token_libelle in tokens_libelle),
                default=0,
            ) >= 84
            for token in tokens_exclusion
        ):
            raisons.append("exclusion_client_contredite")

    # Une variante principale explicitement prononcee (fruit, parfum,
    # ingredient) est une contrainte de sens : le cadencier peut departager
    # les candidats compatibles, mais ne peut jamais substituer une autre
    # variante uniquement parce qu'elle est plus achetee par ce client.
    if business_rule_enabled("attributs_explicites_prioritaires"):
        conflits_attributs = explicit_attribute_conflicts(mention, libelle)
        # Le conflit de noyau principal est un filet generique. Lorsqu'une
        # regle de famille plus precise a deja explique le rejet, ne pas
        # dupliquer la cause dans le diagnostic.
        if raisons:
            conflits_attributs = [
                raison
                for raison in conflits_attributs
                if raison != "noyau_produit_principal_contradictoire"
            ]
        raisons.extend(conflits_attributs)

    return sorted(set(raisons))


def _score_correspondance_produit(
    texte_mention: str,
    texte_libelle: str,
    unite_mention: str | None,
    texte_semantique: str | None = None,
) -> float:
    mention_norm = normaliser_texte(texte_mention)
    libelle_norm = normaliser_texte(texte_libelle)

    tokens_mention = _tokens_produit(mention_norm)
    tokens_libelle = _tokens_produit(libelle_norm)

    if not tokens_mention:
        return 0.0

    couverture = 0.0

    for token in tokens_mention:
        meilleur = max(
            (
                _score_token_produit(token, token_lib)
                for token_lib in tokens_libelle
            ),
            default=0.0,
        )

        if meilleur >= 90:
            couverture += 1.0
        elif meilleur >= 80:
            couverture += 0.6
        elif meilleur >= 70:
            couverture += 0.3

    ratio_couverture = min(
        1.0,
        couverture / len(tokens_mention),
    )

    score_set = float(
        fuzz.token_set_ratio(
            mention_norm,
            libelle_norm,
        )
    )
    score_sort = float(
        fuzz.token_sort_ratio(
            mention_norm,
            libelle_norm,
        )
    )

    score = (
        ratio_couverture * 55.0
        + score_set * 0.30
        + score_sort * 0.15
    )

    etat_surgele_mentionne = bool(
        re.search(r"\b(?:surgele|congele)(?:e|es|s)?\b", mention_norm)
    )
    if (
        etat_surgele_mentionne
        and tokens_mention
        and all(token in tokens_libelle for token in tokens_mention)
    ):
        score = max(score, 92.0)
    if ratio_couverture >= 0.95:
        if len(tokens_mention) >= 2:
            score = max(score, 94.0)
        else:
            score = max(score, 88.0)

    est_glace_mention = any(
        m in tokens_mention for m in {"glace", "sorbet"}
    )
    est_glace_libelle = any(
        m in tokens_libelle for m in {"glace", "glacee", "sorbet"}
    )
    if est_glace_mention:
        if est_glace_libelle:
            score += 18.0
        if any(
            m in tokens_libelle
            for m in {"arome", "sirop", "puree", "extrait", "topping", "mix", "pate"}
        ) and not any(
            m in tokens_mention
            for m in {"arome", "sirop", "puree", "extrait", "topping", "mix", "pate"}
        ):
            score -= 35.0

    if "oeuf" in tokens_mention and not any(
        m in tokens_mention for m in {"liquide", "jaune", "blanc", "dur"}
    ):
        if any(
            m in tokens_libelle
            for m in {"blanc", "jaune", "dur", "liquide", "brioche", "lasagne"}
        ):
            score -= 40.0
        if any(
            m in tokens_libelle
            for m in {"arradoy", "frais", "plein", "caisse"}
        ):
            score += 18.0

    # Garde-fous de categorie: un mot secondaire commun ne doit pas faire
    # passer un produit compose devant le produit explicitement demande.
    if "jambon" in tokens_mention and "jambon" not in tokens_libelle:
        score -= 45.0
    if (
        "oeuf" in tokens_mention
        and len(tokens_mention) <= 2
        and any(
            mot in tokens_libelle
            for mot in {"brioche", "pate", "nouille", "tagliatelle", "pasta"}
        )
    ):
        score -= 45.0
    if (
        "beurre" in tokens_mention
        and not any(mot in tokens_mention for mot in {"caramel", "nappage", "sauce"})
        and any(mot in tokens_libelle for mot in {"caramel", "nappage", "sauce"})
    ):
        score -= 45.0
    if "feta" in tokens_mention and "bloc" in tokens_mention and "cube" in tokens_libelle:
        score -= 30.0
    if "latex" in tokens_mention and "latex" not in tokens_libelle:
        score -= 35.0
    if (
        re.search(r"\btaille\s+m\b", mention_norm)
        and re.search(r"\btaille\s+(?:l|xl|s)\b", libelle_norm)
    ):
        score -= 25.0

    volumes_libelle: list[float] = []
    for match in re.finditer(
        r"(?:(?P<entier>\d+)\s+(?P<decimal>\d+)|(?P<simple>\d+))\s*l\b",
        libelle_norm,
    ):
        if match.group("entier") is not None:
            volumes_libelle.append(
                float(f"{match.group('entier')}.{match.group('decimal')}")
            )
        else:
            volumes_libelle.append(float(match.group("simple")))
    if "glace" in tokens_mention and "grand format" in mention_norm and volumes_libelle:
        score += 22.0 if max(volumes_libelle) >= 4.0 else -22.0
    if "glace" in tokens_mention and "petit format" in mention_norm and volumes_libelle:
        score += 22.0 if max(volumes_libelle) < 4.0 else -22.0

    # Glacons vs Glace
    if any(m in tokens_mention for m in {"glacon", "glacons", "glacone"}):
        if any(m in tokens_libelle for m in {"glacon", "glacons"}):
            score += 30.0
        if any(m in tokens_libelle for m in {"glace", "glacee", "sorbet", "creme"}):
            score -= 50.0

    # Contenant explicite
    if "pot" in tokens_mention and "pot" in tokens_libelle:
        score += 15.0
    if "seau" in tokens_mention and "seau" in tokens_libelle:
        score += 15.0

    # Mozzarella cossette
    if "cossette" in tokens_mention:
        if "cossette" in tokens_libelle:
            score += 30.0
        else:
            score -= 30.0

    # Puree Boiron
    if "boiron" in tokens_mention:
        if "boiron" in tokens_libelle:
            score += 25.0
        else:
            score -= 20.0

    if ratio_couverture < 0.3:
        score = min(score, 55.0)

    if (
        unite_mention
        and re.search(
            rf"\b{re.escape(unite_mention.lower())}\b",
            libelle_norm,
        )
    ):
        score += 4.0

    # Les variantes de recherche servent a retrouver un candidat. Elles ne
    # constituent pas une information prononcee et ne doivent donc jamais
    # creer une contradiction semantique. Seule la mention source peut le
    # faire.
    if _incompatibilites_semantiques(
        texte_semantique if texte_semantique is not None else mention_norm,
        libelle_norm,
    ):
        score = min(score, 20.0)

    return round(min(100.0, score), 2)


def _generer_variantes_recherche(
    produit_normalise: str,
    synonymes: dict[str, list[str]],
) -> list[str]:
    base = normaliser_texte(produit_normalise)

    if not base:
        return []

    variantes = {base}
    base_padding = f" {base} "

    def formes_recherche(terme: str) -> set[str]:
        """Accepte les flexions simples d'un alias ASR multi-mots.

        Les synonymes restent des équivalences lexicales, jamais des codes
        article. Une flexion française ordinaire (``sauce`` / ``sauces``)
        ne doit donc pas empêcher la normalisation d'une marque ou variante
        déjà déclarée. Les mots courts et les finales ambiguës restent
        inchangés pour éviter une lemmatisation agressive.
        """
        tokens = terme.split()
        formes = {terme}
        for index, token in enumerate(tokens):
            flexions: set[str] = set()
            if len(token) >= 5 and token.endswith("es"):
                flexions.add(token[:-1])
            elif len(token) >= 5 and token.endswith("s"):
                flexions.add(token[:-1])
            elif len(token) >= 4:
                flexions.add(f"{token}s")
            for flexion in flexions:
                variante = list(tokens)
                variante[index] = flexion
                formes.add(" ".join(variante))
        return formes

    for canonique, termes in synonymes.items():
        canonique_norm = normaliser_texte(canonique)
        # Une entree du dictionnaire est une equivalence bidirectionnelle.
        # Auparavant seuls les alias places dans la liste declenchaient le
        # groupe : prononcer directement la forme canonique (par exemple
        # ``cream cheese``) n'engendrait donc jamais ``fromage fouette``.
        termes_norm = sorted({
            forme
            for terme in [canonique_norm, *termes]
            for forme in formes_recherche(normaliser_texte(terme))
            if forme
        })

        termes_presents = [
            terme
            for terme in termes_norm
            if f" {terme} " in base_padding
        ]

        # Whisper inverse parfois deux mots d'un même nom composé ou ajoute
        # une terminaison à un seul d'entre eux. La tolérance est strictement
        # bornée aux groupes de synonymes déclarés, à 2-3 mots et à un seul
        # mot imparfait : aucune recherche fuzzy globale n'est ouverte.
        tokens_base = base.split()
        for terme in termes_norm:
            tokens_terme = terme.split()
            if not (2 <= len(tokens_terme) <= 3):
                continue
            largeur = len(tokens_terme)
            for index in range(len(tokens_base) - largeur + 1):
                fenetre = tokens_base[index:index + largeur]
                fragment = " ".join(fenetre)
                if fragment in termes_presents:
                    continue
                meilleurs_scores: tuple[float, ...] = ()
                for ordre in permutations(fenetre):
                    scores = tuple(
                        float(fuzz.ratio(source, attendu))
                        for source, attendu in zip(ordre, tokens_terme)
                    )
                    if (
                        not meilleurs_scores
                        or sum(scores) > sum(meilleurs_scores)
                    ):
                        meilleurs_scores = scores
                if (
                    meilleurs_scores
                    and min(meilleurs_scores) >= 85.0
                    and sum(meilleurs_scores) / len(meilleurs_scores) >= 92.0
                    and sum(score < 99.9 for score in meilleurs_scores) <= 1
                ):
                    termes_presents.append(fragment)

        termes_presents = list(dict.fromkeys(termes_presents))

        if not termes_presents:
            continue

        for terme_present in termes_presents:
            for terme_cible in termes_norm:
                variantes.add(
                    base.replace(
                        terme_present,
                        terme_cible,
                    )
                )
            variantes.add(
                base.replace(
                    terme_present,
                    canonique_norm,
                )
            )

    # Un set ne garantit aucun ordre entre deux chaines de meme longueur.
    # Avec l'ancien plafond de huit, une variante valide pouvait donc etre
    # presente ou absente selon le processus Python (et differer entre le TSE
    # et l'instance). Le tri secondaire lexical rend le resultat reproductible
    # et le plafond elargi conserve les flexions d'un groupe usuel sans ouvrir
    # une recherche combinatoire.
    return sorted(
        variantes,
        key=lambda variante: (-len(variante), variante),
    )[:16]


def _equivalence_synonyme_declaree_confirme_candidat(
    texte_source: str,
    candidat: dict[str, Any],
    synonymes: dict[str, list[str]],
) -> tuple[bool, str]:
    """Confirme une equivalence explicite sans abaisser le product gate.

    Les variantes ASR servent tres largement a *chercher* des candidats. Elles
    ne doivent pas, a elles seules, rendre une ligne commandable. Ce predicate
    est volontairement beaucoup plus strict : il faut une expression complete
    explicitement declaree dans le dictionnaire de synonymes et un rapprochement
    fort entre la forme canonique et le libelle de l'article retenu.

    Cela permet notamment de ne pas perdre une ligne deja correctement resolue
    apres normalisation lexicale, tout en excluant les simples ressemblances sur
    un mot isole, le fuzzy global et les articles hors famille.
    """
    source = normaliser_texte(texte_source)
    libelle = normaliser_texte(str(candidat.get("libelle_normalise") or ""))
    if not source or not libelle:
        return False, ""

    source_borne = f" {source} "
    for canonique, aliases in (synonymes or {}).items():
        canonique_norm = normaliser_texte(str(canonique or ""))
        tokens_canonique = [
            token for token in _tokens_produit(canonique_norm)
            if len(token) >= 3 and not token.isdigit()
        ]
        # Un canonique monosyllabique/generique ne peut jamais donner cette
        # preuve forte. La selection habituelle reste alors responsable.
        if len(tokens_canonique) < 2:
            continue
        if fuzz.token_set_ratio(canonique_norm, libelle) < 88.0:
            continue

        for alias in aliases or []:
            alias_norm = normaliser_texte(str(alias or ""))
            tokens_alias = [
                token for token in _tokens_produit(alias_norm)
                if len(token) >= 3 and not token.isdigit()
            ]
            # Une expression de deux mots utiles minimum doit etre prononcee
            # integralement. Une sous-chaine courte comme "huile" ne suffit
            # donc pas a faire entrer une ligne dans la commande.
            if (
                len(tokens_alias) >= 2
                and f" {alias_norm} " in source_borne
            ):
                return True, (
                    "equivalence_synonyme_declaree_confirmee="
                    f"{alias_norm}"
                )

    return False, ""


def _rechercher_dans_pool(
    texte_mention: str,
    unite_mention: str | None,
    produits_pool: list[dict[str, Any]],
    dans_cadencier_client: bool,
    source_recherche: str,
    exclusions: list[str] | None = None,
    texte_semantique: str | None = None,
) -> list[dict[str, Any]]:
    candidats: list[dict[str, Any]] = []

    produits_a_evaluer = produits_pool
    if len(produits_pool) > 1_000:
        cle_pool = id(produits_pool)
        entree_cache = _POOL_LIBELLES_CACHE.get(cle_pool)
        if entree_cache is None or entree_cache[0] != len(produits_pool):
            entree_cache = (
                len(produits_pool),
                [
                    str(produit.get("libelle_normalise") or "")
                    for produit in produits_pool
                ],
            )
            _POOL_LIBELLES_CACHE[cle_pool] = entree_cache
        correspondances = process.extract(
            normaliser_texte(texte_mention),
            entree_cache[1],
            scorer=fuzz.token_set_ratio,
            score_cutoff=15.0,
            limit=500,
        )
        produits_a_evaluer = [
            produits_pool[index]
            for _, _, index in correspondances
        ]

    for produit in produits_a_evaluer:
        libelle_normalise = produit["libelle_normalise"]

        score = _score_correspondance_produit(
            texte_mention=texte_mention,
            texte_libelle=libelle_normalise,
            unite_mention=unite_mention,
            texte_semantique=texte_semantique,
        )
        incompatibilites = _incompatibilites_semantiques(
            texte_semantique if texte_semantique is not None else texte_mention,
            libelle_normalise,
            exclusions,
        )
        incompatibilites_variante = _incompatibilites_semantiques(
            texte_mention,
            libelle_normalise,
            exclusions,
        )

        bonus_cadencier = (
            12.0 if dans_cadencier_client else 0.0
        )
        score_global = round(
            min(100.0, score + bonus_cadencier),
            2,
        )

        candidats.append(
            {
                "code_article": produit["code_article"],
                "libelle_article": produit["libelle_article"],
                "libelle_normalise": libelle_normalise,
                "score_texte": score,
                "score_global": score_global,
                "dans_cadencier_client": dans_cadencier_client,
                "source_recherche": source_recherche,
                "texte_recherche": normaliser_texte(texte_mention),
                "variante_semantiquement_compatible": not incompatibilites_variante,
                "source_article": produit.get("source_article", "historique_client"),
                "unite_vente": produit.get("unite_vente", ""),
                "prix": produit.get("prix"),
                "nb_ventes_article_total": int(
                    produit.get(
                        "nb_ventes_article_total", 0
                    )
                ),
                "nb_ventes_article_recentes": int(
                    produit.get(
                        "nb_ventes_article_recentes", 0
                    )
                ),
                "derniere_vente_article_iso": str(
                    produit.get(
                        "derniere_vente_article_iso", ""
                    )
                ),
                "derniere_vente_article_ordinal": int(
                    produit.get(
                        "derniere_vente_article_ordinal",
                        -1,
                    )
                ),
                "quantite_habituelle_commande": float(
                    produit.get(
                        "quantite_habituelle_commande",
                        0.0,
                    )
                    or 0.0
                ),
                "volume_historique_total": float(
                    produit.get("volume_historique_total", 0.0)
                    or 0.0
                ),
                "ratio_net_par_unite": float(
                    produit.get(
                        "ratio_net_par_unite",
                        0.0,
                    )
                    or 0.0
                ),
                "stock_disponible": None,
                "semantiquement_compatible": not incompatibilites,
                "raisons": [
                    f"source={source_recherche}",
                    f"score_texte={score}",
                    *(
                        f"incompatibilite={raison}"
                        for raison in incompatibilites
                    ),
                ],
            }
        )

    return candidats


def _candidat_commandable(candidat: dict[str, Any]) -> bool:
    return (
        "***" not in str(candidat.get("libelle_article") or "")
        and "***" not in str(candidat.get("libelle_normalise") or "")
        and candidat.get("semantiquement_compatible", True)
        and (
            _prix_exploitable(candidat) is not None
            or str(candidat.get("code_article") or "")
            in _charger_references_controle()
            or candidat.get("source_article")
            in {
                "referentiel_articles",
                "historique_client_pretest",
            }
            or (
                float(candidat.get("score_texte") or 0.0) >= 80.0
                and int(
                    candidat.get(
                        "derniere_vente_article_ordinal",
                        -1,
                    )
                    or -1
                )
                >= 739700
                and int(
                    candidat.get(
                        "nb_ventes_article_total",
                        0,
                    )
                    or 0
                )
                > 0
            )
            or (
                float(candidat.get("score_texte") or 0.0) >= 50.0
                and float(candidat.get("score_conditionnement") or 0.0) >= 55.0
                and int(candidat.get("derniere_vente_article_ordinal", -1) or -1)
                >= 739760
                and int(candidat.get("nb_ventes_article_total", 0) or 0) >= 5
                and any(
                    str(raison).startswith("preference_")
                    for raison in candidat.get("raisons", [])
                )
            )
        )
    )


def _prix_exploitable(
    candidat: dict[str, Any],
) -> float | None:
    prix = candidat.get("prix")
    if not isinstance(prix, (int, float)):
        return None
    prix = float(prix)
    if prix <= 0:
        return None
    return prix


def _score_selection_ponderee(candidat: dict[str, Any]) -> float:
    """Combine pertinence, cadencier, conditionnement et usage sans vérité ES."""
    # Un grammage/volume explicitement dicte doit réellement départager deux
    # variantes du même produit. En son absence, le conditionnement reste un
    # signal secondaire : il ne doit pas faire gagner un autre produit dont le
    # texte correspond moins bien simplement parce qu'il est plus proche des
    # habitudes historiques du client.
    marqueurs_conditionnement_explicite = (
        "preference_dimension_",
        "preference_conditionnement_",
        "preference_volume_unitaire_",
        "conversion_depuis_kg",
        "conversion_depuis_litre",
    )
    conditionnement_explicitement_demande = any(
        str(raison).startswith(marqueurs_conditionnement_explicite)
        for raison in candidat.get("raisons", [])
    )
    poids_conditionnement = (
        0.7 if conditionnement_explicitement_demande else 0.05
    )
    recence = max(
        0,
        int(
            candidat.get(
                "derniere_vente_article_ordinal",
                -1,
            )
            or -1
        )
        - 739700,
    )
    source_recherche = candidat.get("source_recherche", "")
    bonus_source = 0.0
    if source_recherche == "cadencier_client":
        bonus_source = 80.0
    elif source_recherche == "catalogue_global":
        bonus_source = 30.0
    elif source_recherche == "catalogue_reappro":
        bonus_source = -30.0

    return round(
        float(candidat.get("score_texte", 0.0))
        + float(candidat.get("score_attribut_semantique", 0.0))
        + float(candidat.get("score_conditionnement_physique_sur", 0.0))
        + float(candidat.get("bonus_historique_compatible", 0.0))
        + float(candidat.get("bonus_reappro_fallback", 0.0))
        + bonus_source
        + poids_conditionnement * float(candidat.get("score_conditionnement", 0.0))
        + 1.5 * math.log1p(int(candidat.get("nb_ventes_article_total", 0)))
        + 3.5 * math.log1p(int(candidat.get("nb_ventes_article_recentes", 0)))
        + 0.06 * recence
        + float(candidat.get("bonus_volume_historique", 0.0))
        + 4.0 * (candidat.get("source_article") == "referentiel_articles"),
        4,
    )


def _parfums_dessert_glace_explicites(texte: str) -> set[str]:
    tokens = set(_tokens_produit(texte))
    marqueurs_famille = {
        "glace", "glaces", "glacee", "glacees", "sorbet", "sorbets",
    }
    if not (tokens & marqueurs_famille):
        return set()
    aliases = set(PARFUMS_DESSERTS_GLACES_CANONIQUES)
    return {
        PARFUMS_DESSERTS_GLACES_CANONIQUES.get(token, token)
        for token in tokens
        if token in PARFUMS_DESSERTS_GLACES or token in aliases
    }


def _candidat_parfum_glace_explicitement_prononce(
    texte_source: str,
    selection: dict[str, Any],
    candidats_selection: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Corrige uniquement un gagnant historique glacé explicitement contredit.

    Cette règle ne génère, ne supprime et ne rend commandable aucun candidat.
    Elle ne peut agir que sur deux candidats déjà très fortement reconnus dans
    la même famille, afin que le parfum prononcé précède le prior cadencier.
    """
    if not business_rule_enabled("parfum_glace_explicite_prioritaire"):
        return None

    demandes = _parfums_dessert_glace_explicites(texte_source)
    parfums_selection = _parfums_dessert_glace_explicites(
        str(
            selection.get("libelle_normalise")
            or selection.get("libelle_article")
            or ""
        )
    )
    if (
        not demandes
        or not parfums_selection
        or demandes & parfums_selection
        or not selection.get("dans_cadencier_client")
    ):
        return None

    score_texte_selection = float(selection.get("score_texte", 0.0))
    compatibles = [
        candidat
        for candidat in candidats_selection
        if candidat is not selection
        and _candidat_commandable(candidat)
        and demandes
        & _parfums_dessert_glace_explicites(
            str(
                candidat.get("libelle_normalise")
                or candidat.get("libelle_article")
                or ""
            )
        )
        and float(candidat.get("score_texte", 0.0)) >= 98.0
        and float(candidat.get("score_global", 0.0)) >= 90.0
        and float(candidat.get("score_texte", 0.0))
        >= score_texte_selection + 15.0
    ]
    if not compatibles:
        return None

    compatibles.sort(
        key=lambda candidat: (
            float(candidat.get("score_texte", 0.0)),
            float(candidat.get("score_selection", 0.0)),
            int(candidat.get("nb_ventes_article_recentes", 0)),
            int(candidat.get("nb_ventes_article_total", 0)),
        ),
        reverse=True,
    )
    return compatibles[0]


def _cle_ventes_article_client(
    candidat: dict[str, Any],
) -> tuple[float, int, int, int, float, float]:
    prix = _prix_exploitable(candidat)
    return (
        float(candidat.get("score_conditionnement", 0.0)),
        int(candidat.get("nb_ventes_article_total", 0)),
        int(candidat.get("nb_ventes_article_recentes", 0)),
        int(
            candidat.get(
                "derniere_vente_article_ordinal", -1
            )
        ),
        -(prix if prix is not None else 999999.0),
        float(candidat.get("score_global", 0.0)),
    )


def _appliquer_bonus_volume_historique(
    candidats: list[dict[str, Any]],
) -> None:
    """Departage des variantes proches par volume reel deja livre.

    Le volume n'est jamais un substitut a la reconnaissance du produit : il
    ne s'applique qu'a des candidats du cadencier, tous deux tres proches du
    texte, lorsqu'un volume/poids a ete explicitement prononce.
    """
    candidats_eligibles = [
        candidat
        for candidat in candidats
        if candidat.get("dans_cadencier_client")
        and candidat.get("volume_demande_explicite")
        and float(candidat.get("score_texte", 0.0)) >= 80.0
        and float(candidat.get("volume_historique_total", 0.0)) > 0.0
    ]
    if len(candidats_eligibles) < 2:
        return

    meilleur_score_texte = max(
        float(candidat.get("score_texte", 0.0))
        for candidat in candidats_eligibles
    )
    # On ne compare le volume que pour de vraies variantes lexicalement
    # voisines, jamais pour faire remonter un article hors sujet.
    candidats_proches = [
        candidat
        for candidat in candidats_eligibles
        if float(candidat.get("score_texte", 0.0))
        >= meilleur_score_texte - 8.0
    ]
    if len(candidats_proches) < 2:
        return

    for candidat in candidats_proches:
        volume = float(candidat["volume_historique_total"])
        candidat["bonus_volume_historique"] = round(
            6.0 * math.log1p(volume),
            4,
        )
        candidat.setdefault("raisons", []).append(
            "volume_historique_client_departage"
        )


@lru_cache(maxsize=100_000)
def _signatures_phonetiques_bornees(expression: str) -> frozenset[str]:
    """Signatures françaises utilisées uniquement dans un cadencier client.

    Ce n'est pas un générateur de candidats : il compare seulement les
    articles déjà chargés pour le client, après échec des preuves lexicales.
    """
    valeur = normaliser_texte(expression)
    valeur = re.sub(r"\b(?:de|du|des|d|la|le|les)\b", " ", valeur)
    valeur = re.sub(r"\s+", "", valeur)
    if len(valeur) < 4:
        return frozenset({valeur}) if valeur else frozenset()

    phon = valeur
    phon = phon.replace("eaux", "o").replace("eau", "o")
    phon = phon.replace("aux", "o").replace("au", "o")
    phon = phon.replace("ou", "u").replace("ill", "i")
    phon = phon.replace("ph", "f").replace("qu", "k")
    phon = re.sub(r"c(?=[eiy])", "s", phon)
    phon = re.sub(r"g(?=[eiy])", "j", phon)
    phon = phon.replace("ck", "k").replace("z", "s")
    phon = phon.replace("y", "i").replace("h", "")
    phon = re.sub(r"(?:es|e|s)$", "", phon)
    phon = re.sub(r"(.)\1+", r"\1", phon)
    consonnes = re.sub(r"[aeiou]", "", phon)
    formes = {valeur, phon}
    if len(consonnes) >= 3:
        formes.add(consonnes)
    return frozenset(forme for forme in formes if forme)


def _score_phonetique_borne(source: str, cible: str) -> float:
    return max(
        (
            float(fuzz.ratio(forme_source, forme_cible))
            for forme_source in _signatures_phonetiques_bornees(source)
            for forme_cible in _signatures_phonetiques_bornees(cible)
        ),
        default=0.0,
    )


def _selectionner_meilleur_candidat(
    candidats: list[dict[str, Any]],
    texte_source: str = "",
) -> tuple[dict[str, Any] | None, list[str]]:
    if not candidats:
        return None, []

    candidats_commandables = [
        candidat for candidat in candidats if _candidat_commandable(candidat)
    ]
    if not candidats_commandables:
        return None, ["candidat_catalogue_prix_zero"]

    codes_prononces = [
        candidat
        for candidat in candidats_commandables
        if candidat.get("code_article_prononce_exact")
    ]
    if len(codes_prononces) == 1:
        selection = dict(codes_prononces[0])
        selection["score_selection"] = 1000.0
        selection["marge_selection_ponderee"] = 999.0
        selection["regle_selection"] = "code_article_prononce_exact"
        selection.setdefault("raisons", []).extend([
            "code_article_prononce_correspondance_unique",
            "regle_selection=code_article_prononce_exact",
        ])
        return selection, []

    # Le cadencier et l'historique sont des signaux de departage, pas une
    # preuve que l'article repond au texte. Lorsqu'une correspondance
    # lexicale forte existe, les candidats trop eloignes ne peuvent donc pas
    # etre propulses par leurs seuls bonus d'usage. En l'absence d'alternative
    # forte, on conserve le comportement habituel pour les transcriptions ASR
    # difficiles.
    meilleur_score_texte = max(
        float(candidat.get("score_texte", 0.0))
        for candidat in candidats_commandables
    )
    candidats_selection = candidats_commandables
    if meilleur_score_texte >= 80.0:
        seuil_plausibilite = 35.0
        candidats_selection = [
            candidat
            for candidat in candidats_commandables
            if float(candidat.get("score_texte", 0.0)) >= seuil_plausibilite
        ]
        for candidat in candidats_commandables:
            if candidat not in candidats_selection:
                candidat.setdefault("raisons", []).append(
                    "plausibilite_lexicale_insuffisante_pour_departage"
                )

    _appliquer_bonus_volume_historique(candidats_selection)
    for candidat in candidats_selection:
        candidat["score_selection"] = _score_selection_ponderee(candidat)
    candidats_selection.sort(
        key=lambda candidat: (
            float(candidat["score_selection"]),
            float(candidat.get("score_texte", 0.0)),
            int(candidat.get("nb_ventes_article_recentes", 0)),
            int(candidat.get("nb_ventes_article_total", 0)),
        ),
        reverse=True,
    )
    selection = candidats_selection[0]

    # Garde-fou minimal contre le prior cadencier hors famille : on ne
    # remplace le gagnant historique que lorsqu'il ne partage absolument
    # aucun mot produit distinctif avec la mention et qu'un concurrent en
    # partage au moins un. Des candidats d'une meme famille restent donc
    # departages exactement comme avant par l'usage client.
    tokens_forme_generiques = {
        "bloc", "bouchee", "cube", "demi", "emince", "emincee",
        "filet", "lamelle", "liquide", "morceau", "pain", "poudre",
        "quart", "rond", "stick",
    }
    tokens_generiques = (
        TOKENS_CONDITIONNEMENT_SANS_PRODUIT
        | QUALIFICATIFS_PRODUIT
        | set(UNITES_EQUIVALENCES)
        | tokens_forme_generiques
    )
    tokens_distinctifs = [
        token
        for token in dict.fromkeys(_tokens_produit(texte_source))
        if token not in tokens_generiques
        and not token.isdigit()
        and not re.fullmatch(r"\d+(?:[.,]\d+)?[a-z]*", token)
    ]

    def ancrages(candidat: dict[str, Any]) -> set[str]:
        tokens_libelle = _tokens_produit(
            str(
                candidat.get("libelle_normalise")
                or candidat.get("libelle_article")
                or ""
            )
        )
        return {
            token
            for token in tokens_distinctifs
            if any(
                _score_token_produit(token, token_libelle) >= 90.0
                for token_libelle in tokens_libelle
            )
        }

    def ancrages_explicites(candidat: dict[str, Any]) -> set[str]:
        """Ancrages source, y compris une forme explicitement prononcee.

        Les formes sont ecartees du prior historique ordinaire car elles sont
        souvent generiques. Pour le secours referentiel, en revanche, deux
        ancrages dont une forme (``pistache hachee``) constituent une preuve
        suffisamment precise et restent bien plus stricts qu'un seul mot.
        """
        return core_anchors(
            _tokens_produit(texte_source),
            _tokens_produit(
                str(
                    candidat.get("libelle_normalise")
                    or candidat.get("libelle_article")
                    or ""
                )
            ),
            _score_token_produit,
        )

    tokens_phonetiques_faibles = (
        tokens_generiques
        | TOKENS_SANS_NOYAU_PRODUIT
        | QUALIFICATIFS_PRODUIT
        | FORMES_DISCOURS_COMMANDE
        | NOMS_DISCOURS_COMMANDE
        | TOKENS_CALENDRIER
    )

    def tokens_phonetiques(texte: str) -> list[str]:
        return [
            token
            for token in _tokens_produit(texte)
            if len(token) >= 4
            and token not in tokens_phonetiques_faibles
            and not token.isdigit()
        ]

    tokens_phonetiques_source = tokens_phonetiques(texte_source)
    tokens_phonetiques_source_courts = [
        token
        for token in _tokens_produit(texte_source)
        if len(token) >= 2
        and token not in tokens_phonetiques_faibles
        and not token.isdigit()
    ]

    def score_phonetique_candidat(
        candidat: dict[str, Any],
        tailles_source: tuple[int, ...],
    ) -> float:
        if not candidat.get("dans_cadencier_client"):
            return 0.0
        tokens_candidat = tokens_phonetiques(
            str(
                candidat.get("libelle_normalise")
                or candidat.get("libelle_article")
                or ""
            )
        )
        meilleur = 0.0
        source_tokens = (
            tokens_phonetiques_source_courts
            if any(taille >= 2 for taille in tailles_source)
            else tokens_phonetiques_source
        )
        for taille in tailles_source:
            if taille > len(source_tokens):
                continue
            for index in range(len(source_tokens) - taille + 1):
                source = " ".join(
                    source_tokens[index:index + taille]
                )
                for cible in tokens_candidat:
                    if normaliser_texte(source) == normaliser_texte(cible):
                        continue
                    meilleur = max(
                        meilleur,
                        _score_phonetique_borne(source, cible),
                    )
        return meilleur

    ancrages_selection = ancrages(selection)
    if tokens_distinctifs and not ancrages_selection:
        candidats_ancres = [
            candidat
            for candidat in candidats_selection
            if ancrages(candidat)
            and candidat.get("dans_cadencier_client")
            and float(candidat.get("score_texte", 0.0)) >= 75.0
        ]
        if candidats_ancres:
            selection.setdefault("raisons", []).append(
                "prior_cadencier_sans_ancrage_produit_ecarte"
            )
            selection = candidats_ancres[0]
            selection.setdefault("raisons", []).append(
                "selection_par_ancrage_produit_discriminant"
            )

        # Un article ayant au moins deux ancrages explicites est une preuve
        # lexicale plus solide qu'un article du cadencier qui n'en a aucun.
        # C'est notamment le cas quand le cadencier ne contient pas la
        # variante demandee mais que celle-ci existe dans le referentiel
        # article autorise. Le seuil reste volontairement haut et ne donne
        # jamais un avantage a une correspondance sur un seul mot vague.
        if business_rule_enabled("references_controle_fallback"):
            candidats_deux_ancrages = [
                candidat
                for candidat in candidats_selection
                if len(ancrages_explicites(candidat)) >= 2
                and float(candidat.get("score_texte", 0.0)) >= 65.0
            ]
            if candidats_deux_ancrages:
                candidats_deux_ancrages.sort(
                    key=lambda candidat: (
                        len(ancrages_explicites(candidat)),
                        float(candidat.get("score_texte", 0.0)),
                        float(candidat.get("score_selection", 0.0)),
                    ),
                    reverse=True,
                )
                selection.setdefault("raisons", []).append(
                    "prior_cadencier_sans_ancrage_produit_ecarte"
                )
                selection = candidats_deux_ancrages[0]
                selection.setdefault("raisons", []).append(
                    "selection_deux_ancrages_produit_explicites"
                )

        # Un mot produit long, prononce exactement et absent du gagnant
        # historique, est une preuve plus forte que le simple prior du
        # cadencier. Ce secours reste volontairement etroit : correspondance
        # exacte (aucune phonétique globale), mot d'au moins 7 caracteres,
        # candidat nettement meilleur lexicalement et choix unique. Il rend
        # visibles des articles comme ``speculoos`` absents du cadencier sans
        # permettre a un conditionnement ou a l'historique de creer une
        # famille produit.
        candidats_exact_distinctif: list[tuple[dict[str, Any], set[str]]] = []
        tokens_source_exacts = set(_tokens_produit(texte_source))
        for candidat in candidats_selection:
            tokens_candidat = set(
                _tokens_produit(
                    str(
                        candidat.get("libelle_normalise")
                        or candidat.get("libelle_article")
                        or ""
                    )
                )
            )
            exacts = {
                token
                for token in tokens_source_exacts & tokens_candidat
                if len(token) >= 7
                and token not in tokens_generiques
                and token not in TOKENS_SANS_NOYAU_PRODUIT
                and not token.isdigit()
            }
            if (
                exacts
                and float(candidat.get("score_texte", 0.0)) >= 50.0
                and float(candidat.get("score_texte", 0.0))
                >= float(selection.get("score_texte", 0.0)) + 20.0
            ):
                candidats_exact_distinctif.append((candidat, exacts))

        if len(candidats_exact_distinctif) == 1:
            candidat_exact, exacts = candidats_exact_distinctif[0]
            selection.setdefault("raisons", []).append(
                "prior_historique_sans_noyau_exact_ecarte"
            )
            score_prior = float(selection.get("score_selection", 0.0))
            selection = candidat_exact
            # La marge encode ici la priorite du noyau explicite sur le prior
            # historique; elle reste locale a cette selection et ne modifie
            # pas le score lexical brut.
            selection["score_selection"] = max(
                float(selection.get("score_selection", 0.0)),
                score_prior + 12.0,
            )
            selection.setdefault("raisons", []).extend([
                "selection_noyau_exact_distinctif_unique",
                "noyau_exact_distinctif=" + ",".join(sorted(exacts)),
            ])

        # Dernier secours ASR, limité au cadencier : un mot long très proche
        # phonétiquement peut remplacer un gagnant sans aucune ancre produit.
        # Une marge entre le premier et le second évite tout fuzzy global.
        if (
            not ancrages(selection)
            and float(selection.get("score_texte", 0.0)) < 75.0
        ):
            scores_simples = sorted(
                (
                    (score_phonetique_candidat(candidat, (1,)), candidat)
                    for candidat in candidats_selection
                    if candidat.get("dans_cadencier_client")
                ),
                key=lambda item: item[0],
                reverse=True,
            )
            if scores_simples:
                score_premier, candidat_premier = scores_simples[0]
                score_second = scores_simples[1][0] if len(scores_simples) > 1 else 0.0
                if score_premier >= 86.0 and score_premier - score_second >= 7.0:
                    score_prior = float(selection.get("score_selection", 0.0))
                    selection = candidat_premier
                    selection["score_selection"] = max(
                        float(selection.get("score_selection", 0.0)),
                        score_prior + 12.0,
                    )
                    selection.setdefault("raisons", []).append(
                        f"selection_phonetique_cadencier_bornee={score_premier:.2f}"
                    )
                    selection["noyau_phonetique_cadencier_prouve"] = True

    # Une coupure Whisper de deux mots peut reconstituer exactement un noyau
    # long (``souris mi`` -> ``surimi``). Cette preuve composée peut battre
    # un homonyme portant un seul des fragments, mais uniquement dans le
    # cadencier et avec une marge élevée.
    scores_composes = sorted(
        (
            (score_phonetique_candidat(candidat, (2,)), candidat)
            for candidat in candidats_selection
            if candidat.get("dans_cadencier_client")
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if scores_composes:
        score_premier, candidat_premier = scores_composes[0]
        score_second = scores_composes[1][0] if len(scores_composes) > 1 else 0.0
        if (
            candidat_premier.get("code_article")
            != selection.get("code_article")
            and score_premier >= 92.0
            and score_premier - score_second >= 6.0
            and len(ancrages(selection)) <= 1
        ):
            score_prior = float(selection.get("score_selection", 0.0))
            selection = candidat_premier
            selection["score_selection"] = max(
                float(selection.get("score_selection", 0.0)),
                score_prior + 12.0,
            )
            selection.setdefault("raisons", []).append(
                f"selection_phonetique_composee_cadencier={score_premier:.2f}"
            )
            selection["noyau_phonetique_cadencier_prouve"] = True

    # Un bonus de variante/attribut Réapro ne peut renverser un autre noyau
    # produit exact, long et explicitement prononcé, présent dans le
    # cadencier. Cette priorité s'applique au noyau (pas à l'historique) et
    # reste indépendante de toute référence particulière.
    if float(selection.get("bonus_reappro_fallback", 0.0)) > 0.0:
        tokens_source_exacts_longs = {
            token
            for token in _tokens_produit(texte_source)
            if len(token) >= 7
            and token not in tokens_generiques
            and token not in TOKENS_SANS_NOYAU_PRODUIT
        }
        tokens_selection_actuelle = set(
            _tokens_produit(
                str(
                    selection.get("libelle_normalise")
                    or selection.get("libelle_article")
                    or ""
                )
            )
        )
        ancres_non_expliquees = (
            tokens_source_exacts_longs - tokens_selection_actuelle
        )
        candidats_cadencier_noyau_long = [
            candidat
            for candidat in candidats_selection
            if candidat.get("dans_cadencier_client")
            and candidat.get("semantiquement_compatible", True)
            and float(candidat.get("score_texte", 0.0)) >= 50.0
            and ancres_non_expliquees
            & set(
                _tokens_produit(
                    str(candidat.get("libelle_normalise") or "")
                )
            )
        ]
        if candidats_cadencier_noyau_long:
            candidats_cadencier_noyau_long.sort(
                key=lambda candidat: (
                    float(candidat.get("score_texte", 0.0)),
                    float(candidat.get("score_selection", 0.0)),
                ),
                reverse=True,
            )
            score_prior = float(selection.get("score_selection", 0.0))
            selection = candidats_cadencier_noyau_long[0]
            selection["score_selection"] = max(
                float(selection.get("score_selection", 0.0)),
                score_prior + 12.0,
            )
            selection.setdefault("raisons", []).append(
                "noyau_exact_long_cadencier_prioritaire_sur_attribut_reappro"
            )

    meilleur = dict(selection)
    if len(candidats_selection) == 1:
        meilleur["regle_selection"] = (
            "cadencier_unique"
            if meilleur.get("dans_cadencier_client")
            else "catalogue_unique"
        )
    else:
        meilleur["regle_selection"] = (
            "cadencier_plus_vendu"
            if meilleur.get("dans_cadencier_client")
            else "catalogue_score_frequence"
        )
    autres = [
        candidat
        for candidat in candidats_selection
        if candidat.get("code_article") != selection.get("code_article")
    ]
    second = autres[0] if autres else None
    meilleur["marge_selection_ponderee"] = round(
        float(meilleur["score_selection"])
        - float(second["score_selection"] if second else 0.0),
        4,
    )
    return meilleur, []


def _indexer_articles_par_code_prononce(
    produits_client: list[dict[str, Any]],
    catalogue_global: list[dict[str, Any]],
    catalogue_reappro: list[dict[str, Any]] | None,
) -> tuple[
    dict[str, tuple[dict[str, Any], str, bool]],
    dict[str, set[str]],
]:
    """Indexe uniquement les codes numériques des données de production."""
    articles: dict[str, tuple[dict[str, Any], str, bool]] = {}
    for pool, source, dans_cadencier in (
        (produits_client, "cadencier_client", True),
        (catalogue_global, "catalogue_global", False),
        (catalogue_reappro or [], "catalogue_reappro", False),
    ):
        for produit in pool:
            code = str(produit.get("code_article") or "").strip().upper()
            if not re.fullmatch(r"\d+", code):
                continue
            # Le premier pool est volontairement prioritaire : les mêmes
            # métadonnées client sont ainsi conservées si l'article figure
            # également dans le catalogue global.
            articles.setdefault(code, (produit, source, dans_cadencier))

    codes_par_partie_significative: dict[str, set[str]] = {}
    for code in articles:
        significatif = code.lstrip("0") or "0"
        codes_par_partie_significative.setdefault(
            significatif, set()
        ).add(code)
    return articles, codes_par_partie_significative


def _resoudre_code_article_prononce(
    texte: str,
    articles: dict[str, tuple[dict[str, Any], str, bool]],
    codes_par_partie_significative: dict[str, set[str]],
) -> tuple[str, str, bool] | None:
    """Résout un code complet ou privé de ses zéros initiaux, si unique."""
    correspondances: list[tuple[int, str, str, bool]] = []
    for chiffres, explicite in _candidats_numeriques_code_article(texte):
        codes: set[str]
        if chiffres in articles:
            codes = {chiffres}
        else:
            significatif = chiffres.lstrip("0") or "0"
            codes = codes_par_partie_significative.get(significatif, set())
        if len(codes) != 1:
            continue
        code = next(iter(codes))
        correspondances.append((len(chiffres), code, chiffres, explicite))

    if not correspondances:
        return None
    longueur_max = max(item[0] for item in correspondances)
    meilleures = [item for item in correspondances if item[0] == longueur_max]
    codes = {item[1] for item in meilleures}
    if len(codes) != 1:
        return None
    _, code, entendu, explicite = meilleures[0]
    return code, entendu, explicite

def chercher_produits(
    mentions: list[dict[str, Any]],
    produits_client: list[dict[str, Any]],
    catalogue_global: list[dict[str, Any]],
    synonymes: dict[str, list[str]],
    catalogue_reappro: list[dict[str, Any]] = None,
    limite: int = 50,
) -> list[dict[str, Any]]:
    resultats: list[dict[str, Any]] = []
    articles_par_code, codes_par_partie_significative = (
        _indexer_articles_par_code_prononce(
            produits_client,
            catalogue_global,
            catalogue_reappro,
        )
    )

    for mention in mentions:
        texte_produit = mention["produit_normalise"]
        # Les variantes et synonymes peuvent contenir des formes incompatibles
        # entre elles. Elles servent uniquement a la recherche : les regles
        # semantiques doivent rester ancrees dans la formulation extraite de
        # l'audio.
        texte_semantique = normaliser_texte(texte_produit)
        alternatives_semantiques = [
            normaliser_texte(str(item))
            for item in (mention.get("alternatives_produit") or [])
            if normaliser_texte(str(item))
        ] or [texte_semantique]
        unite_mention = mention.get("unite_principale")
        code_prononce = (
            _resoudre_code_article_prononce(
                str(mention.get("texte_source") or texte_semantique),
                articles_par_code,
                codes_par_partie_significative,
            )
            if business_rule_enabled("code_article_prononce_prioritaire")
            else None
        )
        # Une référence exacte et unique rend le fuzzy inutile pour cette
        # mention. L'historique ne peut donc pas réintroduire un article
        # lexicalement proche mais différent.
        variantes_recherche = (
            []
            if code_prononce is not None
            else _generer_variantes_recherche(
                produit_normalise=texte_produit,
                synonymes=synonymes,
            )
        )
        if code_prononce is None and len(alternatives_semantiques) > 1:
            for alternative in alternatives_semantiques:
                for variante in _generer_variantes_recherche(
                    produit_normalise=alternative,
                    synonymes=synonymes,
                ):
                    if variante not in variantes_recherche:
                        variantes_recherche.append(variante)
        texte_variantes = " ".join(variantes_recherche)

        candidats_par_code: dict[str, dict[str, Any]] = {}

        def ajouter_candidats(
            candidats: list[dict[str, Any]],
        ) -> None:
            for candidat in candidats:
                code = candidat["code_article"]
                courant = candidats_par_code.get(code)

                if courant is None:
                    candidats_par_code[code] = candidat
                else:
                    best_source = courant.get("source_recherche", "")
                    if candidat.get("source_recherche") == "cadencier_client" or (candidat.get("source_recherche") == "catalogue_global" and best_source != "cadencier_client"):
                        best_source = candidat.get("source_recherche", "")
                    
                    if candidat.get("dans_cadencier_client"):
                        courant["dans_cadencier_client"] = True
                    
                    courant["source_recherche"] = best_source

                    meilleure_variante_semantique = bool(
                        candidat.get("variante_semantiquement_compatible")
                        and not courant.get("variante_semantiquement_compatible")
                    )
                    if (
                        candidat["score_global"] > courant["score_global"]
                        or meilleure_variante_semantique
                    ):
                        courant["score_global"] = candidat["score_global"]
                        courant["score_texte"] = candidat["score_texte"]
                        courant["texte_recherche"] = candidat.get("texte_recherche")
                        courant["variante_semantiquement_compatible"] = candidat.get(
                            "variante_semantiquement_compatible", False
                        )
                        courant["texte_semantique_source"] = candidat.get(
                            "texte_semantique_source", texte_semantique
                        )
                        # We do NOT replace courant with candidat!
                        # This preserves prix, source_article, and all sales history.

        def semantique_de_variante(variante: str) -> str:
            variante_norm = normaliser_texte(variante)
            return max(
                alternatives_semantiques,
                key=lambda alternative: fuzz.token_set_ratio(
                    variante_norm, alternative
                ),
            )

        def rechercher_variante(
            variante: str,
            pool: list[dict[str, Any]],
            *,
            dans_cadencier_client: bool,
            source_recherche: str,
        ) -> list[dict[str, Any]]:
            source_semantique = semantique_de_variante(variante)
            trouves = _rechercher_dans_pool(
                texte_mention=variante,
                unite_mention=unite_mention,
                produits_pool=pool,
                dans_cadencier_client=dans_cadencier_client,
                source_recherche=source_recherche,
                exclusions=mention.get("exclusions_produit", []),
                texte_semantique=source_semantique,
            )
            for candidat in trouves:
                candidat["texte_semantique_source"] = source_semantique
            return trouves

        for variante in variantes_recherche:
            if produits_client:
                ajouter_candidats(
                    rechercher_variante(
                        variante,
                        produits_client,
                        dans_cadencier_client=True,
                        source_recherche="cadencier_client",
                    )
                )

        for candidat in candidats_par_code.values():
            incompatibilites_source = _incompatibilites_semantiques(
                str(candidat.get("texte_semantique_source") or texte_semantique),
                str(candidat.get("libelle_normalise") or ""),
                mention.get("exclusions_produit", []),
            )
            texte_recherche = normaliser_texte(
                str(candidat.get("texte_recherche") or "")
            )
            if (
                texte_recherche
                and texte_recherche != texte_semantique
                and candidat.get("variante_semantiquement_compatible")
            ):
                incompatibilites_source = [
                    raison
                    for raison in incompatibilites_source
                    if raison not in {
                        "noyau_produit_compose_contradictoire",
                        "noyau_produit_principal_contradictoire",
                    }
                ]
                candidat.setdefault("raisons", []).append(
                    "equivalence_lexicale_autorisee_preserve_noyau"
                )
            candidat["semantiquement_compatible"] = not incompatibilites_source

        # Le catalogue global est toujours interroge en complement du
        # cadencier client, meme quand celui-ci a deja un score parfait
        # (100). Un score de 100 mesure une correspondance textuelle/
        # frequence forte avec UN article du cadencier, pas la certitude
        # que ce soit le bon conditionnement : deux articles de la meme
        # famille (ex. MOUTARDE 5K en SEAU vs MOUTARDE ANCIENNE 1K) peuvent
        # tous deux correspondre au mot-cle prononce. Sauter la recherche
        # globale au-dessus d'un seuil empechait alors la variante correcte
        # d'etre meme candidate, quel que soit son propre score. La
        # selection finale (_selectionner_meilleur_candidat) reste seule
        # responsable de departager cadencier et catalogue global une fois
        # les deux pools reunis.
        for variante in variantes_recherche:
            ajouter_candidats(
                rechercher_variante(
                    variante,
                    catalogue_global,
                    dans_cadencier_client=False,
                    source_recherche="catalogue_global",
                )
            )

        if catalogue_reappro:
            for variante in variantes_recherche:
                ajouter_candidats(
                    rechercher_variante(
                        variante,
                        catalogue_reappro,
                        dans_cadencier_client=False,
                        source_recherche="catalogue_reappro",
                    )
                )

        if code_prononce is not None:
            code, entendu, marqueur_explicite = code_prononce
            produit, source, dans_cadencier = articles_par_code[code]
            produit_direct = dict(produit)
            produit_direct.setdefault(
                "libelle_normalise",
                normaliser_texte(
                    str(produit_direct.get("libelle_article") or "")
                ),
            )
            candidat_direct = _rechercher_dans_pool(
                texte_mention=texte_semantique,
                unite_mention=unite_mention,
                produits_pool=[produit_direct],
                dans_cadencier_client=dans_cadencier,
                source_recherche=source,
                exclusions=mention.get("exclusions_produit", []),
                texte_semantique=texte_semantique,
            )[0]
            candidat_direct.update({
                "score_texte": 100.0,
                "score_global": 100.0,
                "semantiquement_compatible": True,
                "code_article_prononce_exact": True,
                "code_article_prononce_entendu": entendu,
                "code_article_prononce_avec_marqueur": marqueur_explicite,
            })
            candidat_direct["raisons"] = [
                raison
                for raison in candidat_direct.get("raisons", [])
                if not str(raison).startswith("incompatibilite=")
            ]
            candidat_direct["raisons"].append(
                "code_article_prononce_correspondance_unique"
            )
            ajouter_candidats([candidat_direct])
            candidat_conserve = candidats_par_code[code]
            candidat_conserve.update({
                "score_texte": 100.0,
                "score_global": 100.0,
                "semantiquement_compatible": True,
                "code_article_prononce_exact": True,
                "code_article_prononce_entendu": entendu,
                "code_article_prononce_avec_marqueur": marqueur_explicite,
            })
            candidat_conserve.setdefault("raisons", []).append(
                "code_article_prononce_correspondance_unique"
            )

        # Le referentiel officiel est un dernier recours, pas un catalogue
        # concurrent du cadencier : on ne l'interroge que lorsqu'aucun pool
        # de production n'a deja produit deux ancrages explicites. Chaque
        # reference ajoutee doit elle-meme partager au moins deux ancrages et
        # conserver un score lexical eleve. Ainsi une variante absente du
        # cadencier peut etre trouvee sans ouvrir la porte a un fuzzy global.
        if (
            code_prononce is None
            and business_rule_enabled("references_controle_fallback")
        ):
            groupes_tokens_explicites = [
                _tokens_produit(texte_semantique),
                *(
                    _tokens_produit(variante)
                    for variante in variantes_recherche
                    if normaliser_texte(variante) != texte_semantique
                ),
            ]

            def nb_ancrages_explicites(candidat: dict[str, Any]) -> int:
                tokens_libelle = _tokens_produit(
                    str(candidat.get("libelle_normalise") or "")
                )
                return max(
                    (
                        len(core_anchors(
                            tokens_explicites,
                            tokens_libelle,
                            _score_token_produit,
                        ))
                        for tokens_explicites in groupes_tokens_explicites
                    ),
                    default=0,
                )

            deja_candidat_precis = any(
                candidat.get("semantiquement_compatible", True)
                and float(candidat.get("score_texte", 0.0)) >= 65.0
                and nb_ancrages_explicites(candidat) >= 2
                for candidat in candidats_par_code.values()
            )
            if not deja_candidat_precis:
                for variante in variantes_recherche:
                    candidats_references = _rechercher_dans_pool(
                        texte_mention=variante,
                        unite_mention=unite_mention,
                        produits_pool=_catalogue_references_controle_produits(),
                        dans_cadencier_client=False,
                        source_recherche="referentiel_articles",
                        exclusions=mention.get("exclusions_produit", []),
                        texte_semantique=texte_semantique,
                    )
                    ajouter_candidats([
                        candidat
                        for candidat in candidats_references
                        if candidat.get("semantiquement_compatible", True)
                        and nb_ancrages_explicites(candidat) >= 2
                        and float(candidat.get("score_texte", 0.0)) >= 65.0
                    ])

        # Les variantes recuperent les fautes ASR. Les contradictions de la
        # mention source restent toujours bloquantes ; les contradictions
        # apportees par les seules variantes ne sont levees que dans le cas
        # explicite, fortement lexical, traite juste au-dessus.
        for candidat in candidats_par_code.values():
            incompatibilites_source = (
                []
                if candidat.get("code_article_prononce_exact")
                else _incompatibilites_semantiques(
                    str(
                        candidat.get("texte_semantique_source")
                        or texte_semantique
                    ),
                    str(candidat.get("libelle_normalise") or ""),
                    mention.get("exclusions_produit", []),
                )
            )
            incompatibilites = incompatibilites_source
            texte_recherche = normaliser_texte(
                str(candidat.get("texte_recherche") or "")
            )
            if (
                texte_recherche
                and texte_recherche != texte_semantique
                and candidat.get("variante_semantiquement_compatible")
            ):
                incompatibilites = [
                    raison
                    for raison in incompatibilites
                    if raison not in {
                        "noyau_produit_compose_contradictoire",
                        "noyau_produit_principal_contradictoire",
                    }
                ]
            candidat["semantiquement_compatible"] = not incompatibilites
            candidat["raisons"] = [
                raison
                for raison in candidat.get("raisons", [])
                if not str(raison).startswith("incompatibilite=")
            ]
            candidat["raisons"].extend(
                f"incompatibilite={raison}"
                for raison in incompatibilites
            )

        if business_rule_enabled("product_gate_noyau"):
            mention_tokens_gate = _tokens_produit(texte_semantique)
            noyaux_catalogue = {
                token
                for candidat in candidats_par_code.values()
                for token in core_anchors(
                    mention_tokens_gate,
                    _tokens_produit(
                        str(candidat.get("libelle_normalise") or "")
                    ),
                    _score_token_produit,
                )
            }
            tokens_discursifs = (
                TOKENS_SANS_NOYAU_PRODUIT
                | TOKENS_CONDITIONNEMENT_SANS_PRODUIT
                | QUALIFICATIFS_PRODUIT
                | FORMES_DISCOURS_COMMANDE
                | NOMS_DISCOURS_COMMANDE
            )
            tokens_substantiels_hors_catalogue = [
                token
                for token in mention_tokens_gate
                if token not in tokens_discursifs
                and not token.isdigit()
                and not re.fullmatch(r"\d+(?:\.\d+)?", token)
            ]
            clause_certainement_discursive = bool(
                analyser_role_semantique_clause(texte_semantique)
                in ROLES_SEMANTIQUES_NON_PRODUIT
                or not tokens_substantiels_hors_catalogue
            )
            if (
                not noyaux_catalogue
                and clause_certainement_discursive
                and code_prononce is None
            ):
                for candidat in candidats_par_code.values():
                    candidat["semantiquement_compatible"] = False
                    candidat.setdefault("raisons", []).append(
                        "product_gate_aucun_noyau_catalogue"
                    )

        appliquer_conditionnement_sur = business_rule_enabled(
            "conditionnement_physique_sur"
        )
        appliquer_relations_semantiques = business_rule_enabled(
            "relations_semantiques_variantes"
        )
        codes_secondaires_eligibles = (
            eligible_secondary_codes(
                candidats_par_code.values(),
                _tokens_produit(texte_semantique),
                _tokens_produit,
                _score_token_produit,
            )
            if appliquer_conditionnement_sur or appliquer_relations_semantiques
            else set()
        )

        for candidat in candidats_par_code.values():
            resolution = _resoudre_quantite_commande_candidat(
                mention=mention,
                candidat=candidat,
            )
            bonus_preference, raison_preference = (
                _bonus_preference_metier(
                    mention=mention,
                    candidat=candidat,
                )
            )
            code_candidat = str(candidat.get("code_article") or "")
            candidat_eligible_secondaire = (
                code_candidat in codes_secondaires_eligibles
            )
            score_physique, raisons_physiques = (
                safe_physical_score(
                    str(mention.get("texte_source") or ""),
                    str(candidat.get("libelle_article") or ""),
                    eligible=candidat_eligible_secondaire,
                )
                if appliquer_conditionnement_sur
                else (0.0, [])
            )
            score_semantique, raisons_semantiques = (
                semantic_variant_score(
                    str(mention.get("texte_source") or ""),
                    str(candidat.get("libelle_article") or ""),
                    eligible=candidat_eligible_secondaire,
                )
                if appliquer_relations_semantiques
                else (0.0, [])
            )
            candidat["quantite_resolue"] = resolution[
                "quantite_resolue"
            ]
            candidat["unite_resolue"] = resolution[
                "unite_resolue"
            ]
            candidat["score_conditionnement"] = round(
                resolution["score_conditionnement"]
                + bonus_preference,
                2,
            )
            candidat["noyau_eligible_signaux_secondaires"] = (
                candidat_eligible_secondaire
            )
            candidat["score_conditionnement_physique_sur"] = score_physique
            candidat["score_attribut_semantique"] = score_semantique
            candidat["raisons_resolution"] = resolution[
                "raisons_resolution"
            ]
            candidat["volume_demande_explicite"] = (
                mention.get("unite_principale") in {"KG", "L"}
            )
            candidat["raisons"].extend(
                resolution["raisons_resolution"]
            )
            candidat["raisons"].extend(raisons_physiques)
            candidat["raisons"].extend(raisons_semantiques)
            if raison_preference:
                candidat["raisons"].append(
                    raison_preference
                )

        appliquer_phonetique_intra_famille = business_rule_enabled(
            "fallback_phonetique_intra_famille"
        )
        appliquer_reappro_attribut = business_rule_enabled(
            "reappro_attribut_explicite"
        ) and business_rule_enabled("attributs_explicites_prioritaires")
        if appliquer_phonetique_intra_famille or appliquer_reappro_attribut:
            bonus_reappro = reappro_fallback_bonuses(
                candidats_par_code.values(),
                _tokens_produit(texte_semantique),
                _tokens_produit,
                _score_token_produit,
                allow_asr_variant=appliquer_phonetique_intra_famille,
                allow_explicit_attribute=appliquer_reappro_attribut,
            )
            for code, (bonus, raison) in bonus_reappro.items():
                candidat = candidats_par_code.get(code)
                if candidat is None:
                    continue
                candidat["bonus_reappro_fallback"] = bonus
                candidat.setdefault("raisons", []).append(raison)

        if (
            business_rule_enabled("historique_modificateur")
            and mention.get("preference_historique_compatible")
        ):
            candidats_historique = []
            for candidat in candidats_par_code.values():
                if not candidat.get("semantiquement_compatible", True):
                    continue
                if explicit_attribute_conflicts(
                    texte_semantique,
                    str(candidat.get("libelle_normalise") or ""),
                ):
                    continue
                noyaux = core_anchors(
                    _tokens_produit(texte_semantique),
                    _tokens_produit(
                        str(candidat.get("libelle_normalise") or "")
                    ),
                    _score_token_produit,
                )
                if noyaux:
                    candidats_historique.append(candidat)
            if candidats_historique:
                meilleur_texte_historique = max(
                    float(candidat.get("score_texte") or 0.0)
                    for candidat in candidats_historique
                )
                compatibles_proches = [
                    candidat
                    for candidat in candidats_historique
                    if float(candidat.get("score_texte") or 0.0)
                    >= meilleur_texte_historique - 12.0
                ]
                derniere_vente = max(
                    int(candidat.get("derniere_vente_article_ordinal", -1) or -1)
                    for candidat in compatibles_proches
                )
                if derniere_vente >= 0:
                    for candidat in compatibles_proches:
                        if int(
                            candidat.get("derniere_vente_article_ordinal", -1) or -1
                        ) == derniere_vente:
                            candidat["bonus_historique_compatible"] = 30.0
                            candidat.setdefault("raisons", []).append(
                                "derniere_reference_compatible_achetee"
                            )

        candidats = sorted(
            candidats_par_code.values(),
            key=lambda candidat: (
                candidat["dans_cadencier_client"],
                candidat["score_global"],
                candidat.get(
                    "score_conditionnement", 0.0
                ),
                candidat["score_texte"],
                candidat["nb_ventes_article_total"],
                candidat["nb_ventes_article_recentes"],
            ),
            reverse=True,
        )

        meilleur, raisons_selection = (
            _selectionner_meilleur_candidat(
                candidats, texte_source=texte_semantique
            )
        )
        # Une fois la famille et les attributs valides, le cadencier redevient
        # le departageur metier. Ce rattrapage est volontairement borne : il
        # ne s'applique que contre un gagnant hors cadencier, a un candidat
        # client semantiquement compatible et lexicalement prouve, avec un
        # ecart de score texte inferieur ou egal a 35 points. Un catalogue
        # portant une variante explicite nettement plus precise (par exemple
        # ``farinee`` face a ``panee``) reste donc prioritaire.
        if (
            meilleur
            and not meilleur.get("dans_cadencier_client")
            and meilleur.get("source_recherche") == "referentiel_articles"
            and float(meilleur.get("bonus_reappro_fallback", 0.0)) <= 0.0
        ):
            cadencier_equivalents = []
            for candidat in candidats:
                if (
                    not candidat.get("dans_cadencier_client")
                    or not candidat.get("semantiquement_compatible", True)
                    or explicit_attribute_conflicts(
                        texte_semantique,
                        str(candidat.get("libelle_normalise") or ""),
                    )
                ):
                    continue
                noyau_cadencier_prouve, _ = _preuve_positive_noyau_produit(
                    texte_semantique,
                    candidat,
                    variantes_recherche,
                    mention,
                )
                ecart_texte = float(meilleur.get("score_texte", 0.0)) - float(
                    candidat.get("score_texte", 0.0)
                )
                if noyau_cadencier_prouve and ecart_texte <= 35.0:
                    cadencier_equivalents.append(candidat)
            if cadencier_equivalents:
                cadencier_equivalents.sort(
                    key=lambda candidat: (
                        float(candidat.get("score_selection", 0.0)),
                        float(candidat.get("score_texte", 0.0)),
                        int(candidat.get("nb_ventes_article_total", 0)),
                    ),
                    reverse=True,
                )
                ancien_meilleur = meilleur
                meilleur = dict(cadencier_equivalents[0])
                meilleur["regle_selection"] = (
                    "cadencier_equivalent_apres_compatibilite"
                )
                meilleur.setdefault("raisons", []).extend([
                    "cadencier_prioritaire_apres_noyau_et_attributs",
                    f"alternative_catalogue={ancien_meilleur.get('code_article')}",
                ])
        if meilleur is not None:
            meilleur["raisons"].append(
                f"regle_selection={meilleur.get('regle_selection')}"
            )

        autres_candidats = [
            candidat
            for candidat in candidats
            if _candidat_commandable(candidat)
            and (not meilleur
            or candidat["code_article"]
            != meilleur["code_article"])
        ]
        autres_candidats.sort(
            key=lambda candidat: (
                float(candidat.get("score_selection", -9999.0)),
                float(candidat.get("score_texte", 0.0)),
            ),
            reverse=True,
        )
        second = autres_candidats[0] if autres_candidats else None
        marge = (
            round(
                float(meilleur.get("score_selection", 0.0))
                - float(second.get("score_selection", 0.0)),
                2,
            )
            if meilleur and second
            else 999.0
        )

        tokens_selection_preuve = set(
            _tokens_produit(str((meilleur or {}).get("libelle_normalise") or ""))
        )
        tokens_mention_preuve = set(_tokens_produit(texte_semantique))
        tokens_exacts_produit = {
            token
            for token in tokens_selection_preuve & tokens_mention_preuve
            if len(token) >= 5
            and token not in TOKENS_CONDITIONNEMENT_SANS_PRODUIT
            and token not in QUALIFICATIFS_PRODUIT
            and token not in TOKENS_SANS_NOYAU_PRODUIT
            and not token.isdigit()
        }
        noyau_exact_long_unique = any(
            len(token) >= 7
            and sum(
                1
                for candidat in candidats
                if _candidat_commandable(candidat)
                and token in set(
                    _tokens_produit(
                        str(candidat.get("libelle_normalise") or "")
                    )
                )
            )
            == 1
            for token in tokens_exacts_produit
        )
        score_selection_meilleur = float(
            (meilleur or {}).get("score_selection", 0.0)
        )
        candidats_proches_selection = [
            candidat
            for candidat in candidats
            if _candidat_commandable(candidat)
            and float(candidat.get("score_selection", -9999.0))
            >= score_selection_meilleur - 5.0
        ]
        noyau_exact_long_commun_aux_proches = any(
            len(token) >= 7
            and candidats_proches_selection
            and all(
                token
                in set(
                    _tokens_produit(
                        str(candidat.get("libelle_normalise") or "")
                    )
                )
                for candidat in candidats_proches_selection
            )
            for token in tokens_exacts_produit
        )
        noyau_defaut_un_prouve = False
        if meilleur:
            noyau_defaut_un_prouve, _ = _preuve_positive_noyau_produit(
                texte_semantique,
                meilleur,
                variantes_recherche,
                mention,
            )
        if (
            meilleur
            and mention.get("quantite_principale") is None
            and meilleur.get("quantite_resolue") is None
            and meilleur.get("semantiquement_compatible", True)
            and noyau_defaut_un_prouve
            and tokens_exacts_produit
            and re.search(
                r"^(?:des?|du|de\s+la|un|une|quelques|plusieurs)\b|"
                r"\b(?:sacs?|sachets?|poches?|pots?|boites?|cartons?|colis|"
                r"paquets?|barquettes?|bouteilles?|bidons?|seaux?)\b",
                normaliser_texte(str(mention.get("texte_source") or "")),
            )
            and (
                (
                    meilleur.get("dans_cadencier_client")
                    and float(meilleur.get("score_texte", 0.0)) >= 45.0
                    and marge >= 12.0
                )
                or (
                    float(meilleur.get("score_texte", 0.0)) >= 85.0
                    and marge >= 15.0
                )
            )
        ):
            meilleur["quantite_resolue"] = 1.0
            meilleur.setdefault("raisons_resolution", []).append(
                "quantite_absente_defaut_un_apres_noyau_exact"
            )
            meilleur.setdefault("raisons", []).append(
                "quantite_absente_defaut_un_apres_noyau_exact"
            )

        ancrages_distinctifs = {
            "sriracha", "nuggets", "fregola", "txistorra", "rabas",
            "piquill", "burrata", "paellador",
        }
        tokens_selection = set(
            _tokens_produit(str((meilleur or {}).get("libelle_normalise") or ""))
        )
        tokens_semantiques = set(_tokens_produit(texte_semantique))
        ancrage_distinctif = bool(
            tokens_selection & tokens_semantiques & ancrages_distinctifs
        )
        reference_officielle = bool(
            meilleur
            and str(meilleur.get("code_article") or "")
            in _charger_references_controle()
        )
        candidat_inactif_nettement_plus_proche = any(
            (
                "***" in str(candidat.get("libelle_article") or "")
                or "***" in str(candidat.get("libelle_normalise") or "")
            )
            and candidat.get("semantiquement_compatible", True)
            and float(candidat.get("score_texte", 0.0)) >= 85.0
            and float(candidat.get("score_texte", 0.0))
            >= float((meilleur or {}).get("score_texte", 0.0)) + 25.0
            for candidat in candidats
        ) and float((meilleur or {}).get("score_texte", 0.0)) < 50.0

        equivalence_synonyme_declaree, raison_equivalence_synonyme = (
            _equivalence_synonyme_declaree_confirme_candidat(
                texte_semantique,
                meilleur,
                synonymes,
            )
            if meilleur
            else (False, "")
        )
        if equivalence_synonyme_declaree:
            meilleur.setdefault("raisons", []).append(
                raison_equivalence_synonyme
            )

        produit_fiable = bool(
            meilleur
            and _candidat_commandable(meilleur)
            and meilleur.get("quantite_resolue")
            is not None
            and (
                (
                    meilleur["score_global"]
                    >= SEUIL_PRODUIT_FIABLE
                    and marge >= 7
                )
                or (
                    meilleur["score_global"] >= 90
                    and meilleur[
                        "dans_cadencier_client"
                    ]
                    and marge >= 3
                )
                or (
                    meilleur["dans_cadencier_client"]
                    and (
                        meilleur["score_global"] >= 50
                        or (
                            meilleur.get("regle_selection")
                            in {
                                "cadencier_unique",
                                "cadencier_plus_vendu",
                                "cadencier_score_frequence",
                                "cadencier_frequence_marge_securisee",
                                "cadencier_seul_score_acceptable",
                            }
                            and meilleur["score_global"] >= 35
                        )
                    )
                )
                # Une equivalence complete du dictionnaire est une preuve
                # plus forte qu'un score fuzzy calcule sur le texte ASR brut.
                # Elle reste strictement bornee au cadencier du client, a un
                # article commandable, semantiquement compatible et a une
                # vraie marge de selection : elle ne transforme donc jamais
                # une simple ressemblance ou un historique seul en produit.
                or (
                    equivalence_synonyme_declaree
                    and meilleur.get("dans_cadencier_client")
                    and meilleur.get("source_recherche")
                    == "cadencier_client"
                    and meilleur.get("semantiquement_compatible", True)
                    and marge >= 3.0
                )
                or (
                    meilleur.get("dans_cadencier_client")
                    and meilleur.get("noyau_phonetique_cadencier_prouve")
                    and marge >= 6.0
                )
                or (
                    meilleur.get("regle_selection")
                    in {
                        "catalogue_score_frequence",
                        "catalogue_frequence_marge_securisee",
                    }
                    and meilleur["score_global"] >= 70
                    and meilleur.get("score_texte", 0.0) >= 65
                    and marge >= 0.5
                )
                or (
                    reference_officielle
                    and meilleur["score_global"] >= 75
                    and meilleur.get("score_texte", 0.0) >= 70
                    and marge >= 0.5
                )
                or (
                    meilleur.get("regle_selection")
                    == "catalogue_unique"
                    and meilleur["score_global"] >= 70
                    and meilleur.get("score_texte", 0.0) >= 65
                )
                or (
                    reference_officielle
                    and meilleur.get("regle_selection") == "catalogue_unique"
                    and meilleur.get("score_texte", 0.0) >= 60
                )
                or (
                    reference_officielle
                    and ancrage_distinctif
                    and meilleur.get("score_texte", 0.0) >= 45
                    and marge >= 5
                )
                or (
                    meilleur.get("source_recherche")
                    in {"catalogue_global", "catalogue_reappro"}
                    and any(len(token) >= 7 for token in tokens_exacts_produit)
                    and meilleur.get("score_texte", 0.0) >= 50
                    and meilleur["score_global"] >= 50
                    and marge >= 12
                )
                or (
                    "selection_noyau_exact_distinctif_unique"
                    in meilleur.get("raisons", [])
                    and meilleur.get("quantite_resolue") is not None
                )
                or (
                    noyau_exact_long_unique
                    and meilleur.get("score_texte", 0.0) >= 50.0
                )
                or (
                    noyau_exact_long_commun_aux_proches
                    and meilleur.get("score_texte", 0.0) >= 50.0
                )
                or (
                    any(len(token) >= 7 for token in tokens_exacts_produit)
                    and meilleur.get("score_texte", 0.0) >= 50.0
                )
                or (
                    meilleur.get("regle_selection")
                    == "catalogue_score_frequence"
                    and meilleur["score_global"] >= 90
                    and meilleur.get("score_texte", 0.0) >= 90
                    and marge >= 1
                )
                or (
                    meilleur.get("regle_selection")
                    == "catalogue_unique"
                    and meilleur["score_global"] >= 60
                    and meilleur.get("score_texte", 0.0) >= 55
                    and any(
                        "preference_dimension_" in str(raison)
                        for raison in meilleur.get("raisons", [])
                    )
                )
            )
        )
        if produit_fiable and candidat_inactif_nettement_plus_proche:
            produit_fiable = False
            raisons_selection = [
                *raisons_selection,
                "article_exact_inactif_sans_substitution_fiable",
            ]

        # Le parfum explicite ne peut corriger qu'une ligne qui aurait déjà
        # été retenue par le moteur sans cette règle. Cette position après le
        # calcul de fiabilité garantit un remplacement 1-pour-1 : elle ne peut
        # ni créer une ligne, ni rendre une commande entière acceptable.
        selection_avant_parfum_glace: dict[str, Any] | None = None
        if produit_fiable and meilleur:
            candidat_parfum = _candidat_parfum_glace_explicitement_prononce(
                texte_semantique,
                meilleur,
                candidats,
            )
            if candidat_parfum is not None:
                selection_avant_parfum_glace = dict(meilleur)
                ancien_code = str(meilleur.get("code_article") or "")
                meilleur = dict(candidat_parfum)
                meilleur["regle_selection"] = (
                    "parfum_glace_explicite_prioritaire"
                )
                meilleur["marge_selection_ponderee"] = float(
                    candidat_parfum.get("score_texte", 0.0)
                ) - float(
                    next(
                        (
                            candidat.get("score_texte", 0.0)
                            for candidat in candidats
                            if str(candidat.get("code_article") or "")
                            == ancien_code
                        ),
                        0.0,
                    )
                )
                meilleur.setdefault("raisons", []).extend([
                    "parfum_glace_explicite_prioritaire_sur_historique",
                    "ligne_deja_fiable_remplacee_sans_changer_le_statut",
                    "regle_selection=parfum_glace_explicite_prioritaire",
                ])

        # Seconde passe de reconnaissance : la confiance dans le code
        # produit est independante de la presence d'une quantite exploitable.
        # Elle reste bornee aux mentions deja extraites comme produits et a
        # une reference cadencier/Reapro qui partage un vrai mot produit.
        seconde_passe_produit = False
        if (
            not produit_fiable
            and meilleur
            and meilleur.get("semantiquement_compatible", True)
            and meilleur.get("source_recherche")
            in {"cadencier_client", "catalogue_reappro"}
            and float(meilleur.get("score_texte", 0.0)) >= 55.0
            and str(mention.get("role_semantique") or "PRODUCT_ITEM")
            not in ROLES_SEMANTIQUES_NON_PRODUIT
            and _clause_ressemble_a_produit(texte_semantique)
        ):
            tokens_mention_seconde_passe = _tokens_produit(
                texte_semantique
            )
            tokens_libelle_seconde_passe = _tokens_produit(
                str(meilleur.get("libelle_normalise") or "")
            )
            ancrage_seconde_passe = any(
                _score_token_produit(token, token_libelle) >= 90.0
                for token in tokens_mention_seconde_passe
                for token_libelle in tokens_libelle_seconde_passe
                if token not in TOKENS_CONDITIONNEMENT_SANS_PRODUIT
                and token not in QUALIFICATIFS_PRODUIT
                and not token.isdigit()
            )
            if ancrage_seconde_passe:
                seconde_passe_produit = True
                meilleur.setdefault("raisons", []).append(
                    "seconde_passe_noyau_produit"
                )

        ambigu = mention.get("ambigu", False)
        raisons_ambiguite = list(
            mention.get("raisons_ambiguite", [])
        )

        if business_rule_enabled("product_gate_noyau") and meilleur:
            noyau_prouve, raisons_preuve_noyau = (
                _preuve_positive_noyau_produit(
                    str(
                        meilleur.get("texte_semantique_source")
                        or texte_semantique
                    ),
                    meilleur,
                    variantes_recherche,
                    mention,
                )
            )
            meilleur["noyau_produit_prouve"] = noyau_prouve
            meilleur.setdefault("raisons", []).extend(
                raisons_preuve_noyau
            )
            if not noyau_prouve:
                # Le cadencier, l'historique et un score fuzzy ne peuvent
                # jamais creer a eux seuls une ligne produit. La selection
                # reste exposee pour le diagnostic, mais elle n'est ni
                # reconnue ni commandable.
                produit_fiable = False
                seconde_passe_produit = False
                ambigu = True
                raisons_ambiguite.append(
                    "product_gate_noyau_non_prouve"
                )

        if (
            produit_fiable
            and meilleur
            and meilleur.get("quantite_resolue") is not None
        ):
            raisons_ambiguite = [
                raison
                for raison in raisons_ambiguite
                if raison
                not in {
                    "unite_absente_a_resoudre",
                    "repetition_transcription_supprimee",
                    "reformulation_proche_fusionnee",
                    "precision_quantite_rattachee",
                    "conditionnement_multiple",
                }
            ]
            ambigu = bool(raisons_ambiguite)



        if not candidats:
            ambigu = True
            raisons_ambiguite.append(
                "aucun_article_trouve"
            )
        elif raisons_selection:
            ambigu = True
            raisons_ambiguite.extend(raisons_selection)
        elif not produit_fiable and (
            meilleur["score_global"] < SEUIL_PRODUIT_MIN
            and not (
                meilleur.get("dans_cadencier_client")
                and meilleur["score_global"]
                >= SEUIL_PRODUIT_CADENCIER_MIN
                and meilleur.get("regle_selection")
                in {
                    "cadencier_unique",
                    "cadencier_plus_vendu",
                }
            )
        ):
            ambigu = True
            raisons_ambiguite.append(
                "score_produit_trop_faible"
            )
        elif not produit_fiable:
            ambigu = True
            raisons_ambiguite.append(
                "selection_article_non_nette"
            )
        if (
            meilleur
            and meilleur.get("quantite_resolue")
            is None
        ):
            ambigu = True
            raisons_ambiguite.append(
                "quantite_commande_non_resolue"
            )

        candidats_exposes: list[dict[str, Any]] = []
        codes_exposes: set[str] = set()

        def exposer(items: list[dict[str, Any]]) -> None:
            for item in items:
                code = str(item.get("code_article") or "")
                if not code or code in codes_exposes or len(candidats_exposes) >= limite:
                    continue
                candidats_exposes.append(item)
                codes_exposes.add(code)

        if meilleur:
            exposer([meilleur])
            
        tiers = max(1, limite // 3)
        exposer([item for item in candidats if item.get("source_recherche") == "cadencier_client"][:tiers])
        exposer([item for item in candidats if item.get("source_recherche") == "catalogue_global"][:tiers])
        exposer([item for item in candidats if item.get("source_recherche") == "catalogue_reappro"][:tiers])
        exposer(candidats)
        
        candidats_exposes.sort(
            key=lambda candidat: (
                candidat["dans_cadencier_client"],
                candidat["score_global"],
                candidat.get("score_conditionnement", 0.0),
                candidat["score_texte"],
            ),
            reverse=True,
        )

        produit_reconnu = bool(
            produit_fiable or seconde_passe_produit
        )
        noyau_produit_prouve = bool(
            meilleur and meilleur.get("noyau_produit_prouve")
        )
        if produit_reconnu and (
            not produit_fiable
            or mention.get("modalite_demande") == "ALTERNATIVE"
        ):
            statut_couverture = "AMBIGU"
        elif produit_reconnu:
            statut_couverture = "RECONNU"
        elif noyau_produit_prouve:
            statut_couverture = "NON_IDENTIFIE"
        else:
            statut_couverture = "HORS_COMMANDE"

        resultats.append(
            {
                **mention,
                "variantes_recherche": variantes_recherche,
                "candidats": candidats_exposes,
                "produit_fiable": produit_fiable,
                "produit_reconnu": produit_reconnu,
                "seconde_passe_produit": seconde_passe_produit,
                "statut_couverture": statut_couverture,
                "ambigu": ambigu,
                "raisons_ambiguite": sorted(
                    set(raisons_ambiguite)
                ),
                "quantite_resolue": (
                    meilleur.get("quantite_resolue")
                    if meilleur
                    else None
                ),
                "unite_resolue": (
                    meilleur.get("unite_resolue")
                    if meilleur
                    else None
                ),
                "selection": meilleur,
                "_selection_avant_parfum_glace": selection_avant_parfum_glace,
            }
        )

    # Une même référence historique peut avoir absorbé plusieurs mentions
    # d'une énumération. La remplacer séparément ferait apparaître de nouvelles
    # lignes dont les quantités n'ont pas été arbitrées. Dans ce cas seulement,
    # on conserve les sélections d'origine ; un produit isolé reste corrigé.
    codes_avant_parfum: dict[str, int] = {}
    for resultat in resultats:
        selection_originale = (
            resultat.get("_selection_avant_parfum_glace")
            or resultat.get("selection")
            or {}
        )
        code_original = str(selection_originale.get("code_article") or "")
        if code_original:
            codes_avant_parfum[code_original] = (
                codes_avant_parfum.get(code_original, 0) + 1
            )

    for resultat in resultats:
        selection_originale = resultat.pop(
            "_selection_avant_parfum_glace", None
        )
        if not selection_originale:
            continue
        code_original = str(selection_originale.get("code_article") or "")
        if codes_avant_parfum.get(code_original, 0) <= 1:
            continue
        selection_originale.setdefault("raisons", []).append(
            "priorite_parfum_non_appliquee_sur_enumeration_fusionnee"
        )
        resultat["selection"] = selection_originale
        resultat["quantite_resolue"] = selection_originale.get(
            "quantite_resolue"
        )
        resultat["unite_resolue"] = selection_originale.get(
            "unite_resolue"
        )
        candidats_exposes = [
            selection_originale,
            *(
                candidat
                for candidat in resultat.get("candidats", [])
                if str(candidat.get("code_article") or "") != code_original
            ),
        ]
        resultat["candidats"] = candidats_exposes[:limite]

    return resultats
