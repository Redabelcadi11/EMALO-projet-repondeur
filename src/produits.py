from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from .normalisation import enlever_accents, normaliser_texte


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
)

SEUIL_PRODUIT_FIABLE = 78.0
SEUIL_PRODUIT_MIN = 60.0
SEUIL_PRODUIT_CADENCIER_MIN = 45.0
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
    regles = [
        regle
        for regle in (brut.get("rules") if isinstance(brut, dict) else [])
        if isinstance(regle, dict) and regle.get("enabled", True)
    ]
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


def _bonus_regle_apprentissage(
    produit: str,
    source_mention: str,
    libelle: str,
) -> tuple[float, str | None]:
    meilleur_bonus = 0.0
    meilleure_raison: str | None = None
    champs = {
        "mention": produit,
        "source": source_mention,
        "label": libelle,
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
    texte = re.sub(r"(\d)\s*,\s*(\d)", r"\1.\2", texte)
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


def _couper_avant_quantite_commande(
    clause_norm: str,
) -> str:
    if re.match(r"^\d+(?:\.\d+)?\b", clause_norm):
        return clause_norm

    match = re.search(
        (
            r"\b\d+(?:\.\d+)?"
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


def _rattacher_precision_produit_precedent(
    clause_norm: str,
    mentions: list[dict[str, Any]],
) -> bool:
    precision = clause_norm.strip()

    if mentions:
        precedente = mentions[-1]

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
        r"(?P<taux>\d+(?:\.\d+)?)\s*pour\s*cent",
        precision,
    )
    if pourcentage and mentions:
        precedente = mentions[-1]
        produit_precedent = normaliser_texte(
            precedente.get("produit_normalise", "")
        )
        if any(
            terme in produit_precedent
            for terme in ("creme", "lait", "matiere grasse")
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

    return re.sub(r"\s+", " ", produit).strip()


def _clause_hors_produit(
    clause_norm: str,
) -> bool:
    clause_norm = clause_norm.strip()

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
        "si vous avez",
        "s il vous plait",
        "s il te plait",
    }:
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
    )

    if re.fullmatch(
        r"pour\s+(?:le|la|les|l)\s+[a-z][a-z0-9\s]{1,60}",
        clause_norm,
    ):
        return True

    return clause_norm.startswith(prefixes)


def decouper_clauses_produits(
    transcription: str,
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
        "faudrait",
    )
    clauses_avant_coupe: list[str] = []
    motif_produit_puis_quantite = re.compile(
        (
            r"(?P<produit>[a-z][a-z0-9\s]{2,80}?)"
            r"[,\s]+(?:il\s+me\s+faudrait|il\s+me\s+faut|il\s+m\s+aurait\s+fallu|il\s+faudrait)\s+"
            r"(?P<quantite>\d+(?:\.\d+)?)"
            r"\s*(?P<unite>"
            + UNITES_REGEX
            + r")\b"
        )
    )
    for match in motif_produit_puis_quantite.finditer(texte):
        produit = _nettoyer_debut_clause(
            match.group("produit")
        )
        produit = _normaliser_produit_extrait(produit)
        if produit and _clause_ressemble_a_produit(produit):
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

    positions_debut = [
        texte.find(marqueur)
        for marqueur in marqueurs_debut_commande
        if texte.find(marqueur) != -1
    ]

    if positions_debut:
        texte = texte[min(positions_debut) :]

    for marqueur in MOTS_FIN_COMMANDE:
        texte = re.split(
            rf"\b{re.escape(marqueur)}\b",
            texte,
            maxsplit=1,
        )[0]

    clauses_initiales = [
        morceau.strip()
        for morceau in re.split(
            r"[;,]|(?<!\d)\.(?!\d)",
            texte,
        )
        if morceau.strip()
    ]

    clauses: list[str] = []
    separateur_et = (
        r"\b(?:et|ainsi\s+que|ainsi\s+qu)\s+"
        r"(?=(?:\d+(?:\.\d+)?|"
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
            r"(?<!des)(?<!une)\s+"
            r"(?=(?:(?:\d+(?:\.\d+)?)\s+)?"
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
                            r"(?<!en)(?<!x)\s+"
                            r"(?=\d+(?:\.\d+)?\s+"
                            r"(?!(?:g|grammes?|kg|kilos?|l|litres?)\b)"
                            r"[a-z])"
                        ),
                        morceau_conditionnement,
                    )
                )

        for morceau in morceaux:
            propre = _nettoyer_debut_clause(morceau)

            if (
                propre
                and propre not in {"et", "de", "d"}
                and (
                    not _clause_hors_produit(
                        _normaliser_clause_parse(propre)
                    )
                    or _clause_peut_completer_produit_precedent(
                        _normaliser_clause_parse(propre)
                    )
                )
            ):
                clauses.append(propre)

    return clauses_avant_coupe + clauses


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
    libelle = str(
        candidat.get("libelle_normalise")
        or candidat.get("libelle_article", "")
        or ""
    )
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

    if motif_multi:
        nb_sous_unites = int(motif_multi.group("count"))
        unite_base, taille_base = (
            _convertir_taille_conditionnement(
                motif_multi.group("size"),
                motif_multi.group("unit"),
            )
        )
        if unite_base == "KG":
            meta["taille_kg_par_unite"] = taille_base
        elif unite_base == "L":
            meta["taille_l_par_unite"] = taille_base
        meta["nb_sous_unites_colis"] = nb_sous_unites
        meta["source"] = "libelle_multi"

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
        r"(?:x\s*|\(\s*)(?P<count>[1-9]\d*)\s*p?\b",
        libelle,
    )

    if motif_items:
        nb_items = int(motif_items.group("count"))
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
    ratio_net_par_unite = float(
        candidat.get("ratio_net_par_unite", 0.0)
        or 0.0
    )

    resolution = {
        "quantite_resolue": None,
        "unite_resolue": meta["unite_commande"],
        "score_conditionnement": 0.0,
        "raisons_resolution": [],
    }

    if quantite is None:
        if quantite_habituelle > 0:
            resolution["quantite_resolue"] = (
                _arrondir_quantite_commande(
                    quantite_habituelle
                )
            )
            resolution["score_conditionnement"] = 22.0
            resolution["raisons_resolution"].append(
                "quantite_habituelle_client"
            )
        else:
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
        if taille is None and ratio_net_par_unite > 0:
            taille = ratio_net_par_unite

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

    if unite == "L":
        taille = meta["taille_l_par_unite"]
        if taille is None and ratio_net_par_unite > 0:
            taille = ratio_net_par_unite

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
        transcription
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
            r"\s+"
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

    for clause in clauses:
        clause_norm = _normaliser_clause_parse(
            clause
        )
        clause_norm = _couper_avant_quantite_commande(
            clause_norm
        )

        if not clause_norm:
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
            r"^(?:il\s+)?(?:m\s+|nous\s+)?en\s+faudrait\s+"
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
            }
        )

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
    for original in mentions:
        mention = dict(original)
        produit = normaliser_texte(mention.get("produit_normalise", ""))
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
            set(_tokens_produit(produit)) & saveurs
            and not re.search(
                r"\b(?:surgele|congele|frais|fraiche|liquide|jus|puree|coulis|confiture|sirop)\b",
                produit,
            )
            and "glace" not in produit
            and "sorbet" not in produit
        ):
            produit = f"glace {produit}"
            mention["produit_normalise"] = produit
            mention["texte_produit"] = produit
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
            if fuzz.token_set_ratio(produit, produit_existant) < 94:
                continue
            discriminants = {
                "blanc",
                "jaune",
                "entier",
                "liquide",
                "dur",
                "ecale",
                "rape",
                "rapee",
                "copeau",
                "copeaux",
                "bloc",
                "tranche",
                "tranches",
            }
            if (
                set(produit.split()) & discriminants
                != set(produit_existant.split()) & discriminants
            ):
                continue
            quantite_existante = existante.get("quantite_principale")
            if quantite is not None and quantite_existante is not None:
                if abs(float(quantite) - float(quantite_existante)) > 0.001:
                    continue
            position = index
            break

        if position is None:
            resultat.append(mention)
            continue

        existante = resultat[position]
        if existante.get("quantite_principale") is None and quantite is not None:
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
        "client",
        "restaurant",
        "voudrais",
        "souhaite",
        "commande",
        "appareil",
        "demain",
        "alors",
        "oui",
        "donc",
        "ensuite",
        "fois",
        "litre",
        "litres",
        "voila",
    }

    return any(
        token not in tokens_generiques
        for token in tokens
    )


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

    if "sucre" in mention:
        variantes_sucre = {
            "semoule": ("semoule",),
            "glace": ("glace",),
            "roux": ("roux", "cassonade"),
        }
        variantes_demandees = {
            nom for nom, termes in variantes_sucre.items()
            if mention_contient(*termes)
        }
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

    return sorted(set(raisons))


