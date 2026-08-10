from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from rapidfuzz import fuzz
from src.runtime_paths import (
    bootstrap_runtime_environment,
    get_project_root,
)
from src.clients import (
    charger_telephones_clients,
    charger_variantes_clients,
    enrichir_alias_avec_variantes,
    enrichir_clients_avec_telephones,
    identifier_client,
    normaliser_telephone,
    normaliser_telephones,
)
from src.produits import (
    charger_synonymes_produits,
    construire_catalogue_global,
    decouper_clauses_produits as decouper_clauses_produits_v2,
    extraire_mentions_produits as extraire_mentions_produits_v2,
    chercher_produits as chercher_produits_v2,
)

bootstrap_runtime_environment()

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

RACINE_PROJET = get_project_root()

DOSSIER_TRANSCRIPTIONS = RACINE_PROJET / "resultats" / "transcriptions"
DOSSIER_RESULTATS = RACINE_PROJET / "resultats" / "extractions"
DOSSIER_CONFIG = RACINE_PROJET / "config"
DOSSIER_COMMANDES_VALIDEES = RACINE_PROJET / "resultats" / "commandes-validees"
DOSSIER_COMMANDES_PROBLEMATIQUES = RACINE_PROJET / "resultats" / "commandes-problematiques"

DOSSIER_CLIENTS = RACINE_PROJET / "ressources-originales" / "informations-clients"
DOSSIER_CADENCIER = RACINE_PROJET / "ressources-originales" / "cadencier"
CHEMIN_CADENCIER_COMPLEMENT = (
    DOSSIER_CADENCIER
    / "historique_es_pretest_2026-05-20_au_2026-06-22.csv"
)
CHEMIN_VARIANTES_CLIENTS = DOSSIER_CONFIG / "variantes-clients.json"
CHEMIN_TELEPHONES_CLIENTS = DOSSIER_CONFIG / "telephones-clients.json"
CHEMIN_SYNONYMES_PRODUITS = DOSSIER_CONFIG / "synonymes-produits.json"
CHEMIN_UNITES_ARTICLES = DOSSIER_CONFIG / "unites-articles.csv"
CHEMIN_CATALOGUE_ARTICLES = DOSSIER_CONFIG / "catalogue-articles.json"
CHEMIN_REFERENCES_CONTROLE = (
    DOSSIER_CONFIG / "references-articles-controle.json"
)

NOMBRES = {
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
}

UNITES = {
    "kg": "KG",
    "kilo": "KG",
    "kilos": "KG",
    "kilogramme": "KG",
    "kilogrammes": "KG",
    "gramme": "G",
    "grammes": "G",
    "litre": "L",
    "litres": "L",
    "boite": "BOITE",
    "boites": "BOITE",
    "carton": "CAR",
    "cartons": "CAR",
    "colis": "COL",
    "piece": "PCE",
    "pieces": "PCE",
    "palette": "PAL",
    "palettes": "PAL",
}

JOURS_SEMAINE = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}

MOTIFS_SUPPRESSION_COMMANDE = (
    "supprimer",
    "supprime",
    "retirer",
    "retire",
    "enlever",
    "enleve",
    "annuler",
    "annule",
)

MOTIFS_NOUVELLE_COMMANDE = (
    "ajout",
    "ajouter",
    "ajoute",
    "complement",
    "modifier",
    "modifie",
    "modification",
    "changer",
    "change",
    "remplacer",
    "remplace",
)

MOTIFS_RAPPEL_CLIENT = (
    "rappelle moi",
    "rappelez moi",
    "me rappeler",
    "vous me rappeliez",
    "appelez moi",
    "me rappeleriez",
)

MOTS_GENERIQUES_CLIENT = {
    "le",
    "la",
    "les",
    "un",
    "une",
    "restaurant",
    "resto",
    "hotel",
    "bar",
    "bistrot",
    "brasserie",
    "sarl",
    "sas",
    "sasu",
    "eurl",
    "societe",
}


# -------------------------------------------------------------------
# Normalisation
# -------------------------------------------------------------------

def enlever_accents(texte: str) -> str:
    texte = unicodedata.normalize("NFD", texte)

    return "".join(
        caractere
        for caractere in texte
        if unicodedata.category(caractere) != "Mn"
    )


def normaliser(valeur: Any) -> str:
    texte = "" if valeur is None else str(valeur)

    texte = enlever_accents(texte).lower()

    texte = re.sub(
        r"[^a-z0-9]+",
        " ",
        texte,
    )

    return re.sub(
        r"\s+",
        " ",
        texte,
    ).strip()


def simplifier_nom_client(texte: str) -> str:
    tokens = normaliser(texte).split()

    tokens = [
        token
        for token in tokens
        if token not in MOTS_GENERIQUES_CLIENT
    ]

    return " ".join(tokens)


def creer_alias_client(nom_client: str) -> list[str]:
    """
    Exemple :
    LE BISTROT DES FILLES SARL TUNA

    devient notamment :
    - le bistrot des filles sarl tuna
    - le bistrot des filles
    - filles
    """

    nom_normalise = normaliser(nom_client)

    partie_avant_statut = re.split(
        r"\b(?:sarl|sas|sasu|eurl)\b",
        nom_normalise,
        maxsplit=1,
    )[0].strip()

    aliases = {
        nom_normalise,
        partie_avant_statut,
        simplifier_nom_client(nom_normalise),
        simplifier_nom_client(partie_avant_statut),
    }

    for morceau in re.split(r"\s+-\s+|/|\(|\)", str(nom_client or "")):
        morceau_normalise = normaliser(morceau)

        if not morceau_normalise:
            continue

        morceau_avant_statut = re.split(
            r"\b(?:sarl|sas|sasu|eurl)\b",
            morceau_normalise,
            maxsplit=1,
        )[0].strip()

        if morceau_avant_statut:
            aliases.add(morceau_avant_statut)
            aliases.add(
                simplifier_nom_client(morceau_avant_statut)
            )

    return sorted(
        alias
        for alias in aliases
        if alias
    )


# -------------------------------------------------------------------
# Lecture des fichiers Excel
# -------------------------------------------------------------------

def trouver_fichier_xlsx(dossier: Path) -> Path:
    fichiers = sorted(dossier.glob("*.xlsx"))

    if not fichiers:
        raise FileNotFoundError(
            f"Aucun fichier .xlsx trouvé dans : {dossier}"
        )

    return fichiers[0]


def trouver_fichiers_xlsx(dossier: Path) -> list[Path]:
    fichiers = sorted(dossier.glob("*.xlsx"))

    if not fichiers:
        raise FileNotFoundError(
            f"Aucun fichier .xlsx trouvÃ© dans : {dossier}"
        )

    return fichiers


