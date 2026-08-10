from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from .normalisation import (
    contient_sequence_tokens,
    normaliser_texte,
    simplifier_nom_client,
    tokens_normalises,
)


MARQUEURS_FIN_PRESENTATION_CLIENT = [
    "je voudrais",
    "je souhaite",
    "je souhaiterais",
    "je commande",
    "il me faudrait",
    "il me faudra",
    "il nous faudrait",
    "il nous faudra",
    "c est pour faire un complement",
    "c est pour faire",
    "ce sera pour faire un complement",
    "ce sera pour faire",
    "je vais rajouter",
    "je vais ajouter",
    "a l appareil",
    "a lappareil",
    "ce sera",
    "ca sera",
    "pour demain",
    "pour apres demain",
    "pour aujourd hui",
    "pour ce soir",
    "merci",
]

SEUIL_PRESSELECTION_NOM_OU_CODE = 25.0
SEUIL_DECISION_CLIENT_FUZZY = 88.0
SEUIL_ECART_CLIENT_FUZZY = 8.0
GENERIC_ALIAS_TOKENS = {
    "le",
    "la",
    "les",
    "de",
    "du",
    "des",
    "d",
    "au",
    "aux",
    "a",
    "l",
    "restaurant",
    "resto",
    "hotel",
    "bar",
    "brasserie",
    "bistrot",
    "sarl",
    "sas",
    "sasu",
    "eurl",
    "societe",
    "appareil",
}
ADDRESS_GENERIC_TOKENS = {
    "de",
    "du",
    "des",
    "la",
    "le",
    "les",
    "l",
    "rue",
    "avenue",
    "av",
    "boulevard",
    "bd",
    "allee",
    "all",
    "chemin",
    "route",
    "rt",
    "impasse",
    "place",
    "pl",
    "quai",
    "zone",
    "zac",
    "za",
    "bat",
    "batiment",
    "lot",
    "residence",
}


def normaliser_telephone(
    valeur: Any,
) -> str:
    brut = str(valeur or "").strip()
    if not brut:
        return ""

    chiffres = re.sub(r"\D+", "", brut)
    if not chiffres:
        return ""

    if chiffres.startswith("0033") and len(chiffres) >= 12:
        chiffres = "0" + chiffres[4:]
    elif chiffres.startswith("33") and len(chiffres) >= 11:
        chiffres = "0" + chiffres[2:]

    return chiffres


def normaliser_telephones(
    valeur: Any,
) -> list[str]:
    brut = str(valeur or "").strip()
    if not brut:
        return []

    motifs = re.findall(
        r"(?:\+|00)?33[\s.\-]?[1-9](?:[\s.\-]?\d{2}){4}|0[1-9](?:[\s.\-]?\d{2}){4}",
        brut,
    )
    if not motifs:
        telephone = normaliser_telephone(brut)
        return [telephone] if telephone else []

    telephones = {
        normaliser_telephone(motif)
        for motif in motifs
        if normaliser_telephone(motif)
    }
    return sorted(telephones)


def charger_variantes_clients(
    chemin_variantes: Path,
) -> dict[str, list[str]]:
    if not chemin_variantes.exists():
        return {}

    donnees = json.loads(
        chemin_variantes.read_text(
            encoding="utf-8"
        )
    )

    variantes: dict[str, list[str]] = {}

    for code_client, valeurs in (donnees or {}).items():
        code = str(code_client or "").strip()

        if not code:
            continue

        if isinstance(valeurs, str):
            liste = [valeurs]
        else:
            liste = [
                str(valeur or "").strip()
                for valeur in (valeurs or [])
            ]

        liste = [
            variante
            for variante in liste
            if variante
        ]

        if liste:
            variantes[code] = liste

    return variantes


def charger_telephones_clients(
    chemin_telephones: Path,
) -> dict[str, list[str]]:
    if not chemin_telephones.exists():
        return {}

    donnees = json.loads(
        chemin_telephones.read_text(
            encoding="utf-8"
        )
    )

    telephones_par_code: dict[str, list[str]] = {}

    for code_client, valeurs in (donnees or {}).items():
        code = str(code_client or "").strip()
        if not code:
            continue

        valeurs_liste = [valeurs] if isinstance(valeurs, str) else list(valeurs or [])
        telephones = {
            telephone
            for valeur in valeurs_liste
            for telephone in normaliser_telephones(valeur)
        }
        if telephones:
            telephones_par_code[code] = sorted(telephones)

    return telephones_par_code


def enrichir_alias_avec_variantes(
    clients: list[dict[str, Any]],
    variantes_par_code: dict[str, list[str]],
) -> None:
    if not variantes_par_code:
        return

    for client in clients:
        code_client = str(
            client.get("code_client", "")
        ).strip()

        variantes = variantes_par_code.get(code_client)

        if not variantes:
            continue

        aliases = {
            str(alias).strip()
            for alias in client.get("aliases", [])
            if str(alias).strip()
        }

        for variante in variantes:
            aliases.add(
                normaliser_texte(variante)
            )
            aliases.add(
                simplifier_nom_client(variante)
            )

        client["aliases"] = sorted(
            alias
            for alias in aliases
            if alias
        )