def _score_correspondance_produit(
    texte_mention: str,
    texte_libelle: str,
    unite_mention: str | None,
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

    if "glace" in tokens_mention and "vanille" in tokens_mention:
        if "vanille" in tokens_libelle and "glace" in tokens_libelle:
            score += 18.0
        if "arome" in tokens_libelle:
            score -= 18.0

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

    if _incompatibilites_semantiques(mention_norm, libelle_norm):
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

    for canonique, termes in synonymes.items():
        termes_norm = [
            normaliser_texte(terme)
            for terme in termes
            if normaliser_texte(terme)
        ]

        termes_presents = [
            terme
            for terme in termes_norm
            if f" {terme} " in base_padding
        ]

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
                    canonique,
                )
            )

    return sorted(
        variantes,
        key=len,
        reverse=True,
    )[:8]


def _rechercher_dans_pool(
    texte_mention: str,
    unite_mention: str | None,
    produits_pool: list[dict[str, Any]],
    dans_cadencier_client: bool,
    source_recherche: str,
    exclusions: list[str] | None = None,
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
            scorer=fuzz.WRatio,
            score_cutoff=15.0,
            limit=120,
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
        )
        incompatibilites = _incompatibilites_semantiques(
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
        candidat.get("semantiquement_compatible", True)
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
    return round(
        float(candidat.get("score_texte", 0.0))
        + 40.0 * bool(candidat.get("dans_cadencier_client"))
        # Le conditionnement valide la commandabilite mais ne doit pas
        # renverser une identite produit textuellement plus nette. Deux
        # conditionnements officiels compatibles sont departages d'abord par
        # le produit, puis par l'historique.
        + poids_conditionnement
        * float(candidat.get("score_conditionnement", 0.0))
        + 1.5 * math.log1p(int(candidat.get("nb_ventes_article_total", 0)))
        + 3.5 * math.log1p(int(candidat.get("nb_ventes_article_recentes", 0)))
        + 0.06 * recence
        + 4.0
        * (
            candidat.get("source_article")
            == "referentiel_articles"
        ),
        4,
    )


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


def _selectionner_meilleur_candidat(
    candidats: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    if not candidats:
        return None, []

    candidats_commandables = [
        candidat for candidat in candidats if _candidat_commandable(candidat)
    ]
    if not candidats_commandables:
        return None, ["candidat_catalogue_prix_zero"]

    for candidat in candidats_commandables:
        candidat["score_selection"] = _score_selection_ponderee(candidat)
    candidats_commandables.sort(
        key=lambda candidat: (
            float(candidat["score_selection"]),
            float(candidat.get("score_texte", 0.0)),
            int(candidat.get("nb_ventes_article_recentes", 0)),
            int(candidat.get("nb_ventes_article_total", 0)),
        ),
        reverse=True,
    )
    selection = candidats_commandables[0]
    meilleurs_globaux = [
        candidat
        for candidat in candidats_commandables
        if not candidat.get("dans_cadencier_client")
    ]
    meilleurs_cadencier = [
        candidat
        for candidat in candidats_commandables
        if candidat.get("dans_cadencier_client")
    ]
    global_net = max(
        meilleurs_globaux,
        key=lambda candidat: float(candidat.get("score_texte", 0.0)),
        default=None,
    )
    cadencier_net = max(
        meilleurs_cadencier,
        key=lambda candidat: float(candidat.get("score_texte", 0.0)),
        default=None,
    )
    if (
        selection.get("dans_cadencier_client")
        and global_net is not None
        and float(global_net.get("score_texte", 0.0)) >= 85.0
        and (
            cadencier_net is None
            or (
                float(cadencier_net.get("score_texte", 0.0)) <= 68.0
                and float(global_net.get("score_texte", 0.0))
                - float(cadencier_net.get("score_texte", 0.0))
                >= 20.0
            )
        )
    ):
        selection = global_net
        selection["raisons"].append(
            "catalogue_global_correspondance_textuelle_nette"
        )

    meilleur = dict(selection)
    if len(candidats_commandables) == 1:
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
    second = candidats_commandables[1] if len(candidats_commandables) > 1 else None
    meilleur["marge_selection_ponderee"] = round(
        float(meilleur["score_selection"])
        - float(second["score_selection"] if second else 0.0),
        4,
    )
    return meilleur, []

def chercher_produits(
    mentions: list[dict[str, Any]],
    produits_client: list[dict[str, Any]],
    catalogue_global: list[dict[str, Any]],
    synonymes: dict[str, list[str]],
    limite: int = 20,
) -> list[dict[str, Any]]:
    resultats: list[dict[str, Any]] = []

    for mention in mentions:
        texte_produit = mention["produit_normalise"]
        unite_mention = mention.get("unite_principale")
        variantes_recherche = _generer_variantes_recherche(
            produit_normalise=texte_produit,
            synonymes=synonymes,
        )

        candidats_par_code: dict[str, dict[str, Any]] = {}

        def ajouter_candidats(
            candidats: list[dict[str, Any]],
        ) -> None:
            for candidat in candidats:
                code = candidat["code_article"]
                courant = candidats_par_code.get(code)

                if (
                    courant is None
                    or candidat["score_global"]
                    > courant["score_global"]
                ):
                    candidats_par_code[code] = candidat

        for variante in variantes_recherche:
            if produits_client:
                ajouter_candidats(
                    _rechercher_dans_pool(
                        texte_mention=variante,
                        unite_mention=unite_mention,
                        produits_pool=produits_client,
                        dans_cadencier_client=True,
                        source_recherche="cadencier_client",
                        exclusions=mention.get("exclusions_produit", []),
                    )
                )

        texte_semantique = " ".join(variantes_recherche)
        for candidat in candidats_par_code.values():
            incompatibilites = _incompatibilites_semantiques(
                texte_semantique,
                str(candidat.get("libelle_normalise") or ""),
                mention.get("exclusions_produit", []),
            )
            candidat["semantiquement_compatible"] = not incompatibilites

        meilleur_cadencier = max(
            (
                candidat["score_global"]
                for candidat in candidats_par_code.values()
                if candidat["dans_cadencier_client"]
                and candidat.get("semantiquement_compatible", True)
            ),
            default=0.0,
        )

        if not candidats_par_code or meilleur_cadencier < 95:
            for variante in variantes_recherche:
                ajouter_candidats(
                    _rechercher_dans_pool(
                        texte_mention=variante,
                        unite_mention=unite_mention,
                        produits_pool=catalogue_global,
                        dans_cadencier_client=False,
                        source_recherche="catalogue_global",
                        exclusions=mention.get("exclusions_produit", []),
                    )
                )

        # Les variantes recuperent les fautes ASR, puis une seule cascade
        # semantique est reappliquee sur leur ensemble. Un candidat trouve via
        # la variante brute ne peut ainsi contourner une ancre canonique telle
        # que sriracha, halal ou poche sous vide.
        for candidat in candidats_par_code.values():
            incompatibilites = _incompatibilites_semantiques(
                texte_semantique,
                str(candidat.get("libelle_normalise") or ""),
                mention.get("exclusions_produit", []),
            )
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
            candidat["raisons_resolution"] = resolution[
                "raisons_resolution"
            ]
            candidat["raisons"].extend(
                resolution["raisons_resolution"]
            )
            if raison_preference:
                candidat["raisons"].append(
                    raison_preference
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
            _selectionner_meilleur_candidat(candidats)
        )
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
        second = autres_candidats[0] if autres_candidats else None
        marge = (
            round(
                meilleur["score_global"]
                - second["score_global"],
                2,
            )
            if meilleur and second
            else 999.0
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
                    and meilleur["score_global"] >= 70
                    and meilleur.get("regle_selection")
                    in {
                        "cadencier_unique",
                        "cadencier_plus_vendu",
                    }
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

        ambigu = mention.get("ambigu", False)
        raisons_ambiguite = list(
            mention.get("raisons_ambiguite", [])
        )

        if (
            produit_fiable
            and meilleur
            and meilleur.get("quantite_resolue") is not None
            and meilleur.get("unite_resolue")
        ):
            raisons_ambiguite = [
                raison
                for raison in raisons_ambiguite
                if raison != "unite_absente_a_resoudre"
            ]
            raisons_ambiguite = [
                raison
                for raison in raisons_ambiguite
                if raison
                not in {
                    "repetition_transcription_supprimee",
                    "reformulation_proche_fusionnee",
                    "precision_quantite_rattachee",
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
        moitie = max(1, limite // 2)
        exposer([item for item in candidats if item["dans_cadencier_client"]][:moitie])
        exposer([item for item in candidats if not item["dans_cadencier_client"]][:moitie])
        exposer(candidats)

        resultats.append(
            {
                **mention,
                "variantes_recherche": variantes_recherche,
                "candidats": candidats_exposes,
                "produit_fiable": produit_fiable,
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
            }
        )

    return resultats
