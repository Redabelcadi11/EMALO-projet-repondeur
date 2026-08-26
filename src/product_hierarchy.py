"""Signaux secondaires bornés par un noyau produit lexicalement plausible.

Ce module ne génère aucun candidat et ne connaît aucune référence article.
Il ne peut donc jamais rendre un candidat plausible : les appelants lui
fournissent d'abord le sous-ensemble ayant franchi le filtre de noyau.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable


ATTRIBUTE_ONTOLOGY: dict[str, dict[str, tuple[str, ...]]] = {
    "fruits_exotiques": {
        "aliases": (
            "fruit exotique", "fruits exotiques",
            "fruit tropical", "fruits tropicaux",
        ),
        "members": (
            "ananas", "banane", "coco", "goyave", "kiwi", "litchi",
            "mangue", "papaye", "passion", "fruit de la passion",
        ),
        "incompatible": ("fruits_rouges",),
    },
    "fruits_rouges": {
        "aliases": ("fruit rouge", "fruits rouges"),
        "members": (
            "cassis", "cerise", "fraise", "framboise", "groseille",
            "mure", "myrtille",
        ),
        "incompatible": ("fruits_exotiques",),
    },
}

EXCLUSIVE_ATTRIBUTE_GROUPS: dict[str, tuple[str, ...]] = {
    "fruit": (
        "abricot", "ananas", "banane", "cassis", "cerise", "citron",
        "coco", "fraise", "framboise", "goyave", "groseille", "kiwi",
        "litchi", "mangue", "mure", "myrtille", "orange", "papaye",
        "passion", "peche", "pistache", "poire", "pomme",
    ),
    "forme_decoupe": (
        "brisure", "brisures", "concasse", "concassee", "copeau",
        "copeaux", "cube", "cubes", "emince", "emincee", "entier",
        "entiere", "entiers", "entieres", "fouette", "fouettee", "hache", "hachee", "miette",
        "miettes", "laniere", "lanieres", "petale", "petales", "poudre",
        "rape", "rapee", "rondelle", "rondelles", "semoule", "tranche",
        "tranchee",
    ),
    "type_farine": ("napolitaine", "t45", "t55", "t65", "t80"),
    "type_charcuterie": ("paleta",),
}

# Certains qualificatifs de forme/type sont suffisamment explicites pour que
# leur absence dans un libelle soit une contradiction, pas une simple perte de
# score. Cette table est volontairement semantique et extensible : elle ne
# contient ni code article ni reponse issue d'une commande ERP.
REQUIRED_EXPLICIT_ATTRIBUTES = {
    "cube", "cubes",
    "laniere", "lanieres", "napolitaine", "paleta", "poudre",
    "rape", "rapee", "rapes", "rapees",
    "rondelle", "rondelles",
}

# Noms de familles qui designent le produit principal. Ils servent uniquement
# a detecter qu'un mot demande est un ingredient secondaire d'un autre produit
# (``huile`` dans ``thon a l'huile``), jamais a generer un candidat.
PRIMARY_PRODUCT_FAMILIES: dict[str, tuple[str, ...]] = {
    "beurre": ("beurre",),
    "boeuf": ("boeuf",),
    "canard": ("canard",),
    "chocolat": ("chocolat", "chocolats"),
    "confiture": ("confiture", "confitures"),
    "cote": ("cote", "cotes", "cotelette", "cotelettes"),
    "coulis": ("coulis",),
    "creme": ("creme",),
    "croquette": ("croquette", "croquettes"),
    "farine": ("farine", "farines"),
    "filet": ("filet", "filets"),
    "fromage": (
        "fromage", "fromages", "emmental", "parmesan", "parmigiano",
        "mozzarella", "burrata", "feta", "mascarpone", "cheddar",
        "camembert", "comte", "gruyere", "gouda", "manchego",
    ),
    "glace": ("glace", "glaces", "glacee", "glacees", "sorbet", "sorbets"),
    "huile": ("huile", "huiles"),
    "jambon": ("jambon", "jambons", "paleta"),
    "jus": ("jus",),
    "lait": ("lait",),
    "miel": ("miel", "miels"),
    "muffin": ("muffin", "muffins"),
    "nuggets": ("nugget", "nuggets"),
    "noix": ("noix",),
    "oeuf": ("oeuf", "oeufs"),
    "olive": ("olive", "olives"),
    "pain": ("pain", "pains", "bun", "buns"),
    "pate": ("pate", "pates"),
    "pizza": ("pizza", "pizzas"),
    "poivre": ("poivre", "poivres"),
    "porc": ("porc",),
    "poulet": ("poulet",),
    "puree": ("puree", "purees"),
    "riz": ("riz",),
    "sauce": ("sauce", "sauces"),
    "sel": ("sel", "sels"),
    "sucre": ("sucre", "sucres"),
    "thon": ("thon",),
    "vinaigre": ("vinaigre", "vinaigres"),
    "vin": ("vin", "vins"),
}

NON_CORE_TOKENS = {
    "avec", "sans", "pour", "par", "dans", "comme", "fois", "un", "une",
    "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
    "dix", "litre", "litres", "kilo", "kilos", "kg", "gramme",
    "grammes", "piece", "pieces", "carton", "cartons", "colis", "boite",
    "boites", "poche", "poches", "pot", "pots", "sac", "sacs", "pack",
    "paquet", "paquets", "barquette", "barquettes", "bouteille",
    "bouteilles", "bidon", "bidons", "seau", "seaux", "pourcent",
    "petit", "petite", "grand", "grande", "format", "marque",
    "grain", "grains", "graine", "graines",
}

_UNIT_PATTERN = r"kilogrammes?|kilos?|kgs?|kg|k|grammes?|gr|g|litres?|l|cl|ml"
_COUNT_THEN_SIZE = re.compile(
    rf"(?<![\w.])(?P<count>\d+(?:\.\d+)?)\s*p?\s*(?:x|×|fois)\s*"
    rf"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT_PATTERN})(?![a-z])"
)
_SIZE_THEN_COUNT = re.compile(
    rf"(?<![\w.])(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT_PATTERN})\s*"
    rf"(?:x|×|fois)\s*(?P<count>\d+(?:\.\d+)?)\s*p?(?![a-z])"
)
_SIMPLE_SIZE = re.compile(
    rf"(?<![\w.])(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT_PATTERN})(?![a-z])"
)
_CONTAINER = (
    r"(?:pots?|plaques?|poches?|sacs?|bouteilles?|bidons?|boites?|cartons?|"
    r"colis|paquets?|barquettes?|seaux?)"
)
_EXPLICIT_UNIT_SIZE = re.compile(
    rf"\b{_CONTAINER}\b[^,;.]*?\b(?:de|d|en)\s+"
    rf"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT_PATTERN})(?![a-z])"
)
_LABEL_PIECE_PACK = re.compile(
    r"(?<!\w)(?:x|×)\s*(?P<count>\d+(?:\.\d+)?)\s*p(?:ieces?)?(?![a-z])"
)
_EXPLICIT_PIECE_SIZE = re.compile(
    rf"\b{_CONTAINER}\b[^,;.]*?\b(?:de|d|avec)\s+"
    r"(?P<count>\d+(?:\.\d+)?)\s*(?:p|pieces?)(?![a-z])"
)
_SIMPLE_PIECE_QUANTITY = re.compile(
    r"(?<![\w.])(?P<count>\d+(?:\.\d+)?)\s*(?:p|pieces?)(?![a-z])"
)


def normalize(text: str) -> str:
    value = "".join(
        char
        for char in unicodedata.normalize("NFKD", str(text or ""))
        if not unicodedata.combining(char)
    )
    return value.casefold().replace(",", ".")


def contains_expression(text: str, expression: str) -> bool:
    normalized = normalize(text)
    wanted = normalize(expression).strip()
    return bool(
        wanted and re.search(rf"(?<!\w){re.escape(wanted)}(?!\w)", normalized)
    )


def primary_product_family(text: str) -> str | None:
    """Retourne le premier noyau metier explicite d'une expression.

    Les parfums seuls (cafe, fraise, caramel...) ne sont volontairement pas
    des familles : ils peuvent heriter d'un contexte d'enumeration. A
    l'inverse, ``huile``, ``jus`` ou ``muffin`` sont des noyaux explicites qui
    ne peuvent pas etre renverses par un simple ingredient homonyme.
    """
    tokens = re.findall(r"[a-z0-9]+", normalize(text))
    if (
        any(token in {"glacee", "glacees", "sorbet", "sorbets"} for token in tokens)
        or (
            any(token in {"glace", "glaces"} for token in tokens)
            and "sucre" not in tokens
        )
    ):
        return "glace"
    for token in tokens:
        for family, aliases in PRIMARY_PRODUCT_FAMILIES.items():
            if token in aliases:
                return family
    return None


def _dimension_and_value(value: float, unit: str) -> tuple[str, float]:
    normalized = unit.casefold()
    if normalized in {
        "kg", "kgs", "kilogramme", "kilogrammes", "kilo", "kilos", "k",
    }:
        return "mass", value
    if normalized in {"g", "gr", "gramme", "grammes"}:
        return "mass", value / 1000.0
    if normalized in {"l", "litre", "litres"}:
        return "volume", value
    if normalized == "cl":
        return "volume", value / 100.0
    if normalized == "ml":
        return "volume", value / 1000.0
    raise ValueError(unit)


@dataclass(frozen=True)
class PhysicalMeasure:
    dimension: str
    unit_value: float
    multiplier: float = 1.0

    @property
    def total_value(self) -> float:
        return self.unit_value * self.multiplier


@dataclass(frozen=True)
class SpokenPhysicalConstraint:
    dimension: str
    unit_size: float | None


def extract_label_measures(text: str) -> list[PhysicalMeasure]:
    normalized = normalize(text)
    measures: list[PhysicalMeasure] = []
    occupied: list[tuple[int, int]] = []

    def overlaps(span: tuple[int, int]) -> bool:
        return any(span[0] < end and start < span[1] for start, end in occupied)

    for pattern in (_COUNT_THEN_SIZE, _SIZE_THEN_COUNT):
        for match in pattern.finditer(normalized):
            if overlaps(match.span()):
                continue
            dimension, value = _dimension_and_value(
                float(match.group("value")), match.group("unit")
            )
            measures.append(PhysicalMeasure(
                dimension, value, float(match.group("count"))
            ))
            occupied.append(match.span())
    for match in _SIMPLE_SIZE.finditer(normalized):
        if overlaps(match.span()):
            continue
        dimension, value = _dimension_and_value(
            float(match.group("value")), match.group("unit")
        )
        measures.append(PhysicalMeasure(dimension, value))
    for match in _LABEL_PIECE_PACK.finditer(normalized):
        measures.append(PhysicalMeasure("count", float(match.group("count"))))
    return measures


def extract_spoken_physical_constraint(text: str) -> SpokenPhysicalConstraint | None:
    normalized = normalize(text)
    explicit_piece = _EXPLICIT_PIECE_SIZE.search(normalized)
    if explicit_piece:
        return SpokenPhysicalConstraint(
            "count", float(explicit_piece.group("count"))
        )
    explicit = _EXPLICIT_UNIT_SIZE.search(normalized)
    if explicit:
        dimension, value = _dimension_and_value(
            float(explicit.group("value")), explicit.group("unit")
        )
        return SpokenPhysicalConstraint(dimension, value)
    composite = _COUNT_THEN_SIZE.search(normalized) or _SIZE_THEN_COUNT.search(normalized)
    if composite:
        dimension, value = _dimension_and_value(
            float(composite.group("value")), composite.group("unit")
        )
        return SpokenPhysicalConstraint(dimension, value)
    total = _SIMPLE_SIZE.search(normalized)
    if total:
        dimension, _ = _dimension_and_value(
            float(total.group("value")), total.group("unit")
        )
        # Une simple quantité totale ne révèle aucune taille unitaire.
        return SpokenPhysicalConstraint(dimension, None)
    piece_total = _SIMPLE_PIECE_QUANTITY.search(normalized)
    if piece_total:
        return SpokenPhysicalConstraint("count", None)
    return None


def core_anchors(
    mention_tokens: Iterable[str],
    label_tokens: Iterable[str],
    token_score: Callable[[str, str], float],
) -> set[str]:
    labels = tuple(label_tokens)
    return {
        token
        for token in mention_tokens
        if len(token) >= 3
        and token not in NON_CORE_TOKENS
        and not token.isdigit()
        and any(token_score(token, label) >= 90.0 for label in labels)
    }


def eligible_secondary_codes(
    candidates: Iterable[dict[str, Any]],
    mention_tokens: list[str],
    tokenize: Callable[[str], list[str]],
    token_score: Callable[[str, str], float],
) -> set[str]:
    rows: list[tuple[dict[str, Any], set[str]]] = []
    for candidate in candidates:
        anchors = core_anchors(
            mention_tokens,
            tokenize(str(candidate.get("libelle_normalise") or candidate.get("libelle_article") or "")),
            token_score,
        )
        if anchors:
            rows.append((candidate, anchors))
    if not rows:
        return set()
    best_text = max(float(row.get("score_texte") or 0.0) for row, _ in rows)
    threshold = max(30.0, best_text - 35.0)
    return {
        str(row.get("code_article") or "")
        for row, anchors in rows
        if anchors and float(row.get("score_texte") or 0.0) >= threshold
    }


def safe_physical_score(
    mention_text: str,
    label: str,
    *,
    eligible: bool,
) -> tuple[float, list[str]]:
    if not eligible:
        return 0.0, []
    spoken = extract_spoken_physical_constraint(mention_text)
    labels = extract_label_measures(label)
    if spoken is None or not labels:
        return 0.0, []
    same_dimension = [item for item in labels if item.dimension == spoken.dimension]
    if not same_dimension:
        return -12.0, ["conditionnement_dimension_contradictoire_apres_noyau"]
    if spoken.unit_size is None:
        return 0.0, []
    distances = [
        abs(item.unit_value - spoken.unit_size) / max(item.unit_value, spoken.unit_size, 1e-9)
        for item in same_dimension
    ]
    distance = min(distances)
    if distance <= 0.05:
        return 12.0, ["conditionnement_unitaire_compatible_apres_noyau"]
    penalty = -min(12.0, 4.0 + 10.0 * distance)
    return round(penalty, 2), ["conditionnement_unitaire_different_apres_noyau"]


def _explicit_categories(text: str) -> set[str]:
    return {
        category
        for category, definition in ATTRIBUTE_ONTOLOGY.items()
        if any(contains_expression(text, alias) for alias in definition["aliases"])
    }


def _candidate_categories(text: str) -> set[str]:
    return {
        category
        for category, definition in ATTRIBUTE_ONTOLOGY.items()
        if any(
            contains_expression(text, expression)
            for expression in (*definition["aliases"], *definition["members"])
        )
    }


def semantic_variant_score(
    mention_text: str,
    label: str,
    *,
    eligible: bool,
) -> tuple[float, list[str]]:
    if not eligible:
        return 0.0, []
    requested = _explicit_categories(mention_text)
    if not requested:
        return 0.0, []
    candidate = _candidate_categories(label)
    incompatible = {
        item
        for category in requested
        for item in ATTRIBUTE_ONTOLOGY[category]["incompatible"]
    }
    if candidate & incompatible:
        return -30.0, ["attribut_categorie_explicitement_contradictoire"]
    if candidate & requested:
        return 20.0, ["attribut_categorie_explicitement_compatible"]
    return 0.0, []


def explicit_attribute_conflicts(mention_text: str, label: str) -> list[str]:
    def canonical(group: str, attribute: str) -> str:
        # Les accords français d'une même découpe ne sont pas des variantes
        # contradictoires : ``haché`` et ``hachée`` décrivent la même forme.
        if group == "forme_decoupe":
            return {
                "brisure": "fragmente",
                "brisures": "fragmente",
                "concasse": "fragmente",
                "concassee": "fragmente",
                "copeaux": "copeau",
                "cubes": "cube",
                "emincee": "emince",
                "fouettee": "fouette",
                "hachee": "hache",
                "miette": "fragmente",
                "miettes": "fragmente",
                "lanieres": "laniere",
                "petale": "copeau",
                "petales": "copeau",
                "rape": "fragmente",
                "rapee": "fragmente",
                "rondelles": "rondelle",
                "semoule": "poudre",
                "tranchee": "tranche",
                "entiere": "entier",
                "entiers": "entier",
                "entieres": "entier",
            }.get(attribute, attribute)
        return attribute

    conflicts: list[str] = []
    for group, attributes in EXCLUSIVE_ATTRIBUTE_GROUPS.items():
        requested = {
            canonical(group, item)
            for item in attributes
            if contains_expression(mention_text, item)
        }
        offered = {
            canonical(group, item)
            for item in attributes
            if contains_expression(label, item)
        }
        if requested and offered and not (requested & offered):
            conflicts.append(f"attribut_explicite_contradictoire:{group}")
        attributs_requis = {
            canonical(group, item)
            for item in attributes
            if item in REQUIRED_EXPLICIT_ATTRIBUTES
            and contains_expression(mention_text, item)
        }
        if attributs_requis and not (attributs_requis & offered):
            conflicts.append(f"attribut_explicite_absent:{group}")

    mention_tokens = re.findall(r"[a-z0-9]+", normalize(mention_text))
    label_tokens = re.findall(r"[a-z0-9]+", normalize(label))

    # Un produit compose ne peut gagner uniquement parce que son ingredient
    # ou sa saveur reprend le produit principal prononce.
    wrappers = {
        "chips", "tartiflette", "pizza", "pizzas", "croquette",
        "croquettes", "glace", "glaces", "glacee", "glacees", "sorbet", "sorbets",
        "confiture", "confitures", "coulis", "puree", "purees",
        "muffin", "muffins", "biscuit", "biscuits",
    }
    canon_wrapper = {
        "pizzas": "pizza", "croquettes": "croquette",
        "glaces": "glace", "glacee": "glace", "glacees": "glace",
        "sorbets": "sorbet",
        "confitures": "confiture", "purees": "puree",
        "muffins": "muffin", "biscuits": "biscuit",
    }
    wrappers_label = {
        canon_wrapper.get(token, token)
        for token in label_tokens
        if token in wrappers
    }
    # ``sucre glace`` est une forme de sucre, pas une glace alimentaire.
    if "sucre" in label_tokens and not any(
        token in {"glacee", "glacees", "sorbet", "sorbets"}
        for token in label_tokens
    ):
        wrappers_label.discard("glace")
    wrappers_mention = {
        canon_wrapper.get(token, token)
        for token in mention_tokens
        if token in wrappers
    }
    famille_demandee = primary_product_family(mention_text)
    famille_offerte = primary_product_family(label)
    if (
        famille_demandee
        and wrappers_label
        and not (wrappers_label & wrappers_mention)
    ):
        partages = {
            token for token in mention_tokens
            if len(token) >= 4
            and token in set(label_tokens)
            and token not in NON_CORE_TOKENS
        }
        if partages:
            conflicts.append("noyau_produit_compose_contradictoire")

    if (
        famille_demandee
        and famille_offerte
        and famille_demandee != famille_offerte
    ):
        conflicts.append("noyau_produit_principal_contradictoire")

    # ``oeuf entier liquide`` est un seul produit dont les deux attributs
    # sont obligatoires. Un blanc, un jaune ou un oeuf coquille n'est pas une
    # variante acceptable, meme s'il est frequent dans le cadencier.
    if contains_expression(mention_text, "oeuf"):
        demande_liquide = contains_expression(mention_text, "liquide")
        demande_entier = contains_expression(mention_text, "entier")
        if demande_liquide and not contains_expression(label, "liquide"):
            conflicts.append("etat_oeuf_liquide_explicite_absent")
        if demande_entier and not contains_expression(label, "entier"):
            conflicts.append("partie_oeuf_entier_explicite_absente")
        if demande_entier and any(
            contains_expression(label, partie) for partie in ("blanc", "jaune")
        ):
            conflicts.append("partie_oeuf_explicite_contradictoire")

    # Si le client dit explicitement ``fromage de brebis/chevre/...``, un
    # fromage generique d'un autre lait ne peut gagner par son historique.
    if contains_expression(mention_text, "fromage"):
        types_lait = {
            "brebis": ("brebis", "ovine"),
            "chevre": ("chevre",),
            "vache": ("vache",),
            "bufflonne": ("bufflonne", "bufala"),
        }
        demandes = {
            famille
            for famille, termes in types_lait.items()
            if any(contains_expression(mention_text, terme) for terme in termes)
        }
        if demandes and not any(
            contains_expression(label, terme)
            for famille in demandes
            for terme in types_lait[famille]
        ):
            conflicts.append("type_lait_fromage_explicite_absent")

    return conflicts


def residual_variant_score(
    mention_tokens: Iterable[str],
    label_tokens: Iterable[str],
    core_tokens: set[str],
    token_score: Callable[[str, str], float],
) -> float:
    residual = [
        token for token in mention_tokens
        if token not in core_tokens and token not in NON_CORE_TOKENS and len(token) >= 3
    ]
    labels = list(label_tokens)
    if not residual or not labels:
        return 0.0
    scores = [max((token_score(token, label) for label in labels), default=0.0) for token in residual]
    return round(max(scores), 2)


def reappro_fallback_bonuses(
    candidates: Iterable[dict[str, Any]],
    mention_tokens: list[str],
    tokenize: Callable[[str], list[str]],
    token_score: Callable[[str, str], float],
    *,
    allow_asr_variant: bool,
    allow_explicit_attribute: bool,
) -> dict[str, tuple[float, str]]:
    """Retourne des bonus Réapro uniquement à l'intérieur d'une famille sûre.

    Le noyau est établi lexicalement avant d'examiner la variante. Un score de
    variante ou un attribut ne peut donc jamais faire entrer un article d'une
    autre famille dans la compétition.
    """
    rows = list(candidates)
    mention_text = " ".join(mention_tokens)
    anchors_by_code: dict[str, set[str]] = {}
    for candidate in rows:
        code = str(candidate.get("code_article") or "")
        anchors_by_code[code] = core_anchors(
            mention_tokens,
            tokenize(str(candidate.get("libelle_normalise") or "")),
            token_score,
        )

    cadence = [
        candidate for candidate in rows
        if candidate.get("dans_cadencier_client")
        and anchors_by_code.get(str(candidate.get("code_article") or ""))
    ]
    fallback_catalogue = [
        candidate for candidate in rows
        if candidate.get("source_recherche")
        in {"catalogue_reappro", "catalogue_global"}
        and anchors_by_code.get(str(candidate.get("code_article") or ""))
        and candidate.get("semantiquement_compatible", True)
    ]
    bonuses: dict[str, tuple[float, str]] = {}
    if not fallback_catalogue:
        return bonuses

    requested_by_group = {
        group: {
            attribute
            for attribute in attributes
            if contains_expression(mention_text, attribute)
        }
        for group, attributes in EXCLUSIVE_ATTRIBUTE_GROUPS.items()
    }
    requested_by_group = {
        group: requested
        for group, requested in requested_by_group.items()
        if requested
    }

    for candidate in fallback_catalogue:
        code = str(candidate.get("code_article") or "")
        anchors = anchors_by_code[code]
        same_family_cadence = [
            item for item in cadence
            if anchors & anchors_by_code.get(
                str(item.get("code_article") or ""), set()
            )
        ]
        label = str(candidate.get("libelle_normalise") or "")

        if allow_explicit_attribute and requested_by_group:
            candidate_matches_all = all(
                any(contains_expression(label, attr) for attr in requested)
                for requested in requested_by_group.values()
            )
            cadence_has_compatible = any(
                not explicit_attribute_conflicts(
                    mention_text,
                    str(item.get("libelle_normalise") or ""),
                )
                and all(
                    any(
                        contains_expression(
                            str(item.get("libelle_normalise") or ""), attr
                        )
                        for attr in requested
                    )
                    for requested in requested_by_group.values()
                )
                for item in same_family_cadence
            )
            meilleur_score_cadence = max(
                (
                    float(item.get("score_texte") or 0.0)
                    for item in same_family_cadence
                ),
                default=0.0,
            )
            candidat_deja_plausible = bool(
                same_family_cadence
                and float(candidate.get("score_texte") or 0.0)
                >= meilleur_score_cadence - 5.0
            )
            if (
                candidate_matches_all
                and not cadence_has_compatible
                and candidat_deja_plausible
            ):
                bonuses[code] = (
                    125.0,
                    "fallback_reappro_attribut_explicite_intra_famille",
                )
                continue

        if allow_asr_variant and same_family_cadence:
            same_family_catalogue = [
                item for item in fallback_catalogue
                if anchors & anchors_by_code.get(
                    str(item.get("code_article") or ""), set()
                )
            ]
            residuals = [
                token for token in mention_tokens
                if token not in anchors
                and token not in NON_CORE_TOKENS
                and len(token) >= 3
            ]
            # La phonétique n'est justifiée que pour une unique variante
            # réellement incomprise. Une variante déjà lisible dans la
            # famille (ex. ``creme liquide``) doit continuer à être traitée
            # par le matching lexical normal, jamais par un bonus de secours.
            if len(residuals) != 1:
                continue
            # Les variantes descriptives longues restent lisibles par le
            # moteur lexical. Ce secours vise seulement les très courts
            # fragments ASR opaques (par exemple ``xrf``), pour lesquels
            # une phonétique intra-famille apporte une information réelle.
            if len(residuals[0]) > 3:
                continue
            meilleur_score_residuel = max(
                (
                    token_score(residuals[0], token)
                    for item in [*same_family_cadence, *same_family_catalogue]
                    for token in tokenize(
                        str(item.get("libelle_normalise") or "")
                    )
                ),
                default=0.0,
            )
            if meilleur_score_residuel >= 70.0:
                continue
            candidate_variant = residual_variant_score(
                mention_tokens,
                tokenize(label),
                anchors,
                token_score,
            )
            cadence_variant = max(
                residual_variant_score(
                    mention_tokens,
                    tokenize(str(item.get("libelle_normalise") or "")),
                    anchors,
                    token_score,
                )
                for item in same_family_cadence
            )
            if candidate_variant >= 45.0 and candidate_variant >= cadence_variant + 15.0:
                source = str(candidate.get("source_recherche") or "")
                bonuses[code] = (
                    125.0,
                    (
                        "fallback_catalogue_variante_phonetique_intra_famille"
                        if source == "catalogue_global"
                        else "fallback_reappro_variante_phonetique_intra_famille"
                    ),
                )
    return bonuses