def enrichir_clients_avec_telephones(
    clients: list[dict[str, Any]],
    telephones_par_code: dict[str, list[str]],
) -> None:
    if not telephones_par_code:
        return

    proprietaires_config: dict[str, set[str]] = {}
    for code_client, valeurs in telephones_par_code.items():
        for valeur in valeurs:
            telephone = normaliser_telephone(valeur)
            if telephone:
                proprietaires_config.setdefault(
                    telephone,
                    set(),
                ).add(str(code_client).strip())

    for client in clients:
        code_client = str(
            client.get("code_client", "")
        ).strip()

        telephones_config = telephones_par_code.get(code_client)
        telephones = {
            telephone
            for valeur in client.get("telephones", [])
            for telephone in normaliser_telephones(valeur)
            if (
                telephone not in proprietaires_config
                or code_client in proprietaires_config[telephone]
            )
        }
        telephones.update(telephones_config or [])
        client["telephones"] = sorted(
            telephone
            for telephone in telephones
            if telephone
        )


def extraire_zone_presentation_client(
    transcription: str,
) -> str:
    texte = normaliser_texte(transcription)

    positions = [
        texte.find(marqueur)
        for marqueur in MARQUEURS_FIN_PRESENTATION_CLIENT
        if texte.find(marqueur) != -1
    ]

    if positions:
        texte = texte[: min(positions)]

    motif_premiere_qte = re.search(
        (
            r"\b\d+(?:\.\d+)?\s+"
            r"(?:kg|kilo|kilos|kilogramme|kilogrammes|"
            r"gramme|grammes|litre|litres|boite|boites|"
            r"carton|cartons|colis|piece|pieces|palette|palettes)\b"
        ),
        texte,
    )

    if motif_premiere_qte:
        texte = texte[: motif_premiere_qte.start()]

    return texte.strip()


def client_est_mentionne(
    zone_client: str,
) -> bool:
    tokens = tokens_normalises(zone_client)
    tokens_significatifs = [
        token
        for token in tokens
        if token
        not in {
            "bonjour",
            "bonsoir",
            "salut",
            "c",
            "est",
            "je",
            "suis",
            "le",
            "la",
            "les",
            "client",
            "de",
        }
    ]

    if any(
        any(caractere.isdigit() for caractere in token)
        and len(token) >= 3
        for token in tokens_significatifs
    ):
        return True

    if any(
        len(token) >= 4
        for token in tokens_significatifs
    ):
        return True

    return False


def _a_raison_exacte(
    raisons: list[str],
    prefixe: str,
) -> bool:
    return any(
        raison.startswith(prefixe)
        for raison in raisons
    )


def _extraire_zones_recherche(
    transcription: str,
) -> dict[str, str]:
    presentation = extraire_zone_presentation_client(
        transcription
    )
    conclusion = ""
    segments = [
        normaliser_texte(segment)
        for segment in re.split(r"[.!?;]+", transcription)
        if normaliser_texte(segment)
    ]
    for segment in reversed(segments[-3:]):
        if (
            re.search(r"\bpour\s+(?:le|la|les|l)\b", segment)
            and re.search(
                r"\b(?:merci|au revoir|restaurant|client|commande)\b",
                segment,
            )
        ):
            conclusion = segment
            break

    texte_complet = normaliser_texte(transcription)
    conclusion_apres_merci = re.search(
        r"\bmerci\s+(?:(?:pour|de\s+chez)\s+)?"
        r"(?:(?:le|la|les|l)\s+)?"
        r"(?:restaurant|resto|bar|hotel|bistrot|brasserie|snack)\b"
        r".{0,80}$",
        texte_complet,
    )
    if conclusion_apres_merci:
        conclusion = conclusion_apres_merci.group(0)

    zone_client_explicite = " ".join(
        morceau
        for morceau in (presentation, conclusion)
        if morceau
    ).strip()
    return {
        "presentation": presentation,
        # Ne jamais rechercher un client dans la liste des produits. Seules
        # la presentation et une eventuelle conclusion explicite comptent.
        "transcription": zone_client_explicite,
    }


def _cle_phonetique_nom(texte: str) -> str:
    """Cle volontairement simple pour les noms propres dictes au telephone."""
    tokens = [
        token
        for token in tokens_normalises(texte)
        if token not in GENERIC_ALIAS_TOKENS
        and token not in {
            "bonjour", "bonsoir", "salut", "c", "est", "chez",
            "pour", "commande", "aujourd", "hui", "demain",
        }
    ]
    valeur = "".join(tokens)
    valeur = valeur.replace("eau", "o").replace("au", "o")
    valeur = valeur.replace("ph", "f").replace("qu", "k")
    valeur = valeur.replace("ck", "k").replace("ch", "sh")
    valeur = valeur.replace("y", "i").replace("q", "k")
    valeur = valeur.replace("c", "k").replace("z", "s")
    valeur = valeur.replace("h", "")
    valeur = re.sub(r"(.)\1+", r"\1", valeur)
    return valeur