def lire_lignes_xlsx(
    chemin: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    classeur = load_workbook(
        chemin,
        read_only=True,
        data_only=True,
    )

    feuille = classeur.active

    lignes_excel = feuille.iter_rows(values_only=True)

    en_tetes = [
        normaliser(valeur)
        for valeur in next(lignes_excel)
    ]

    lignes: list[dict[str, Any]] = []

    for valeurs in lignes_excel:
        ligne = {
            en_tetes[index]: valeurs[index]
            for index in range(
                min(len(en_tetes), len(valeurs))
            )
        }

        if any(
            valeur not in (None, "")
            for valeur in ligne.values()
        ):
            lignes.append(ligne)

    classeur.close()

    return en_tetes, lignes


def choisir_colonne(
    en_tetes: list[str],
    candidats: list[str],
    obligatoire: bool = True,
) -> str | None:
    candidats_normalises = [
        normaliser(candidat)
        for candidat in candidats
    ]

    for candidat in candidats_normalises:
        if candidat in en_tetes:
            return candidat

    for candidat in candidats_normalises:
        for en_tete in en_tetes:
            if candidat in en_tete:
                return en_tete

    if obligatoire:
        raise KeyError(
            "Colonne introuvable.\n"
            f"Candidats : {candidats}\n"
            f"Colonnes disponibles : {en_tetes}"
        )

    return None


# -------------------------------------------------------------------
# Clients
# -------------------------------------------------------------------

def charger_clients() -> list[dict[str, Any]]:
    clients_par_code: dict[str, dict[str, Any]] = {}

    for chemin in trouver_fichiers_xlsx(DOSSIER_CLIENTS):
        en_tetes, lignes = lire_lignes_xlsx(chemin)

        col_code = choisir_colonne(
            en_tetes,
            [
                "clients livres code",
                "client livre code",
                "code client",
                "n cpte",
                "numero compte",
                "compte",
            ],
        )

        col_nom = choisir_colonne(
            en_tetes,
            [
                "clients livres lib",
                "client livre lib",
                "nom client",
                "raison sociale",
            ],
        )

        col_ville = choisir_colonne(
            en_tetes,
            [
                "ville",
            ],
            obligatoire=False,
        )
        col_adresse_1 = choisir_colonne(
            en_tetes,
            [
                "adresse 1",
            ],
            obligatoire=False,
        )
        col_adresse_2 = choisir_colonne(
            en_tetes,
            [
                "adresse 2",
            ],
            obligatoire=False,
        )
        col_code_postal = choisir_colonne(
            en_tetes,
            [
                "code postal",
            ],
            obligatoire=False,
        )
        col_telephone = choisir_colonne(
            en_tetes,
            [
                "telephone du contact",
                "téléphone du contact",
                "telephone",
                "tel",
                "portable",
            ],
            obligatoire=False,
        )
        col_code_recherche = choisir_colonne(
            en_tetes,
            [
                "code recherche",
                "cod rech",
            ],
            obligatoire=False,
        )

        for ligne in lignes:
            code = str(ligne.get(col_code, "") or "").strip()
            nom = str(ligne.get(col_nom, "") or "").strip()

            if not code or not nom:
                continue

            ville = (
                str(ligne.get(col_ville, "") or "").strip()
                if col_ville
                else ""
            )
            adresse_1 = (
                str(ligne.get(col_adresse_1, "") or "").strip()
                if col_adresse_1
                else ""
            )
            adresse_2 = (
                str(ligne.get(col_adresse_2, "") or "").strip()
                if col_adresse_2
                else ""
            )
            code_postal = (
                str(ligne.get(col_code_postal, "") or "").strip()
                if col_code_postal
                else ""
            )
            telephone = (
                str(ligne.get(col_telephone, "") or "").strip()
                if col_telephone
                else ""
            )
            telephones = normaliser_telephones(telephone)

            aliases = set(
                creer_alias_client(nom)
            )

            aliases.add(
                normaliser(code)
            )
            if col_code_recherche:
                aliases.add(
                    normaliser(ligne.get(col_code_recherche, ""))
                )

            nouveau_client = {
                "code_client": code,
                "nom_client": nom,
                "ville": ville,
                "adresse_1": adresse_1,
                "adresse_2": adresse_2,
                "code_postal": code_postal,
                "telephone": telephone,
                "telephones": telephones,
                "aliases": sorted(alias for alias in aliases if alias),
            }

            existant = clients_par_code.get(code)
            if not existant:
                clients_par_code[code] = nouveau_client
                continue

            for cle in [
                "nom_client",
                "ville",
                "adresse_1",
                "adresse_2",
                "code_postal",
                "telephone",
            ]:
                if (
                    not str(existant.get(cle, "") or "").strip()
                    and str(nouveau_client.get(cle, "") or "").strip()
                ):
                    existant[cle] = nouveau_client[cle]

            existant["telephones"] = sorted(
                {
                    *[
                        str(value)
                        for value in existant.get("telephones", [])
                        if str(value).strip()
                    ],
                    *[
                        str(value)
                        for value in nouveau_client.get("telephones", [])
                        if str(value).strip()
                    ],
                }
            )
            existant["aliases"] = sorted(
                {
                    *[
                        str(value)
                        for value in existant.get("aliases", [])
                        if str(value).strip()
                    ],
                    *[
                        str(value)
                        for value in nouveau_client.get("aliases", [])
                        if str(value).strip()
                    ],
                }
            )

    return list(clients_par_code.values())


def extraire_zone_presentation_client(
    transcription: str,
) -> str:
    """
    On cherche le client uniquement au début du message.

    Exemple :
    Bonjour, c'est Les Affranchis, je voudrais...
    """

    texte = normaliser(transcription)

    marqueurs_fin = [
        "je voudrais",
        "je souhaite",
        "je souhaiterais",
        "je commande",
        "il me faudrait",
        "pour demain",
    ]

    positions = [
        texte.find(marqueur)
        for marqueur in marqueurs_fin
        if texte.find(marqueur) != -1
    ]

    if positions:
        texte = texte[:min(positions)]

    return texte.strip()


def calculer_score_client(
    zone_client: str,
    client: dict[str, Any],
) -> float:
    zone_normale = normaliser(zone_client)
    zone_simplifiee = simplifier_nom_client(zone_client)

    meilleur_score = 0.0

    for alias in client["aliases"]:
        alias_normalise = normaliser(alias)
        alias_simplifie = simplifier_nom_client(alias)

        if not alias_normalise:
            continue

        # Correspondance exacte du code ou du nom dans la présentation.
        if (
            len(alias_normalise) >= 3
            and alias_normalise in zone_normale
        ):
            meilleur_score = max(meilleur_score, 100.0)

        if (
            len(alias_simplifie) >= 3
            and alias_simplifie in zone_simplifiee
        ):
            meilleur_score = max(meilleur_score, 100.0)

        if len(alias_simplifie) >= 4:
            meilleur_score = max(
                meilleur_score,
                float(
                    fuzz.token_set_ratio(
                        alias_simplifie,
                        zone_simplifiee,
                    )
                ),
                float(
                    fuzz.partial_ratio(
                        alias_simplifie,
                        zone_simplifiee,
                    )
                ),
            )

    return round(meilleur_score, 2)


def chercher_clients(
    transcription: str,
    clients: list[dict[str, Any]],
    limite: int = 5,
) -> list[dict[str, Any]]:
    zone_client = extraire_zone_presentation_client(
        transcription
    )

    candidats: list[dict[str, Any]] = []

    for client in clients:
        score = calculer_score_client(
            zone_client,
            client,
        )

        if score >= 45:
            candidats.append(
                {
                    "code_client": client["code_client"],
                    "nom_client": client["nom_client"],
                    "ville": client["ville"],
                    "score": score,
                }
            )

    candidats.sort(
        key=lambda candidat: candidat["score"],
        reverse=True,
    )

    return candidats[:limite]


def client_est_fiable(
    candidats: list[dict[str, Any]],
) -> bool:
    if not candidats:
        return False

    premier = candidats[0]["score"]

    deuxieme = (
        candidats[1]["score"]
        if len(candidats) > 1
        else 0
    )

    return (
        premier >= 88
        and (
            premier - deuxieme >= 5
            or premier == 100
        )
    )


# -------------------------------------------------------------------
# Cadencier
# -------------------------------------------------------------------

@lru_cache(maxsize=1)
def _charger_index_references_officielles(
) -> tuple[set[str], dict[str, str], dict[str, str]]:
    """Indexe les codes actuels et les libelles officiels non ambigus."""
    if not CHEMIN_REFERENCES_CONTROLE.exists():
        return set(), {}, {}
    try:
        payload = json.loads(
            CHEMIN_REFERENCES_CONTROLE.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return set(), {}, {}
    references = (
        payload.get("references", {})
        if isinstance(payload, dict)
        else {}
    )
    if not isinstance(references, dict):
        return set(), {}, {}

    codes = {
        str(code).strip()
        for code in references
        if str(code).strip()
    }
    codes_reels: set[str] = set()
    references_par_libelle: dict[
        str,
        list[tuple[str, str]],
    ] = defaultdict(list)
    for code_brut, reference in references.items():
        code = str(code_brut).strip()
        if not code or not isinstance(reference, dict):
            continue
        suffixe_duplique = re.match(r"^(.+)\.(\d+)$", code)
        if suffixe_duplique and suffixe_duplique.group(1) in codes:
            # Suffixe technique cree par l'importeur pour une seconde ligne
            # de langue du meme code source. Ce n'est pas un code ERP.
            continue
        codes_reels.add(code)
        libelle_brut = str(reference.get("label") or "").strip()
        libelle = normaliser(libelle_brut)
        if libelle:
            references_par_libelle[libelle].append(
                (code, libelle_brut)
            )

    libelles_uniques = {
        libelle: references_libelle[0][0]
        for libelle, references_libelle in references_par_libelle.items()
        if len({code for code, _ in references_libelle}) == 1
    }
    alias_par_code: dict[str, str] = {}
    for references_libelle in references_par_libelle.values():
        codes_libelle = {code for code, _ in references_libelle}
        if len(codes_libelle) <= 1:
            continue
        codes_non_marques = {
            code
            for code, libelle_brut in references_libelle
            if "*" not in libelle_brut
        }
        if len(codes_non_marques) != 1:
            continue
        code_canonique = next(iter(codes_non_marques))
        for code, libelle_brut in references_libelle:
            if code != code_canonique and "*" in libelle_brut:
                alias_par_code[code] = code_canonique
    return codes_reels, libelles_uniques, alias_par_code


def _canonicaliser_code_article_reference(
    code_article: str,
    libelle_article: str,
) -> str:
    """Remplace un ancien code par le code officiel du meme libelle exact."""
    code = str(code_article or "").strip()
    if not code:
        return ""
    codes_officiels, codes_par_libelle, alias_par_code = (
        _charger_index_references_officielles()
    )
    if code in alias_par_code:
        return alias_par_code[code]
    if code in codes_officiels:
        return code
    libelle = normaliser(str(libelle_article or ""))
    return codes_par_libelle.get(libelle, code)


def _fusionner_historique_cadencier_pretest(
    produits_par_client: dict[str, dict[str, dict[str, Any]]],
    chemin_csv: Path = CHEMIN_CADENCIER_COMPLEMENT,
) -> None:
    """Ajoute un historique anterieur au corpus avec un garde-fou anti-fuite."""
    if not chemin_csv.exists():
        return

    chemin_manifest = chemin_csv.with_suffix(".manifest.json")
    if not chemin_manifest.exists():
        raise RuntimeError(
            f"Manifest du complement cadencier introuvable: {chemin_manifest}"
        )

    manifest = json.loads(chemin_manifest.read_text(encoding="utf-8"))
    if manifest.get("truth_from_evaluation_included") is not False:
        raise RuntimeError("Complement cadencier refuse: verite evaluation non isolee")
    date_coupure = date.fromisoformat(str(manifest["cutoff_inclusive"]))
    date_premier_audio = date.fromisoformat(
        str(manifest["evaluation_audio_from"])
    )
    if date_coupure >= date_premier_audio:
        raise RuntimeError(
            "Complement cadencier refuse: coupure posterieure au debut du corpus"
        )

    seuil_recent = date_coupure - timedelta(days=30)
    for produits in produits_par_client.values():
        for produit in produits.values():
            produit["nb_ventes_article_recentes"] = 0

    historiques_quantites: dict[
        tuple[str, str], Counter[float]
    ] = defaultdict(Counter)
    recence_quantites: dict[tuple[str, str], dict[float, int]] = defaultdict(dict)

    with chemin_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for ligne in csv.DictReader(handle, delimiter=";"):
            code_client = str(ligne.get("client_code") or "").strip()
            code_article = str(ligne.get("article_code") or "").strip()
            libelle = str(ligne.get("designation") or "").strip()
            if not code_client or not code_article or not libelle:
                continue
            code_article = _canonicaliser_code_article_reference(
                code_article,
                libelle,
            )

            texte_date = str(
                ligne.get("departure_date")
                or ligne.get("order_date")
                or ""
            ).strip()
            try:
                date_vente = date.fromisoformat(texte_date[:10])
            except ValueError:
                continue
            if date_vente > date_coupure:
                raise RuntimeError(
                    f"Complement cadencier refuse: date hors coupure {date_vente}"
                )

            produits = produits_par_client[code_client]
            produit = produits.setdefault(
                code_article,
                {
                    "code_article": code_article,
                    "client_libelle": str(
                        ligne.get("client_label") or ""
                    ).strip(),
                    "libelle_article": libelle,
                    "libelle_normalise": normaliser(libelle),
                    "prix": None,
                    "nb_ventes_article_total": 0,
                    "nb_ventes_article_recentes": 0,
                    "derniere_vente_article_iso": "",
                    "derniere_vente_article_ordinal": -1,
                    "quantite_habituelle_commande": 0.0,
                    "quantites_habituelles_commande": [],
                    "ratio_net_par_unite": 0.0,
                    "unite_vente": str(ligne.get("unit") or "").strip().upper(),
                    "source_article": "historique_client_pretest",
                },
            )
            produit["client_libelle"] = (
                str(ligne.get("client_label") or "").strip()
                or produit.get("client_libelle", "")
            )
            produit["libelle_article"] = libelle
            produit["libelle_normalise"] = normaliser(libelle)
            produit["nb_ventes_article_total"] = (
                int(produit.get("nb_ventes_article_total", 0)) + 1
            )
            if date_vente >= seuil_recent:
                produit["nb_ventes_article_recentes"] = (
                    int(produit.get("nb_ventes_article_recentes", 0)) + 1
                )
            ordinal = date_vente.toordinal()
            if ordinal > int(produit.get("derniere_vente_article_ordinal", -1)):
                produit["derniere_vente_article_ordinal"] = ordinal
                produit["derniere_vente_article_iso"] = date_vente.isoformat()
            if not produit.get("unite_vente"):
                produit["unite_vente"] = str(
                    ligne.get("unit") or ""
                ).strip().upper()

            texte_quantite = str(ligne.get("quantity") or "").replace(",", ".")
            try:
                quantite = round(float(texte_quantite), 3)
            except ValueError:
                quantite = 0.0
            if quantite > 0:
                cle = (code_client, code_article)
                historiques_quantites[cle][quantite] += 1
                recence_quantites[cle][quantite] = max(
                    recence_quantites[cle].get(quantite, -1),
                    ordinal,
                )

    for (code_client, code_article), historique in historiques_quantites.items():
        produit = produits_par_client[code_client][code_article]
        quantites_tries = sorted(
            historique.items(),
            key=lambda item: (
                item[1],
                recence_quantites[(code_client, code_article)].get(item[0], -1),
                item[0],
            ),
            reverse=True,
        )
        produit["quantite_habituelle_commande"] = float(quantites_tries[0][0])
        produit["quantites_habituelles_commande"] = [
            float(quantite) for quantite, _ in quantites_tries[:5]
        ]


def charger_cadencier() -> dict[str, list[dict[str, Any]]]:
    chemin = trouver_fichier_xlsx(DOSSIER_CADENCIER)

    en_tetes, lignes = lire_lignes_xlsx(chemin)

    col_client = choisir_colonne(
        en_tetes,
        [
            "client livre code",
        ],
    )
    col_client_lib = choisir_colonne(
        en_tetes,
        [
            "client livre lib",
            "clients livres lib",
        ],
        obligatoire=False,
    )

    col_article = choisir_colonne(
        en_tetes,
        [
            "article code",
        ],
    )

    col_libelle = choisir_colonne(
        en_tetes,
        [
            "article lib",
        ],
    )
    col_prix = choisir_colonne(
        en_tetes,
        [
            "px net pied",
            "px.net pied",
            "prix net",
        ],
        obligatoire=False,
    )
    col_pieces = choisir_colonne(
        en_tetes,
        [
            "pieces liv",
        ],
        obligatoire=False,
    )
    col_pds_net = choisir_colonne(
        en_tetes,
        [
            "pds net liv",
        ],
        obligatoire=False,
    )
    col_depart = choisir_colonne(
        en_tetes,
        [
            "depart",
        ],
        obligatoire=False,
    )

    dates_valides = [
        valeur
        if isinstance(valeur, datetime)
        else datetime.combine(
            valeur,
            datetime.min.time(),
        )
        for valeur in (
            ligne.get(col_depart)
            for ligne in lignes
        )
        if col_depart
        and isinstance(valeur, (datetime, date))
    ]
    reference_recente = (
        max(dates_valides)
        if dates_valides
        else None
    )
    seuil_recent = (
        reference_recente - timedelta(days=30)
        if reference_recente is not None
        else None
    )

    produits_par_client: dict[
        str,
        dict[str, dict[str, Any]],
    ] = defaultdict(dict)

    for ligne in lignes:
        code_client = str(
            ligne.get(col_client, "")
            or ""
        ).strip()

        code_article = str(
            ligne.get(col_article, "")
            or ""
        ).strip()
        client_libelle = (
            str(ligne.get(col_client_lib, "") or "").strip()
            if col_client_lib
            else ""
        )

        libelle = str(
            ligne.get(col_libelle, "")
            or ""
        ).strip()
        prix = (
            ligne.get(col_prix)
            if col_prix
            else None
        )

        if not code_client or not code_article or not libelle:
            continue
        code_article = _canonicaliser_code_article_reference(
            code_article,
            libelle,
        )

        produit = produits_par_client[
            code_client
        ].setdefault(
            code_article,
            {
                "code_article": code_article,
                "client_libelle": client_libelle,
                "libelle_article": libelle,
                "libelle_normalise": normaliser(libelle),
                "prix": None,
                "nb_ventes_article_total": 0,
                "nb_ventes_article_recentes": 0,
                "derniere_vente_article_iso": "",
                "derniere_vente_article_ordinal": -1,
                "quantite_habituelle_commande": 0.0,
                "quantites_habituelles_commande": [],
                "ratio_net_par_unite": 0.0,
                "_historique_quantites": Counter(),
                "_recence_quantites": {},
                "_somme_quantites_positives": 0.0,
                "_somme_pds_net_positif": 0.0,
            },
        )

        produit["client_libelle"] = client_libelle or produit[
            "client_libelle"
        ]
        produit["libelle_article"] = libelle or produit[
            "libelle_article"
        ]
        produit["libelle_normalise"] = normaliser(
            produit["libelle_article"]
        )
        if isinstance(prix, (int, float)):
            produit["prix"] = float(prix)

        produit["nb_ventes_article_total"] += 1

        qte_pieces = (
            ligne.get(col_pieces)
            if col_pieces
            else None
        )
        pds_net = (
            ligne.get(col_pds_net)
            if col_pds_net
            else None
        )

        if col_depart:
            date_depart = ligne.get(col_depart)
            if isinstance(date_depart, datetime):
                date_depart_dt = date_depart
                date_depart_simple = date_depart.date()
            elif isinstance(date_depart, date):
                date_depart_simple = date_depart
                date_depart_dt = datetime.combine(
                    date_depart,
                    datetime.min.time(),
                )
            else:
                date_depart_simple = None
                date_depart_dt = None

            if date_depart_simple is not None:
                ordinal = date_depart_simple.toordinal()
                if (
                    ordinal
                    > produit["derniere_vente_article_ordinal"]
                ):
                    produit["derniere_vente_article_ordinal"] = (
                        ordinal
                    )
                    produit["derniere_vente_article_iso"] = (
                        date_depart_simple.isoformat()
                    )
            if (
                seuil_recent is not None
                and date_depart_dt is not None
                and date_depart_dt >= seuil_recent
            ):
                produit["nb_ventes_article_recentes"] += 1

            if (
                isinstance(qte_pieces, (int, float))
                and float(qte_pieces) > 0
            ):
                qte_positive = round(
                    float(qte_pieces), 3
                )
                produit["_historique_quantites"][
                    qte_positive
                ] += 1
                produit["_recence_quantites"][
                    qte_positive
                ] = max(
                    int(
                        produit["_recence_quantites"].get(
                            qte_positive, -1
                        )
                    ),
                    int(
                        date_depart_simple.toordinal()
                    )
                    if date_depart_simple is not None
                    else -1,
                )
                produit["_somme_quantites_positives"] += (
                    qte_positive
                )

                if (
                    isinstance(pds_net, (int, float))
                    and float(pds_net) > 0
                ):
                    produit["_somme_pds_net_positif"] += (
                        float(pds_net)
                    )

    for produits_client in produits_par_client.values():
        for produit in produits_client.values():
            historique_quantites = produit.pop(
                "_historique_quantites"
            )
            recence_quantites = produit.pop(
                "_recence_quantites"
            )
            somme_quantites = float(
                produit.pop(
                    "_somme_quantites_positives"
                )
            )
            somme_pds_net = float(
                produit.pop("_somme_pds_net_positif")
            )

            if historique_quantites:
                quantites_tries = sorted(
                    historique_quantites.items(),
                    key=lambda item: (
                        item[1],
                        recence_quantites.get(
                            item[0], -1
                        ),
                        item[0],
                    ),
                    reverse=True,
                )
                produit[
                    "quantite_habituelle_commande"
                ] = float(quantites_tries[0][0])
                produit[
                    "quantites_habituelles_commande"
                ] = [
                    float(quantite)
                    for quantite, _ in quantites_tries[:5]
                ]

            if somme_quantites > 0 and somme_pds_net > 0:
                produit["ratio_net_par_unite"] = round(
                    somme_pds_net / somme_quantites,
                    4,
                )

    _fusionner_historique_cadencier_pretest(produits_par_client)

    return {
        code_client: list(produits.values())
        for code_client, produits in produits_par_client.items()
    }


def charger_stats_ventes_clients() -> dict[str, dict[str, Any]]:
    chemin = trouver_fichier_xlsx(DOSSIER_CADENCIER)
    en_tetes, lignes = lire_lignes_xlsx(chemin)

    col_client = choisir_colonne(
        en_tetes,
        [
            "client livre code",
        ],
    )
    col_depart = choisir_colonne(
        en_tetes,
        [
            "depart",
        ],
    )
    col_commande = choisir_colonne(
        en_tetes,
        [
            "n cde",
            "no cde",
            "numero commande",
        ],
        obligatoire=False,
    )
    col_montant = choisir_colonne(
        en_tetes,
        [
            "mtt net ligne",
            "montant net ligne",
        ],
        obligatoire=False,
    )

    dates_valides = [
        valeur
        if isinstance(valeur, datetime)
        else datetime.combine(
            valeur,
            datetime.min.time(),
        )
        for valeur in (
            ligne.get(col_depart)
            for ligne in lignes
        )
        if isinstance(valeur, (datetime, date))
    ]
    reference_recente = (
        max(dates_valides)
        if dates_valides
        else None
    )
    seuil_recent = (
        reference_recente - timedelta(days=30)
        if reference_recente is not None
        else None
    )

    stats_par_client: dict[str, dict[str, Any]] = {}

    for ligne in lignes:
        code_client = str(
            ligne.get(col_client, "") or ""
        ).strip()
        date_depart = ligne.get(col_depart)

        if not code_client or not isinstance(
            date_depart, (datetime, date)
        ):
            continue

        stats = stats_par_client.setdefault(
            code_client,
            {
                "derniere_vente_iso": "",
                "derniere_vente_ordinal": -1,
                "nb_lignes_ventes": 0,
                "nb_lignes_ventes_recentes": 0,
                "nb_commandes_total": 0,
                "nb_commandes_recentes": 0,
                "montant_recent": 0.0,
                "_commandes_total": set(),
                "_commandes_recentes": set(),
            },
        )

        stats["nb_lignes_ventes"] += 1
        if isinstance(date_depart, datetime):
            date_depart_dt = date_depart
            date_depart_simple = date_depart.date()
        else:
            date_depart_simple = date_depart
            date_depart_dt = datetime.combine(
                date_depart,
                datetime.min.time(),
            )
        ordinal = date_depart_simple.toordinal()

        if ordinal > stats["derniere_vente_ordinal"]:
            stats["derniere_vente_ordinal"] = ordinal
            stats["derniere_vente_iso"] = (
                date_depart_simple.isoformat()
            )

        numero_commande = (
            str(ligne.get(col_commande, "") or "").strip()
            if col_commande
            else ""
        )
        if numero_commande:
            stats["_commandes_total"].add(numero_commande)

        est_recent = (
            seuil_recent is not None
            and date_depart_dt >= seuil_recent
        )
        if est_recent:
            stats["nb_lignes_ventes_recentes"] += 1
            if numero_commande:
                stats["_commandes_recentes"].add(
                    numero_commande
                )
            montant = (
                ligne.get(col_montant)
                if col_montant
                else None
            )
            if isinstance(montant, (int, float)):
                stats["montant_recent"] += float(montant)

    for stats in stats_par_client.values():
        stats["nb_commandes_total"] = len(
            stats.pop("_commandes_total")
        )
        stats["nb_commandes_recentes"] = len(
            stats.pop("_commandes_recentes")
        )
        stats["montant_recent"] = round(
            stats["montant_recent"], 2
        )

    return stats_par_client


def enrichir_clients_depuis_cadencier(
    clients: list[dict[str, Any]],
    cadencier: dict[str, list[dict[str, Any]]],
) -> int:
    clients_par_code = {
        client["code_client"]: client
        for client in clients
    }
    ajoutes = 0

    for code_client, produits in cadencier.items():
        if code_client in clients_par_code:
            continue

        nom_client = ""

        if produits:
            nom_client = str(
                produits[0].get("client_libelle", "")
                or ""
            ).strip()

        if not nom_client:
            nom_client = code_client

        ville = ""
        tokens_nom = normaliser(nom_client).split()

        if tokens_nom:
            token_final = tokens_nom[-1]

            if (
                token_final.isalpha()
                and len(token_final) >= 4
            ):
                ville = token_final.upper()

        aliases = set(
            creer_alias_client(nom_client)
        )
        aliases.add(normaliser(code_client))

        nouveau_client = {
            "code_client": code_client,
            "nom_client": nom_client,
            "ville": ville,
            "adresse_1": "",
            "adresse_2": "",
            "code_postal": "",
            "aliases": sorted(
                alias
                for alias in aliases
                if alias
            ),
            "source_client": "cadencier",
        }

        clients.append(nouveau_client)
        clients_par_code[code_client] = nouveau_client
        ajoutes += 1

    return ajoutes


def enrichir_clients_avec_stats_ventes(
    clients: list[dict[str, Any]],
    stats_ventes: dict[str, dict[str, Any]],
) -> None:
    for client in clients:
        stats = stats_ventes.get(
            str(client.get("code_client", "")).strip(),
            {},
        )
        client["derniere_vente_iso"] = stats.get(
            "derniere_vente_iso",
            "",
        )
        client["derniere_vente_ordinal"] = int(
            stats.get("derniere_vente_ordinal", -1)
        )
        client["nb_lignes_ventes"] = int(
            stats.get("nb_lignes_ventes", 0)
        )
        client["nb_lignes_ventes_recentes"] = int(
            stats.get("nb_lignes_ventes_recentes", 0)
        )
        client["nb_commandes_total"] = int(
            stats.get("nb_commandes_total", 0)
        )
        client["nb_commandes_recentes"] = int(
            stats.get("nb_commandes_recentes", 0)
        )
        client["montant_recent"] = float(
            stats.get("montant_recent", 0.0)
        )


# -------------------------------------------------------------------
# Dates
# -------------------------------------------------------------------

def extraire_date_livraison(
    transcription: str,
    date_reference: date | None = None,
) -> dict[str, str] | None:
    """
    Détection volontairement stricte.

    Elle évite les faux positifs comme :
    'je' interprété comme une date.
    """

    reference = date_reference or date.today()

    texte = normaliser(transcription)
    candidats: list[
        tuple[int, int, dict[str, str]]
    ] = []

    for motif in re.finditer(
        r"\bapres demain\b",
        texte,
    ):
        valeur = reference + timedelta(days=2)
        candidats.append(
            (
                motif.start(),
                motif.end(),
                {
                    "expression": "après-demain",
                    "date_iso": valeur.isoformat(),
                },
            )
        )

    for motif in re.finditer(
        r"\bdemain\b",
        texte,
    ):
        valeur = reference + timedelta(days=1)
        candidats.append(
            (
                motif.start(),
                motif.end(),
                {
                    "expression": "demain",
                    "date_iso": valeur.isoformat(),
                },
            )
        )

    for motif_date in re.finditer(
        r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b",
        texte,
    ):
        jour = int(motif_date.group(1))
        mois = int(motif_date.group(2))

        annee_brute = motif_date.group(3)

        if annee_brute is None:
            annee = reference.year
        elif len(annee_brute) == 2:
            annee = 2000 + int(annee_brute)
        else:
            annee = int(annee_brute)

        try:
            valeur = date(
                year=annee,
                month=mois,
                day=jour,
            )
        except ValueError:
            continue

        candidats.append(
            (
                motif_date.start(),
                motif_date.end(),
                {
                    "expression": motif_date.group(0),
                    "date_iso": valeur.isoformat(),
                },
            )
        )

    for mot, numero_jour in JOURS_SEMAINE.items():
        for motif in re.finditer(
            rf"\b{re.escape(mot)}\b",
            texte,
        ):
            decalage = (
                numero_jour
                - reference.weekday()
            ) % 7

            if decalage == 0:
                decalage = 7

            valeur = reference + timedelta(
                days=decalage
            )

            candidats.append(
                (
                    motif.start(),
                    motif.end(),
                    {
                        "expression": mot,
                        "date_iso": valeur.isoformat(),
                    },
                )
            )

    if not candidats:
        return None

    _, _, premier = min(
        candidats,
        key=lambda candidat: (
            candidat[0],
            -(candidat[1] - candidat[0]),
        ),
    )

    return premier


def _message_est_rappel_sans_commande(
    texte: str,
) -> bool:
    if not any(
        expression in texte
        for expression in MOTIFS_RAPPEL_CLIENT
    ):
        return False

    marqueurs_commande = (
        "je voudrais",
        "il me faudrait",
        "il faudrait",
        "commande",
        "ajouter",
        "ajoute",
    )
    if any(
        marqueur in texte
        for marqueur in marqueurs_commande
    ):
        return False

    unites = (
        "carton",
        "cartons",
        "kilo",
        "kilos",
        "kg",
        "litre",
        "litres",
        "piece",
        "pieces",
        "pack",
        "packs",
        "bidon",
        "bidons",
        "boite",
        "boites",
    )
    mots_nombres = tuple(NOMBRES.keys())
    motif_quantite = (
        r"\b(?:\d+(?:[\.,]\d+)?|"
        + "|".join(
            re.escape(mot) for mot in mots_nombres
        )
        + r")\s+(?:"
        + "|".join(re.escape(unite) for unite in unites)
        + r")\b"
    )

    return re.search(motif_quantite, texte) is None


def detecter_type_action_commande(
    transcription: str,
) -> dict[str, str]:
    texte = normaliser(transcription)

    for expression in MOTIFS_SUPPRESSION_COMMANDE:
        motif = re.search(
            rf"\b{re.escape(expression)}\b",
            texte,
        )
        if motif:
            return {
                "type_action": "suppression",
                "expression": expression,
            }

    if _message_est_rappel_sans_commande(texte):
        return {
            "type_action": "rappel",
            "expression": "rappel_client",
        }

    for expression in MOTIFS_NOUVELLE_COMMANDE:
        motif = re.search(
            rf"\b{re.escape(expression)}\b",
            texte,
        )
        if motif:
            return {
                "type_action": "creation",
                "expression": expression,
            }

    return {
        "type_action": "creation",
        "expression": "",
    }


def extraire_mentions_suppression(
    transcription: str,
) -> list[dict[str, Any]]:
    texte = normaliser(transcription)
    segments: list[str] = []

    for verbe in MOTIFS_SUPPRESSION_COMMANDE:
        for motif in re.finditer(
            rf"\b{re.escape(verbe)}\b\s+(?P<segment>.+)",
            texte,
        ):
            segment = motif.group("segment").strip()
            segment = re.split(
                r"\b(?:pour|merci|bonne journee|au revoir|"
                r"ce sera|ca sera|ce serait|ca serait)\b",
                segment,
                maxsplit=1,
            )[0].strip()

            if segment:
                segments.append(segment)

    mentions: list[dict[str, Any]] = []

    for segment in segments:
        morceaux = re.split(
            r"\s*(?:,|;|\bet\b)\s*",
            segment,
        )

        for morceau in morceaux:
            produit = re.sub(
                r"^(?:le|la|les|du|de la|de l|des|d)\s+",
                "",
                morceau.strip(),
            )
            produit = produit.strip()

            if len(produit) < 3:
                continue

            mentions.append(
                {
                    "texte_source": produit,
                    "texte_normalise": produit,
                    "produit_normalise": produit,
                    "texte_produit": produit,
                    "quantite_principale": 1.0,
                    "quantite": 1.0,
                    "unite_principale": None,
                    "unite_detectee": None,
                    "precisions_quantite": [],
                    "ambigu": False,
                    "raisons_ambiguite": [],
                }
            )

    return mentions


def resoudre_date_livraison(
    transcription: str,
    date_reference: date | None = None,
    heure_reference: int | None = None,
    jour_reference: date | None = None,
) -> dict[str, Any]:
    date_expression_reference = date_reference
    if (
        date_expression_reference is not None
        and heure_reference is not None
        and 0 <= heure_reference < 6
    ):
        date_expression_reference -= timedelta(days=1)

    date_detectee = extraire_date_livraison(
        transcription=transcription,
        date_reference=date_expression_reference,
    )

    if date_detectee:
        return {
            **date_detectee,
            "date_par_defaut": False,
        }

    if date_reference is not None and heure_reference is not None:
        if 0 <= heure_reference < 6:
            reference = date_reference
            expression = "defaut_nuit_date_du_jour"
        else:
            reference = date_reference + timedelta(days=1)
            expression = "defaut_journee_date_demain"
    elif date_reference is not None:
        reference = date_reference
        expression = "defaut_date_reference"
    else:
        heure = (
            heure_reference
            if heure_reference is not None
            else datetime.now().hour
        )
        jour = jour_reference or date.today()

        if 0 <= heure < 6:
            reference = jour
            expression = "defaut_nuit_date_du_jour"
        else:
            reference = jour + timedelta(days=1)
            expression = "defaut_journee_date_demain"

    return {
        "expression": expression,
        "date_iso": reference.isoformat(),
        "date_par_defaut": True,
    }


# -------------------------------------------------------------------
# Extraction des mentions produit
# -------------------------------------------------------------------

def remplacer_nombres_ecrits(texte: str) -> str:
    # Conservé pour compatibilité avec les tests
    # et l’ancien flux d’appel.
    return texte


def nettoyer_clause(clause: str) -> str:
    return clause.strip()


def decouper_clauses_produits(
    transcription: str,
) -> list[str]:
    return decouper_clauses_produits_v2(
        transcription
    )


def extraire_mentions_produits(
    transcription: str,
) -> list[dict[str, Any]]:
    return extraire_mentions_produits_v2(
        transcription
    )


# -------------------------------------------------------------------
# Recherche des produits dans le cadencier
# -------------------------------------------------------------------

def chercher_produits(
    mentions: list[dict[str, Any]],
    produits_client: list[dict[str, Any]],
    catalogue_global: list[dict[str, Any]],
    synonymes_produits: dict[str, list[str]],
    limite: int = 12,
) -> list[dict[str, Any]]:
    produits = chercher_produits_v2(
        mentions=mentions,
        produits_client=produits_client,
        catalogue_global=catalogue_global,
        synonymes=synonymes_produits,
        limite=limite,
    )

    # Compatibilité avec les anciens appels : clef `score`.
    for produit in produits:
        for candidat in produit.get("candidats", []):
            candidat["score"] = candidat["score_global"]

    return produits


# -------------------------------------------------------------------
# Lecture et écriture JSON / TXT
# -------------------------------------------------------------------

def lire_transcription(
    chemin_json: Path,
) -> str:
    donnees = json.loads(
        chemin_json.read_text(
            encoding="utf-8"
        )
    )

    return str(
        donnees.get(
            "texte",
            "",
        )
    ).strip()


def creer_resume_txt(
    resultat: dict[str, Any],
) -> str:
    lignes = [
        f"AUDIO : {resultat['fichier_audio']}",
        "",
        "TRANSCRIPTION :",
        resultat["transcription"],
        "",
        "CLIENTS CANDIDATS :",
    ]

    for candidat in resultat["clients_candidats"]:
        score_global = candidat.get("score_global")
        score_nom = candidat.get("score_nom")
        score_code = candidat.get("score_code")
        score_adresse = candidat.get("score_adresse")
        score_ville = candidat.get("score_ville")
        score_cadencier = candidat.get(
            "score_cadencier"
        )
        score_ancien = candidat.get("score")

        details_scores: list[str] = []

        if score_global is not None:
            details_scores.append(
                f"global={score_global}"
            )

        if score_nom is not None:
            details_scores.append(
                f"nom={score_nom}"
            )

        if score_code is not None:
            details_scores.append(
                f"code={score_code}"
            )

        if score_adresse is not None:
            details_scores.append(
                f"adresse={score_adresse}"
            )

        if score_ville is not None:
            details_scores.append(
                f"ville={score_ville}"
            )

        if score_cadencier is not None:
            details_scores.append(
                f"cadencier={score_cadencier}"
            )

        if (
            not details_scores
            and score_ancien is not None
        ):
            details_scores.append(
                f"score={score_ancien}"
            )

        lignes.append(
            "- "
            f"{candidat['code_client']} "
            "| "
            f"{candidat['nom_client']} "
            "| "
            + " / ".join(details_scores)
        )

    if not resultat["clients_candidats"]:
        lignes.append("- Aucun client candidat")

    lignes.extend(
        [
            "",
            "ACTION COMMANDE :",
            str(
                resultat.get(
                    "type_action_commande",
                    "creation",
                )
            ),
            "",
            (
                "CLIENT RETENU AUTOMATIQUEMENT : "
                f"{resultat['client_retenu'] or 'NON'}"
            ),
            (
                "DÉCISION AUTOMATIQUE : "
                f"{'OUI' if resultat.get('decision_automatique_client') else 'NON'}"
            ),
            (
                "RAISONS DÉCISION CLIENT : "
                f"{resultat.get('raisons_decision_client', [])}"
            ),
            "",
            "DATE DE LIVRAISON :",
            str(
                resultat["date_livraison"]
                or "Non détectée"
            ),
            "",
            "PRODUITS :",
        ]
    )

    if not resultat["produits"]:
        lignes.append("- Aucun produit détecté")

    for produit in resultat["produits"]:
        quantite_affichee = (
            produit.get("quantite_resolue")
            if produit.get("quantite_resolue")
            is not None
            else produit.get("quantite")
        )
        unite_affichee = (
            produit.get("unite_resolue")
            or produit.get("unite_detectee")
            or "?"
        )
        lignes.append(
            "- Mention : "
            f"{quantite_affichee} "
            f"{unite_affichee} "
            f"de {produit['texte_produit']}"
        )

        if produit["precisions_quantite"]:
            lignes.append(
                "  Précisions de quantité : "
                f"{produit['precisions_quantite']}"
            )

        for candidat in produit["candidats"]:
            lignes.append(
                "    * "
                f"{candidat['code_article']} "
                "| "
                f"{candidat['libelle_article']} "
                f"| score={candidat['score']}"
            )

        lignes.append(
            "  Sélection automatique fiable : "
            + (
                "OUI"
                if produit["produit_fiable"]
                else "NON"
            )
        )

    return "\n".join(lignes)


# -------------------------------------------------------------------
# Commandes / CSV
# -------------------------------------------------------------------

@lru_cache(maxsize=1)
def charger_catalogue_articles_reference() -> list[dict[str, Any]]:
    """Charge le referentiel produit local, independant des commandes evaluees."""
    if not CHEMIN_CATALOGUE_ARTICLES.exists():
        return []
    try:
        payload = json.loads(CHEMIN_CATALOGUE_ARTICLES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload if isinstance(item, dict)]


@lru_cache(maxsize=1)
def charger_unites_articles() -> dict[str, str]:
    """Charge les unités officielles, puis les rares ajustements locaux."""
    unites: dict[str, str] = {}
    if CHEMIN_REFERENCES_CONTROLE.exists():
        try:
            payload = json.loads(
                CHEMIN_REFERENCES_CONTROLE.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            payload = {}
        for code, reference in (
            payload.get("references", {}).items()
            if isinstance(payload, dict)
            else []
        ):
            if not isinstance(reference, dict):
                continue
            unite = str(reference.get("order_unit") or "").strip().upper()
            if code and unite:
                unites[str(code)] = unite

    if CHEMIN_UNITES_ARTICLES.exists():
        with CHEMIN_UNITES_ARTICLES.open(
            "r", encoding="utf-8-sig", newline=""
        ) as fichier:
            for ligne in csv.DictReader(fichier, delimiter=";"):
                code = str(ligne.get("code_article") or "").strip()
                unite = str(ligne.get("unite") or "").strip().upper()
                if code and unite:
                    unites[code] = unite
    return unites


def construire_lignes_commande(
    produits: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    lignes_commande: list[dict[str, Any]] = []
    raisons: list[str] = []
    index_par_code: dict[str, int] = {}
    qualite_par_code: dict[str, tuple[Any, ...]] = {}

    for index, produit in enumerate(produits, start=1):
        selection = produit.get("selection")

        if not selection:
            raisons.append(
                f"produit_non_vendu_ligne_{index}"
            )
            continue

        if not produit.get("produit_fiable", False):
            raisons.append(
                f"produit_non_fiable_ligne_{index}"
            )

        if produit.get("ambigu", False):
            raisons.append(
                f"produit_ambigu_ligne_{index}"
            )

        prix = selection.get("prix")
        unite_ligne = (
            charger_unites_articles().get(str(selection["code_article"]))
            or produit.get("unite_resolue")
            or produit.get("unite_principale")
        )
        if str(unite_ligne or "").upper() == "PCE":
            unite_ligne = "PI"

        if isinstance(prix, (int, float)) and prix == 0:
            raisons.append(
                f"produit_non_vendu_prix_zero_ligne_{index}"
            )

        ligne = {
            "ordre_ligne": index,
            "code_article": selection[
                "code_article"
            ],
            "libelle_article": selection[
                "libelle_article"
            ],
            "quantite": (
                produit.get("quantite_resolue")
                if produit.get("quantite_resolue")
                is not None
                else produit.get(
                    "quantite_principale"
                )
            ),
            "unite": unite_ligne,
            "score_article": selection.get(
                "score_global"
            ),
            "source_recherche": selection.get(
                "source_recherche"
            ),
            "texte_source": produit.get(
                "texte_source"
            ),
            "prix": prix,
        }
        code_article = str(
            selection.get("code_article") or ""
        )
        qualite = (
            bool(produit.get("produit_fiable")),
            not bool(produit.get("ambigu")),
            float(selection.get("score_global") or 0.0),
            float(selection.get("score_selection") or 0.0),
            bool(produit.get("unite_principale")),
            index,
        )
        if code_article in index_par_code:
            raisons.append(
                f"article_duplique_consolide_{code_article}"
            )
            if qualite > qualite_par_code[code_article]:
                position = index_par_code[code_article]
                lignes_commande[position] = ligne
                qualite_par_code[code_article] = qualite
            continue

        index_par_code[code_article] = len(
            lignes_commande
        )
        qualite_par_code[code_article] = qualite
        lignes_commande.append(ligne)

    for ordre, ligne in enumerate(
        lignes_commande,
        start=1,
    ):
        ligne["ordre_ligne"] = ordre

    if not produits:
        raisons.append("produit_non_vendu_aucune_mention")
    elif not lignes_commande:
        raisons.append("produit_non_vendu_aucune_selection")

    return lignes_commande, sorted(set(raisons))


def determiner_statut_commande(
    resultat: dict[str, Any],
) -> tuple[str, list[str], list[dict[str, Any]]]:
    raisons: list[str] = []

    if resultat.get("type_action_commande") == "rappel":
        return "PROBLEMATIQUE", ["message_a_rappeler"], []

    if not resultat.get("client_retenu"):
        raisons.extend(
            resultat.get(
                "raisons_decision_client",
                [],
            )
        )
        raisons.append(
            "client_non_mentionne_ou_non_identifie"
        )

    lignes_commande, raisons_lignes = construire_lignes_commande(
        resultat.get("produits", [])
    )
    raisons.extend(raisons_lignes)

    statut = (
        "VALIDEE"
        if not raisons
        else "PROBLEMATIQUE"
    )

    return statut, sorted(set(raisons)), lignes_commande


def _ecrire_csv_lignes(
    chemin: Path,
    champs: list[str],
    lignes: list[dict[str, Any]],
) -> None:
    chemin.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with chemin.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as fichier:
        writer = csv.DictWriter(
            fichier,
            fieldnames=champs,
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(lignes)


def _base_export_commande(
    commande: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "genere_le": commande["genere_le"],
        "audio_source": commande["fichier_audio"],
        "client_code": commande.get("client_retenu"),
        "client_nom": commande.get(
            "client_nom_retenu", ""
        ),
        "date_livraison": (
            commande.get("date_livraison", {})
            or {}
        ).get("date_iso", ""),
        "statut": commande.get("statut"),
    }


def _ligne_validee_export(
    base: dict[str, Any],
    ligne: dict[str, Any],
) -> dict[str, Any]:
    return {
        **base,
        "ordre_ligne": ligne["ordre_ligne"],
        "code_article": ligne["code_article"],
        "libelle_article": ligne["libelle_article"],
        "quantite": ligne["quantite"],
        "unite": ligne["unite"],
        "score_article": ligne["score_article"],
        "source_recherche": ligne["source_recherche"],
        "texte_source": ligne["texte_source"],
        "prix": ligne["prix"],
    }


def _ligne_problematique_export(
    base: dict[str, Any],
    commande: dict[str, Any],
    raisons_supplementaires: list[str]
    | None = None,
) -> dict[str, Any]:
    raisons = list(
        commande.get("raisons_problematiques", [])
    )
    raisons.extend(raisons_supplementaires or [])

    return {
        **base,
        "statut": "PROBLEMATIQUE",
        "raisons_problematiques": " | ".join(
            sorted(set(raisons))
        ),
        "transcription": commande.get(
            "transcription", ""
        ),
        "nombre_mentions_produits": len(
            commande.get("mentions_produits", [])
        ),
    }


def _appliquer_suppression_lignes_validees(
    lignes_validees: list[dict[str, Any]],
    commande: dict[str, Any],
) -> tuple[int, list[str]]:
    client_code = commande.get("client_retenu")
    date_livraison = (
        (commande.get("date_livraison") or {}).get(
            "date_iso", ""
        )
    )
    codes_a_supprimer = Counter(
        ligne.get("code_article")
        for ligne in commande.get(
            "lignes_commande", []
        )
        if ligne.get("code_article")
    )

    if not client_code or not codes_a_supprimer:
        return 0, []

    indexes_a_supprimer: list[int] = []

    for index in range(
        len(lignes_validees) - 1,
        -1,
        -1,
    ):
        ligne = lignes_validees[index]

        if ligne.get("client_code") != client_code:
            continue

        if (
            date_livraison
            and ligne.get("date_livraison")
            != date_livraison
        ):
            continue

        code_article = ligne.get("code_article")

        if (
            code_article
            and codes_a_supprimer[code_article] > 0
        ):
            indexes_a_supprimer.append(index)
            codes_a_supprimer[code_article] -= 1

            if not any(codes_a_supprimer.values()):
                break

    for index in sorted(
        indexes_a_supprimer,
        reverse=True,
    ):
        del lignes_validees[index]

    codes_restants = [
        code_article
        for code_article, quantite_restante in (
            codes_a_supprimer.items()
        )
        for _ in range(quantite_restante)
    ]

    return len(indexes_a_supprimer), codes_restants


def preparer_exports_commandes(
    commandes: list[dict[str, Any]],
    run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lignes_validees: list[dict[str, Any]] = []
    lignes_problematiques: list[dict[str, Any]] = []

    for commande in commandes:
        base = _base_export_commande(
            commande=commande,
            run_id=run_id,
        )
        type_action = commande.get(
            "type_action_commande",
            "creation",
        )

        if commande.get("statut") != "VALIDEE":
            lignes_problematiques.append(
                _ligne_problematique_export(
                    base=base,
                    commande=commande,
                )
            )
            continue

        if type_action == "suppression":
            nb_supprimees, codes_restants = (
                _appliquer_suppression_lignes_validees(
                    lignes_validees=lignes_validees,
                    commande=commande,
                )
            )

            if nb_supprimees == 0:
                lignes_problematiques.append(
                    _ligne_problematique_export(
                        base=base,
                        commande=commande,
                        raisons_supplementaires=[
                            "suppression_produit_introuvable"
                        ],
                    )
                )
                continue

            if codes_restants:
                raisons = [
                    "suppression_partielle",
                    "codes_restants="
                    + ",".join(codes_restants),
                ]
                lignes_problematiques.append(
                    _ligne_problematique_export(
                        base=base,
                        commande=commande,
                        raisons_supplementaires=raisons,
                    )
                )

            continue

        for ligne in commande.get(
            "lignes_commande", []
        ):
            lignes_validees.append(
                _ligne_validee_export(
                    base=base,
                    ligne=ligne,
                )
            )

    return lignes_validees, lignes_problematiques


def exporter_csv_commandes(
    commandes: list[dict[str, Any]],
    run_id: str,
) -> tuple[Path, Path]:
    (
        lignes_validees,
        lignes_problematiques,
    ) = preparer_exports_commandes(
        commandes=commandes,
        run_id=run_id,
    )

    chemin_validees = (
        DOSSIER_COMMANDES_VALIDEES
        / "commandes_validees.csv"
    )
    chemin_problematiques = (
        DOSSIER_COMMANDES_PROBLEMATIQUES
        / "commandes_problematiques.csv"
    )

    _ecrire_csv_lignes(
        chemin=chemin_validees,
        champs=[
            "run_id",
            "genere_le",
            "audio_source",
            "client_code",
            "client_nom",
            "date_livraison",
            "statut",
            "ordre_ligne",
            "code_article",
            "libelle_article",
            "quantite",
            "unite",
            "score_article",
            "source_recherche",
            "texte_source",
            "prix",
        ],
        lignes=lignes_validees,
    )

    _ecrire_csv_lignes(
        chemin=chemin_problematiques,
        champs=[
            "run_id",
            "genere_le",
            "audio_source",
            "client_code",
            "client_nom",
            "date_livraison",
            "statut",
            "raisons_problematiques",
            "nombre_mentions_produits",
            "transcription",
        ],
        lignes=lignes_problematiques,
    )

    return chemin_validees, chemin_problematiques


# -------------------------------------------------------------------
# Programme principal
# -------------------------------------------------------------------

DATE_FICHIER_REPONDEUR_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[_ -](\d{2})[-h](\d{2})")


def date_reference_depuis_nom_fichier(nom_fichier: str) -> date | None:
    match = DATE_FICHIER_REPONDEUR_RE.search(nom_fichier)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def heure_reference_depuis_nom_fichier(nom_fichier: str) -> int | None:
    match = DATE_FICHIER_REPONDEUR_RE.search(nom_fichier)
    if not match:
        return None
    try:
        return int(match.group(2))
    except ValueError:
        return None


def telephone_depuis_nom_fichier(nom_fichier: str) -> str:
    match = re.search(
        r"_De-([^_.]+)",
        nom_fichier,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return normaliser_telephone(match.group(1))


def traiter_transcriptions(
    chemins_transcriptions: list[Path] | None = None,
    date_reference: date | None = None,
) -> list[dict[str, Any]]:
    DOSSIER_RESULTATS.mkdir(
        parents=True,
        exist_ok=True,
    )

    clients = charger_clients()
    cadencier = charger_cadencier()
    unites_articles = charger_unites_articles()
    for produits_client in cadencier.values():
        for produit in produits_client:
            produit["unite_vente"] = unites_articles.get(
                str(produit.get("code_article") or ""), ""
            )
    articles_reference = charger_catalogue_articles_reference()
    for article in articles_reference:
        code = str(article.get("code_article") or "")
        article["unite_vente"] = unites_articles.get(code, "")

    nb_clients_ajoutes = enrichir_clients_depuis_cadencier(
        clients=clients,
        cadencier=cadencier,
    )
    stats_ventes = charger_stats_ventes_clients()
    enrichir_clients_avec_stats_ventes(
        clients=clients,
        stats_ventes=stats_ventes,
    )
    catalogue_global = construire_catalogue_global(
        cadencier,
        articles_reference=articles_reference,
    )
    variantes_clients = charger_variantes_clients(
        CHEMIN_VARIANTES_CLIENTS
    )
    telephones_clients = charger_telephones_clients(
        CHEMIN_TELEPHONES_CLIENTS
    )
    synonymes_produits = charger_synonymes_produits(
        CHEMIN_SYNONYMES_PRODUITS
    )
    enrichir_alias_avec_variantes(
        clients=clients,
        variantes_par_code=variantes_clients,
    )
    enrichir_clients_avec_telephones(
        clients=clients,
        telephones_par_code=telephones_clients,
    )

    fichiers = (
        sorted(chemins_transcriptions)
        if chemins_transcriptions is not None
        else sorted(
            DOSSIER_TRANSCRIPTIONS.glob(
                "*__transcription.json"
            )
        )
    )

    if not fichiers:
        raise RuntimeError(
            "Aucune transcription JSON trouvée dans : "
            f"{DOSSIER_TRANSCRIPTIONS}"
        )

    print(f"Clients chargés : {len(clients)}")
    print(
        "Clients ajoutés depuis cadencier : "
        f"{nb_clients_ajoutes}"
    )
    print(f"Clients avec cadencier : {len(cadencier)}")
    print(
        "Catalogue global articles : "
        f"{len(catalogue_global)}"
    )
    print(
        "Clients avec variantes manuelles : "
        f"{len(variantes_clients)}"
    )
    print(
        "Clients avec telephones manuels : "
        f"{len(telephones_clients)}"
    )
    print(
        "Entrées synonymes produits : "
        f"{len(synonymes_produits)}"
    )
    print("")

    commandes: list[dict[str, Any]] = []

    for chemin in fichiers:
        transcription = lire_transcription(
            chemin
        )
        date_reference_commande = (
            date_reference
            if date_reference is not None
            else date_reference_depuis_nom_fichier(chemin.name)
        )
        action_commande = detecter_type_action_commande(
            transcription
        )

        mentions = (
            []
            if action_commande["type_action"] == "rappel"
            else extraire_mentions_produits(transcription)
        )
        if (
            action_commande["type_action"]
            == "suppression"
            and not mentions
        ):
            mentions = extraire_mentions_suppression(
                transcription
            )

        identification_client = identifier_client(
            transcription=transcription,
            clients=clients,
            cadencier=cadencier,
            mentions_produits=mentions,
            telephone_appel=telephone_depuis_nom_fichier(
                chemin.name
            ),
        )

        clients_candidats = identification_client[
            "candidats"
        ]

        client_retenu = identification_client[
            "client_retenu"
        ]
        client_nom_retenu = identification_client.get(
            "client_nom_retenu", ""
        )

        produits = (
            []
            if action_commande["type_action"] == "rappel"
            else chercher_produits(
                mentions=mentions,
                produits_client=cadencier.get(
                    client_retenu,
                    [],
                ),
                catalogue_global=catalogue_global,
                synonymes_produits=synonymes_produits,
            )
        )

        resultat = {
            "fichier_audio": chemin.name.replace(
                "__transcription.json",
                ".ogg",
            ),
            "fichier_transcription": chemin.name,
            "genere_le": datetime.now().isoformat(),
            "transcription": transcription,
            "type_action_commande": action_commande[
                "type_action"
            ],
            "expression_action_commande": action_commande[
                "expression"
            ],
            "zone_client_detectee": identification_client[
                "zone_client"
            ],
            "clients_candidats": clients_candidats,
            "client_retenu": client_retenu,
            "client_nom_retenu": client_nom_retenu,
            "decision_automatique_client": identification_client[
                "decision_automatique"
            ],
            "raisons_decision_client": identification_client[
                "raisons_decision"
            ],
            "identification_client": identification_client,
            "date_livraison": resoudre_date_livraison(
                transcription,
                date_reference=date_reference_commande,
                heure_reference=heure_reference_depuis_nom_fichier(
                    chemin.name
                ),
            ),
            "mentions_produits": mentions,
            "produits": produits,
        }

        statut, raisons_problematiques, lignes_commande = (
            determiner_statut_commande(
                resultat
            )
        )
        resultat["statut"] = statut
        resultat[
            "raisons_problematiques"
        ] = raisons_problematiques
        resultat[
            "lignes_commande"
        ] = lignes_commande

        resultat["ai_arbitrage"] = {
            "enabled": False,
            "api_key_available": False,
            "applied": False,
            "skipped": "traitement_exclusivement_sur_instance_locale",
        }

        chemin_json = (
            DOSSIER_RESULTATS
            / chemin.name.replace(
                "__transcription.json",
                "__extraction.json",
            )
        )

        chemin_txt = (
            DOSSIER_RESULTATS
            / chemin.name.replace(
                "__transcription.json",
                "__extraction.txt",
            )
        )

        chemin_json.write_text(
            json.dumps(
                resultat,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        chemin_txt.write_text(
            creer_resume_txt(resultat),
            encoding="utf-8",
        )

        print(f"Extraction : {chemin.name}")
        print(
            "  action : "
            f"{action_commande['type_action']}"
        )
        print(
            "  client retenu : "
            f"{client_retenu or 'aucun - à vérifier'}"
        )
        print(
            "  décision auto client : "
            + (
                "OUI"
                if identification_client[
                    "decision_automatique"
                ]
                else "NON"
            )
        )
        print(f"  mentions produits : {len(mentions)}")
        print(f"  statut : {statut}")
        print(f"  TXT : {chemin_txt}")
        print("")

        commandes.append(resultat)

    return commandes


def main() -> None:
    run_id = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )
    commandes = traiter_transcriptions()
    chemin_validees, chemin_problematiques = (
        exporter_csv_commandes(
            commandes=commandes,
            run_id=run_id,
        )
    )
    print("CSV commandes validées :", chemin_validees)
    print(
        "CSV commandes problématiques :",
        chemin_problematiques,
    )


if __name__ == "__main__":
    main()