def _cle_recence_client(
    candidat: dict[str, Any],
) -> tuple[int, int, int, int, float, int]:
    return (
        int(candidat.get("nb_commandes_recentes", 0)),
        int(candidat.get("derniere_vente_ordinal", -1)),
        int(candidat.get("nb_commandes_total", 0)),
        int(candidat.get("nb_lignes_ventes_recentes", 0)),
        float(candidat.get("montant_recent", 0.0)),
        int(candidat.get("nb_lignes_ventes", 0)),
    )


def _departager_candidats_homonymes(
    candidats: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    if not candidats:
        return None, ["aucun_candidat_client"]

    if len(candidats) == 1:
        return candidats[0], ["candidat_unique"]

    candidats_code = [
        candidat
        for candidat in candidats
        if candidat.get("match_code_exact")
    ]
    if len(candidats_code) == 1:
        return candidats_code[0], [
            "departage_code_exact"
        ]
    if candidats_code:
        candidats = candidats_code

    candidats_nom = [
        candidat
        for candidat in candidats
        if candidat.get("match_nom_exact")
    ]
    if len(candidats_nom) == 1:
        return candidats_nom[0], [
            "departage_nom_exact"
        ]
    if candidats_nom:
        candidats = candidats_nom

    candidats_adresse = [
        candidat
        for candidat in candidats
        if candidat.get("match_adresse_exact")
    ]
    if len(candidats_adresse) == 1:
        return candidats_adresse[0], [
            "departage_adresse_exacte"
        ]
    if candidats_adresse:
        candidats = candidats_adresse

    candidats_ville = [
        candidat
        for candidat in candidats
        if candidat.get("match_ville_exact")
    ]
    if len(candidats_ville) == 1:
        return candidats_ville[0], [
            "departage_ville_exacte"
        ]
    if candidats_ville:
        candidats = candidats_ville

    # Une meme enseigne peut subsister sous deux codes (ancien code sans
    # historique et code actif avec cadencier). A preuves de nom/adresse
    # egales, le code possedant le cadencier est le seul exploitable pour la
    # suite du traitement.
    candidats_avec_cadencier = [
        candidat
        for candidat in candidats
        if int(candidat.get("cadencier_articles", 0) or 0) > 0
    ]
    if len(candidats_avec_cadencier) == 1:
        return candidats_avec_cadencier[0], [
            "departage_cadencier_disponible"
        ]
    if candidats_avec_cadencier:
        candidats = candidats_avec_cadencier

    candidats_tries = sorted(
        candidats,
        key=_cle_recence_client,
        reverse=True,
    )

    if len(candidats_tries) == 1:
        return candidats_tries[0], [
            "departage_recence_ventes"
        ]

    if _cle_recence_client(
        candidats_tries[0]
    ) != _cle_recence_client(candidats_tries[1]):
        return candidats_tries[0], [
            "departage_recence_ventes"
        ]

    return None, ["ambiguite_homonymes"]


def _calculer_score_nom_alias(
    alias: str,
    zone_normale: str,
    zone_simplifiee: str,
    tokens_zone_normale: list[str],
    tokens_zone_simplifiee: list[str],
) -> tuple[float, str]:
    alias_normalise = normaliser_texte(alias)
    alias_simplifie = simplifier_nom_client(alias)

    variantes = [
        (
            alias_normalise,
            tokens_zone_normale,
            zone_normale,
            "alias_normalise",
        ),
        (
            alias_simplifie,
            tokens_zone_simplifiee,
            zone_simplifiee,
            "alias_simplifie",
        ),
    ]

    meilleur_score = 0.0
    meilleure_raison = "aucun_match_nom"

    for (
        texte_alias,
        tokens_zone,
        texte_zone,
        type_alias,
    ) in variantes:
        tokens_alias = texte_alias.split()

        if not tokens_alias:
            continue

        if len(texte_alias) < 4:
            continue

        if all(
            len(token) < 3
            for token in tokens_alias
        ):
            continue

        tokens_alias_utiles = [
            token
            for token in tokens_alias
            if token not in GENERIC_ALIAS_TOKENS
        ]

        if not tokens_alias_utiles:
            continue

        texte_alias_utile = " ".join(tokens_alias_utiles)

        if len(texte_alias_utile) < 4:
            continue

        if contient_sequence_tokens(
            tokens_zone,
            tokens_alias_utiles,
        ):
            return 100.0, (
                f"match_exact_sequence:{type_alias}:"
                f"{texte_alias_utile}"
            )

        tokens_zone_sans_particules = [
            token
            for token in tokens_zone
            if token not in GENERIC_ALIAS_TOKENS
        ]
        if contient_sequence_tokens(
            tokens_zone_sans_particules,
            tokens_alias_utiles,
        ):
            return 100.0, (
                f"match_exact_sequence:souple:{type_alias}:"
                f"{texte_alias_utile}"
            )

        cle_alias = _cle_phonetique_nom(texte_alias_utile)
        tokens_zone_phonetiques = [
            token
            for token in tokens_zone
            if token not in GENERIC_ALIAS_TOKENS
            and token not in {
                "bonjour", "bonsoir", "salut", "c", "est", "chez",
                "pour", "commande", "aujourd", "hui", "demain",
            }
        ]
        max_taille = min(
            4,
            max(1, len(tokens_alias_utiles) + 1),
        )
        candidats_phonetiques = {
            _cle_phonetique_nom(
                " ".join(tokens_zone_phonetiques[index:index + taille])
            )
            for taille in range(1, max_taille + 1)
            for index in range(
                0,
                max(0, len(tokens_zone_phonetiques) - taille + 1),
            )
        }
        candidats_phonetiques.discard("")
        if cle_alias and cle_alias in candidats_phonetiques:
            return 100.0, (
                f"match_phonetique_exact:{type_alias}:"
                f"{texte_alias_utile}"
            )
        score_phonetique = max(
            (
                float(fuzz.ratio(cle_alias, candidat))
                for candidat in candidats_phonetiques
            ),
            default=0.0,
        )

        score_token = 0.0

        for token_alias in tokens_alias_utiles:
            meilleur_token = max(
                (
                    fuzz.ratio(
                        token_alias,
                        token_zone,
                    )
                    for token_zone in tokens_zone
                ),
                default=0.0,
            )

            if meilleur_token >= 90:
                score_token += 1.0
            elif meilleur_token >= 80:
                score_token += 0.6

        ratio_token = min(
            1.0,
            score_token / len(tokens_alias_utiles),
        )

        score_tokens = ratio_token * 100.0

        score_fuzzy = max(
            float(
                fuzz.token_set_ratio(
                    texte_alias_utile,
                    texte_zone,
                )
            ),
            float(
                fuzz.token_sort_ratio(
                    texte_alias_utile,
                    texte_zone,
                )
            ),
        )

        # Sans recouvrement lexical, on évite de sur-noter
        # les sous-chaînes (ex: ranch dans affranchis).
        if ratio_token == 0:
            score_fuzzy = min(score_fuzzy, 35.0)

        score = max(
            score_tokens,
            (0.65 * score_tokens)
            + (0.35 * score_fuzzy),
        )
        if len(tokens_alias_utiles) == 1:
            score = min(score, 88.0)
        if score_phonetique >= 92.0:
            score = max(
                score,
                96.0 if len(tokens_alias_utiles) >= 2 else 88.0,
            )
            meilleure_raison = (
                f"match_phonetique:{type_alias}:{texte_alias}"
            )

        if score > meilleur_score:
            meilleur_score = score
            if score_phonetique < 92.0:
                meilleure_raison = (
                    f"match_fuzzy:{type_alias}:{texte_alias}"
                )

    return round(meilleur_score, 2), meilleure_raison


def calculer_score_nom_client(
    zone_client: str,
    client: dict[str, Any],
) -> tuple[float, list[str]]:
    zone_normale = normaliser_texte(zone_client)
    zone_simplifiee = simplifier_nom_client(zone_client)
    tokens_zone_normale = tokens_normalises(zone_normale)
    tokens_zone_simplifiee = tokens_normalises(
        zone_simplifiee
    )

    meilleur_score = 0.0
    raisons: list[str] = []

    for alias in client.get("aliases", []):
        score_alias, raison = _calculer_score_nom_alias(
            alias=alias,
            zone_normale=zone_normale,
            zone_simplifiee=zone_simplifiee,
            tokens_zone_normale=tokens_zone_normale,
            tokens_zone_simplifiee=tokens_zone_simplifiee,
        )

        if score_alias > meilleur_score:
            meilleur_score = score_alias
            raisons = [raison]

    return round(meilleur_score, 2), raisons


def calculer_score_code_client(
    zone_client: str,
    code_client: str,
) -> tuple[float, list[str]]:
    zone_normale = normaliser_texte(zone_client)
    tokens_zone = set(
        tokens_normalises(zone_normale)
    )
    code_normalise = normaliser_texte(code_client)

    if not code_normalise:
        return 0.0, []

    raisons: list[str] = []

    if re.fullmatch(r"[a-z]+", code_normalise) and not re.search(
        rf"\bcode\s+client\s+{re.escape(code_normalise)}\b",
        zone_normale,
    ):
        return 0.0, []

    if (
        code_normalise.isdigit()
        and len(code_normalise) <= 3
        and not re.search(
            rf"\bcode\s+client\s+{re.escape(code_normalise)}\b",
            zone_normale,
        )
    ):
        return 0.0, []

    if code_normalise in tokens_zone:
        raisons.append("code_exact")
        return 100.0, raisons

    prefixe_alphanum = re.match(
        r"^([a-z0-9]{3,})",
        code_normalise,
    )

    if prefixe_alphanum:
        prefixe = prefixe_alphanum.group(1)

        if prefixe in tokens_zone:
            raisons.append("code_prefixe_exact")
            return 90.0, raisons

    prefixe_numerique = re.match(
        r"^(\d{3,})",
        code_normalise,
    )

    if (
        prefixe_numerique
        and prefixe_numerique.group(1) in tokens_zone
    ):
        raisons.append("code_prefixe_numerique")
        return 85.0, raisons

    return 0.0, []


def _code_client_acceptable_hors_presentation(
    code_client: str,
) -> bool:
    code_normalise = normaliser_texte(code_client)

    if len(code_normalise) < 4:
        return False

    if code_normalise.isdigit():
        return False

    contient_lettre = bool(re.search(r"[a-z]", code_normalise))
    contient_chiffre = bool(re.search(r"\d", code_normalise))

    return contient_lettre and contient_chiffre


def calculer_score_ville(
    zone_client: str,
    ville_client: str,
) -> tuple[float, list[str]]:
    zone_normale = normaliser_texte(zone_client)
    ville_normale = normaliser_texte(ville_client)

    if not ville_normale:
        return 0.0, []

    if ville_normale in zone_normale:
        return 100.0, [
            f"ville_mentionnee:{ville_normale}"
        ]

    tokens_zone = tokens_normalises(zone_normale)
    tokens_ville = tokens_normalises(ville_normale)

    if not tokens_ville:
        return 0.0, []

    for token_ville in tokens_ville:
        if len(token_ville) < 5:
            continue

        meilleur = max(
            (
                max(
                    fuzz.ratio(token_ville, token_zone),
                    fuzz.ratio(
                        _cle_phonetique_nom(token_ville),
                        _cle_phonetique_nom(token_zone),
                    ),
                )
                for token_zone in tokens_zone
            ),
            default=0.0,
        )

        if meilleur >= 90:
            return 85.0, [
                f"ville_approx:{token_ville}"
            ]

    return 0.0, []


def calculer_score_adresse(
    zone_client: str,
    adresse_1: str,
    adresse_2: str,
    code_postal: str,
) -> tuple[float, list[str]]:
    zone_normale = normaliser_texte(zone_client)
    tokens_zone = tokens_normalises(zone_normale)
    tokens_zone_utiles = [
        token
        for token in tokens_zone
        if token not in ADDRESS_GENERIC_TOKENS
    ]

    variantes = [
        normaliser_texte(adresse_1),
        normaliser_texte(adresse_2),
        normaliser_texte(
            " ".join(
                morceau
                for morceau in [adresse_1, adresse_2]
                if morceau
            )
        ),
    ]

    if code_postal:
        variantes.append(
            normaliser_texte(code_postal)
        )
        variantes.append(
            normaliser_texte(
                " ".join(
                    morceau
                    for morceau in [
                        adresse_1,
                        adresse_2,
                        code_postal,
                    ]
                    if morceau
                )
            )
        )

    meilleur_score = 0.0
    meilleures_raisons: list[str] = []

    for variante in variantes:
        if not variante:
            continue

        tokens_variante = [
            token
            for token in tokens_normalises(variante)
            if token not in ADDRESS_GENERIC_TOKENS
            and (
                len(token) >= 3
                or (token.isdigit() and len(token) >= 2)
            )
        ]

        if not tokens_variante:
            continue

        if contient_sequence_tokens(
            tokens_zone_utiles,
            tokens_variante,
        ):
            return 100.0, [
                f"adresse_exacte:{' '.join(tokens_variante)}"
            ]

        score_token = 0.0

        for token_variante in tokens_variante:
            meilleur_token = max(
                (
                    max(
                        fuzz.ratio(token_variante, token_zone),
                        fuzz.ratio(
                            _cle_phonetique_nom(token_variante),
                            _cle_phonetique_nom(token_zone),
                        ),
                    )
                    for token_zone in tokens_zone
                ),
                default=0.0,
            )

            if meilleur_token >= 90:
                score_token += 1.0
            elif meilleur_token >= 80:
                score_token += 0.6
            elif meilleur_token >= 70:
                score_token += 0.3

        ratio_token = min(
            1.0,
            score_token / len(tokens_variante),
        )
        score_fuzzy = max(
            float(
                fuzz.token_set_ratio(
                    " ".join(tokens_variante),
                    zone_normale,
                )
            ),
            float(
                fuzz.token_sort_ratio(
                    " ".join(tokens_variante),
                    zone_normale,
                )
            ),
        )

        if ratio_token == 0:
            score_fuzzy = min(score_fuzzy, 35.0)

        score = max(
            ratio_token * 100.0,
            (ratio_token * 65.0)
            + (score_fuzzy * 0.35),
        )

        if score > meilleur_score:
            meilleur_score = score
            meilleures_raisons = [
                f"adresse_fuzzy:{' '.join(tokens_variante)}"
            ]

    return round(meilleur_score, 2), meilleures_raisons


def calculer_score_cadencier(
    mentions_produits: list[dict[str, Any]],
    produits_client: list[dict[str, Any]],
) -> tuple[float, list[str], list[dict[str, Any]]]:
    mentions = [
        normaliser_texte(
            mention.get("texte_produit", "")
        )
        for mention in mentions_produits
    ]
    mentions = [
        mention
        for mention in mentions
        if mention
    ]

    if not mentions:
        return 0.0, ["aucune_mention_produit"], []

    if not produits_client:
        return 0.0, ["cadencier_absent"], []

    details: list[dict[str, Any]] = []
    meilleurs_scores: list[float] = []

    for mention in mentions:
        meilleur = {
            "mention": mention,
            "score": 0.0,
            "code_article": None,
            "libelle_article": None,
        }

        for produit in produits_client:
            score = float(
                fuzz.token_set_ratio(
                    mention,
                    produit["libelle_normalise"],
                )
            )

            if score > meilleur["score"]:
                meilleur = {
                    "mention": mention,
                    "score": round(score, 2),
                    "code_article": produit[
                        "code_article"
                    ],
                    "libelle_article": produit[
                        "libelle_article"
                    ],
                }

        meilleurs_scores.append(
            float(meilleur["score"])
        )
        details.append(meilleur)

    moyenne = sum(meilleurs_scores) / len(
        meilleurs_scores
    )
    nb_forts = sum(
        1
        for score in meilleurs_scores
        if score >= 85
    )
    nb_moyens = sum(
        1
        for score in meilleurs_scores
        if score >= 70
    )

    couverture = nb_moyens / len(meilleurs_scores)

    score_cadencier = min(
        100.0,
        (moyenne * 0.7) + (couverture * 30),
    )

    raisons = [
        f"cadencier_moyenne={round(moyenne, 2)}",
        (
            "cadencier_mentions_fortes="
            f"{nb_forts}/{len(meilleurs_scores)}"
        ),
        (
            "cadencier_mentions_couvertes="
            f"{nb_moyens}/{len(meilleurs_scores)}"
        ),
    ]

    return round(score_cadencier, 2), raisons, details


def _preselectionner_par_nom_ou_code(
    transcription: str,
    clients: list[dict[str, Any]],
    limite_preselection: int,
    telephone_appel: str | None = None,
) -> list[dict[str, Any]]:
    zones = _extraire_zones_recherche(
        transcription
    )
    telephone_normalise = normaliser_telephone(
        telephone_appel
    )

    candidats: list[dict[str, Any]] = []

    for client in clients:
        score_nom_presentation, raisons_nom_presentation = (
            calculer_score_nom_client(
                zones["presentation"],
                client,
            )
        )
        score_nom_transcription, raisons_nom_transcription = (
            calculer_score_nom_client(
                zones["transcription"],
                client,
            )
        )
        # Le corps d'une commande contient souvent des mots proches d'un
        # client (par exemple "piquillos" ou "vinaigre blanc"). Hors de la
        # zone de presentation, seule une mention exacte du nom/alias est une
        # preuve client exploitable ; une simple ressemblance floue ne l'est
        # pas.
        if not any(
            raison.startswith("match_exact_sequence:")
            for raison in raisons_nom_transcription
        ):
            score_nom_transcription = 0.0
            raisons_nom_transcription = []
        if score_nom_presentation >= score_nom_transcription:
            score_nom = score_nom_presentation
            raisons_nom = raisons_nom_presentation
        else:
            score_nom = score_nom_transcription
            raisons_nom = raisons_nom_transcription

        score_code_presentation, raisons_code_presentation = (
            calculer_score_code_client(
                zones["presentation"],
                str(client.get("code_client", "")),
            )
        )
        score_code_transcription, raisons_code_transcription = (
            calculer_score_code_client(
                zones["transcription"],
                str(client.get("code_client", "")),
            )
        )
        if not _code_client_acceptable_hors_presentation(
            str(client.get("code_client", ""))
        ):
            score_code_transcription = 0.0
            raisons_code_transcription = []

        if score_code_presentation >= score_code_transcription:
            score_code = score_code_presentation
            raisons_code = raisons_code_presentation
        else:
            score_code = score_code_transcription
            raisons_code = raisons_code_transcription

        score_ville_presentation, raisons_ville_presentation = (
            calculer_score_ville(
                zones["presentation"],
                str(client.get("ville", "")),
            )
        )
        score_ville_transcription, raisons_ville_transcription = (
            calculer_score_ville(
                zones["transcription"],
                str(client.get("ville", "")),
            )
        )
        if score_ville_presentation >= score_ville_transcription:
            score_ville = score_ville_presentation
            raisons_ville = raisons_ville_presentation
        else:
            score_ville = score_ville_transcription
            raisons_ville = raisons_ville_transcription

        score_adresse_presentation, raisons_adresse_presentation = (
            calculer_score_adresse(
                zone_client=zones["presentation"],
                adresse_1=str(
                    client.get("adresse_1", "")
                ),
                adresse_2=str(
                    client.get("adresse_2", "")
                ),
                code_postal=str(
                    client.get("code_postal", "")
                ),
            )
        )
        score_adresse_transcription, raisons_adresse_transcription = (
            calculer_score_adresse(
                zone_client=zones["transcription"],
                adresse_1=str(
                    client.get("adresse_1", "")
                ),
                adresse_2=str(
                    client.get("adresse_2", "")
                ),
                code_postal=str(
                    client.get("code_postal", "")
                ),
            )
        )
        if score_adresse_presentation >= score_adresse_transcription:
            score_adresse = score_adresse_presentation
            raisons_adresse = raisons_adresse_presentation
        else:
            score_adresse = score_adresse_transcription
            raisons_adresse = raisons_adresse_transcription

        telephones_client = {
            normaliser_telephone(telephone)
            for telephone in client.get("telephones", [])
            if normaliser_telephone(telephone)
        }
        match_telephone_exact = bool(
            telephone_normalise
            and telephone_normalise in telephones_client
        )
        score_telephone = 100.0 if match_telephone_exact else 0.0

        if max(
            score_nom,
            score_code,
            score_ville,
            score_adresse,
            score_telephone,
        ) < SEUIL_PRESSELECTION_NOM_OU_CODE:
            continue

        candidats.append(
            {
                "code_client": client["code_client"],
                "nom_client": client["nom_client"],
                "ville": client.get("ville", ""),
                "score_nom": round(score_nom, 2),
                "score_code": round(score_code, 2),
                "score_ville": round(score_ville, 2),
                "score_adresse": round(score_adresse, 2),
                "score_telephone": round(score_telephone, 2),
                "raisons_nom": raisons_nom,
                "raisons_code": raisons_code,
                "raisons_ville": raisons_ville,
                "raisons_adresse": raisons_adresse,
                "raisons_telephone": (
                    ["telephone_appel_exact"]
                    if match_telephone_exact
                    else []
                ),
                "aliases": client.get("aliases", []),
                "match_nom_exact": _a_raison_exacte(
                    raisons_nom,
                    "match_exact_sequence:",
                ),
                "match_code_exact": _a_raison_exacte(
                    raisons_code,
                    "code_",
                ),
                "match_adresse_exact": _a_raison_exacte(
                    raisons_adresse,
                    "adresse_exacte:",
                ),
                "match_ville_exact": _a_raison_exacte(
                    raisons_ville,
                    "ville_mentionnee:",
                ),
                "match_telephone_exact": (
                    match_telephone_exact
                ),
                "derniere_vente_iso": str(
                    client.get("derniere_vente_iso", "")
                ),
                "derniere_vente_ordinal": int(
                    client.get("derniere_vente_ordinal", -1)
                ),
                "nb_lignes_ventes": int(
                    client.get("nb_lignes_ventes", 0)
                ),
                "nb_lignes_ventes_recentes": int(
                    client.get(
                        "nb_lignes_ventes_recentes", 0
                    )
                ),
                "nb_commandes_total": int(
                    client.get("nb_commandes_total", 0)
                ),
                "nb_commandes_recentes": int(
                    client.get("nb_commandes_recentes", 0)
                ),
                "montant_recent": float(
                    client.get("montant_recent", 0.0)
                ),
            }
        )

    candidats.sort(
        key=lambda candidat: (
            candidat["match_telephone_exact"],
            candidat["match_code_exact"],
            candidat["match_nom_exact"],
            candidat["match_adresse_exact"],
            candidat["score_code"],
            candidat["score_nom"],
            candidat["score_adresse"],
            candidat["score_ville"],
            _cle_recence_client(candidat),
        ),
        reverse=True,
    )

    return candidats[:limite_preselection]


def identifier_client(
    transcription: str,
    clients: list[dict[str, Any]],
    cadencier: dict[str, list[dict[str, Any]]],
    mentions_produits: list[dict[str, Any]],
    telephone_appel: str | None = None,
    limite_preselection: int = 80,
    limite_resultats: int = 8,
) -> dict[str, Any]:
    zone_client = extraire_zone_presentation_client(
        transcription
    )

    preselection = _preselectionner_par_nom_ou_code(
        transcription=transcription,
        clients=clients,
        limite_preselection=limite_preselection,
        telephone_appel=telephone_appel,
    )

    candidats: list[dict[str, Any]] = []

    for candidat in preselection:
        code_client = candidat["code_client"]
        produits_client = cadencier.get(code_client, [])

        (
            score_cadencier,
            raisons_cadencier,
            details_cadencier,
        ) = calculer_score_cadencier(
            mentions_produits=mentions_produits,
            produits_client=produits_client,
        )

        score_global = round(
            100.0
            if candidat.get("match_telephone_exact")
            else (
                (candidat["score_nom"] * 0.40)
                + (candidat["score_code"] * 0.20)
                + (score_cadencier * 0.20)
                + (candidat["score_adresse"] * 0.15)
                + (candidat["score_ville"] * 0.05)
            ),
            2,
        )

        raisons = [
            *candidat["raisons_telephone"],
            *candidat["raisons_nom"],
            *candidat["raisons_code"],
            *candidat["raisons_adresse"],
            *candidat["raisons_ville"],
            *raisons_cadencier,
        ]

        candidats.append(
            {
                "code_client": code_client,
                "nom_client": candidat["nom_client"],
                "ville": candidat.get("ville", ""),
                "score_nom": candidat["score_nom"],
                "score_code": candidat["score_code"],
                "score_adresse": candidat["score_adresse"],
                "score_ville": candidat["score_ville"],
                "score_telephone": candidat[
                    "score_telephone"
                ],
                "score_cadencier": score_cadencier,
                "score_global": score_global,
                "cadencier_articles": len(
                    produits_client
                ),
                "details_cadencier": details_cadencier,
                "raisons": raisons,
                "match_nom_exact": candidat[
                    "match_nom_exact"
                ],
                "match_code_exact": candidat[
                    "match_code_exact"
                ],
                "match_adresse_exact": candidat[
                    "match_adresse_exact"
                ],
                "match_ville_exact": candidat[
                    "match_ville_exact"
                ],
                "match_telephone_exact": candidat[
                    "match_telephone_exact"
                ],
                "derniere_vente_iso": candidat[
                    "derniere_vente_iso"
                ],
                "derniere_vente_ordinal": candidat[
                    "derniere_vente_ordinal"
                ],
                "nb_lignes_ventes": candidat[
                    "nb_lignes_ventes"
                ],
                "nb_lignes_ventes_recentes": candidat[
                    "nb_lignes_ventes_recentes"
                ],
                "nb_commandes_total": candidat[
                    "nb_commandes_total"
                ],
                "nb_commandes_recentes": candidat[
                    "nb_commandes_recentes"
                ],
                "montant_recent": candidat[
                    "montant_recent"
                ],
            }
        )

    candidats.sort(
        key=lambda candidat: (
            candidat["match_telephone_exact"],
            candidat["match_code_exact"],
            candidat["match_nom_exact"],
            candidat["match_adresse_exact"],
            candidat["score_global"],
            candidat["score_nom"],
            candidat["score_cadencier"],
            _cle_recence_client(candidat),
        ),
        reverse=True,
    )

    candidats = candidats[:limite_resultats]

    decision_automatique = False
    client_retenu: str | None = None
    client_nom_retenu = ""
    raisons_decision: list[str] = []

    if not candidats:
        if client_est_mentionne(transcription):
            raisons_decision.append(
                "client_non_identifie"
            )
        else:
            raisons_decision.append(
                "client_non_mentionne"
            )
    else:
        candidats_code_exact = [
            candidat
            for candidat in candidats
            if candidat["match_code_exact"]
        ]
        candidats_nom_exact = [
            candidat
            for candidat in candidats
            if candidat["match_nom_exact"]
        ]
        candidats_adresse_exact = [
            candidat
            for candidat in candidats
            if candidat["match_adresse_exact"]
        ]
        candidats_telephone_exact = [
            candidat
            for candidat in candidats
            if candidat["match_telephone_exact"]
        ]

        selection: dict[str, Any] | None = None

        if candidats_telephone_exact:
            selection, raisons_decision = (
                _departager_candidats_homonymes(
                    candidats_telephone_exact
                )
            )
            if selection is not None:
                raisons_decision.insert(
                    0,
                    "client_identifie_par_telephone",
                )
        elif candidats_code_exact:
            selection, raisons_decision = (
                _departager_candidats_homonymes(
                    candidats_code_exact
                )
            )
            if selection is not None:
                raisons_decision.insert(
                    0,
                    "client_identifie_par_code",
                )
        elif candidats_nom_exact:
            selection, raisons_decision = (
                _departager_candidats_homonymes(
                    candidats_nom_exact
                )
            )
            if selection is not None:
                raisons_decision.insert(
                    0,
                    "client_identifie_par_nom_exact",
                )
        elif candidats_adresse_exact:
            selection, raisons_decision = (
                _departager_candidats_homonymes(
                    candidats_adresse_exact
                )
            )
            if selection is not None:
                raisons_decision.insert(
                    0,
                    "client_identifie_par_adresse",
                )
        else:
            premier = candidats[0]
            second = (
                candidats[1]
                if len(candidats) > 1
                else None
            )
            ecart_score = (
                round(
                    premier["score_global"]
                    - second["score_global"],
                    2,
                )
                if second is not None
                else 999.0
            )
            ecart_adresse = (
                round(
                    premier["score_adresse"]
                    - second["score_adresse"],
                    2,
                )
                if second is not None
                else 999.0
            )

            if (
                len(candidats) == 1
                and premier["score_nom"] >= 55
            ):
                selection = premier
                raisons_decision = [
                    "client_identifie_par_nom_approx_unique"
                ]
            elif (
                premier["score_adresse"] >= 95
                and ecart_adresse >= 20
            ):
                selection = premier
                raisons_decision = [
                    "client_identifie_par_adresse_forte"
                ]
            elif (
                premier["score_global"]
                >= SEUIL_DECISION_CLIENT_FUZZY
                and ecart_score
                >= SEUIL_ECART_CLIENT_FUZZY
            ) or (
                premier["score_nom"] >= 95
                and ecart_score >= 5
            ):
                selection = premier
                raisons_decision = [
                    "client_identifie_par_correspondance_forte"
                ]
            else:
                raisons_decision = [
                    "ambiguite_client"
                ]

        if selection is not None:
            decision_automatique = True
            client_retenu = selection["code_client"]
            client_nom_retenu = selection["nom_client"]

    return {
        "zone_client": zone_client,
        "client_retenu": client_retenu,
        "client_nom_retenu": client_nom_retenu,
        "decision_automatique": decision_automatique,
        "raisons_decision": raisons_decision,
        "candidats": candidats,
    }
