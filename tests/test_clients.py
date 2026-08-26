from __future__ import annotations

from pathlib import Path

from extraire_informations import (
    CHEMIN_VARIANTES_CLIENTS,
    charger_cadencier,
    charger_clients,
    charger_stats_ventes_clients,
    enrichir_clients_avec_stats_ventes,
    enrichir_clients_depuis_cadencier,
    extraire_mentions_produits,
)
from src.clients import (
    extraire_zone_presentation_client,
    calculer_score_nom_client,
    enrichir_alias_avec_variantes,
    enrichir_clients_avec_telephones,
    identifier_client,
    normaliser_telephones,
)


def _charger_referentiels() -> tuple[list[dict], dict]:
    clients = charger_clients()
    cadencier = charger_cadencier()
    enrichir_clients_depuis_cadencier(
        clients=clients,
        cadencier=cadencier,
    )
    enrichir_clients_avec_stats_ventes(
        clients=clients,
        stats_ventes=charger_stats_ventes_clients(),
    )

    variantes = {}
    if Path(CHEMIN_VARIANTES_CLIENTS).exists():
        import json

        variantes = json.loads(
            Path(CHEMIN_VARIANTES_CLIENTS).read_text(
                encoding="utf-8"
            )
        )

    enrichir_alias_avec_variantes(
        clients=clients,
        variantes_par_code=variantes,
    )

    return clients, cadencier


def test_score_nom_evite_faux_positif_sous_chaine() -> None:
    zone = "Bonjour, c'est les affranchis"

    score_affranchis, _ = calculer_score_nom_client(
        zone,
        {
            "aliases": ["les affranchis"],
        },
    )

    score_ranch, _ = calculer_score_nom_client(
        zone,
        {
            "aliases": ["sarl le ranch", "ranch"],
        },
    )

    assert score_affranchis >= 95
    assert score_ranch <= 30


def test_identification_audio2_nom_et_cadencier() -> None:
    clients, cadencier = _charger_referentiels()

    transcription = (
        "Bonjour, c'est Les Affranchis, je voudrais cinq litres de "
        "vanille crème glacée, je voudrais deux litres cinq de caramel "
        "beurre sel, je voudrais un kilo de moutarde, deux litres de "
        "blanc d'œuf, ça serait pour demain, merci beaucoup."
    )

    mentions = extraire_mentions_produits(transcription)
    resultat = identifier_client(
        transcription=transcription,
        clients=clients,
        cadencier=cadencier,
        mentions_produits=mentions,
    )

    assert resultat["candidats"]
    assert resultat["candidats"][0]["code_client"] == "AFFRANCHILAB"
    assert resultat["client_retenu"] == "AFFRANCHILAB"
    assert resultat["decision_automatique"] is True

    ranch = next(
        (
            candidat
            for candidat in resultat["candidats"]
            if candidat["code_client"] == "RANCH"
        ),
        None,
    )

    if ranch is not None:
        assert ranch["score_cadencier"] == 0.0
        assert ranch["score_global"] < 40


def test_identification_client_par_numero_appelant() -> None:
    clients = [
        {
            "code_client": "BALEINE",
            "nom_client": "BAR DE LA BALEINE",
            "ville": "BIARRITZ",
            "adresse_1": "",
            "adresse_2": "",
            "code_postal": "",
            "telephones": ["0559000000"],
            "aliases": ["bar de la baleine", "baleine"],
        },
        {
            "code_client": "BALEINEHDYE",
            "nom_client": "LA BALEINE HENDAYE - SAS TALOAK",
            "ville": "HENDAYE",
            "adresse_1": "BD DE LA MER",
            "adresse_2": "",
            "code_postal": "64700",
            "telephones": ["0620148088"],
            "aliases": [
                "la baleine hendaye",
                "la baleine",
                "taloak",
            ],
        },
    ]

    resultat = identifier_client(
        transcription=(
            "Bonjour c'est la baleine, pour demain il faudrait "
            "quatre cartons de steak hache."
        ),
        clients=clients,
        cadencier={},
        mentions_produits=[],
        telephone_appel="06 20 14 80 88",
    )

    assert resultat["client_retenu"] == "BALEINEHDYE"
    assert resultat["decision_automatique"] is True
    assert (
        "client_identifie_par_telephone"
        in resultat["raisons_decision"]
    )


def test_telephone_partage_departage_par_nom_prononce() -> None:
    clients = [
        {
            "code_client": "HOTEL_A",
            "nom_client": "HOTEL ALPHA",
            "ville": "BAYONNE",
            "adresse_1": "",
            "adresse_2": "",
            "code_postal": "",
            "telephones": ["0612345678"],
            "aliases": ["hotel alpha"],
            "nb_commandes_recentes": 1,
        },
        {
            "code_client": "HOTEL_B",
            "nom_client": "HOTEL BRAVO",
            "ville": "BIARRITZ",
            "adresse_1": "",
            "adresse_2": "",
            "code_postal": "",
            "telephones": ["0612345678"],
            "aliases": ["hotel bravo"],
            "nb_commandes_recentes": 9,
        },
    ]

    resultat = identifier_client(
        transcription=(
            "Bonjour, ici l'hotel Alpha. Il nous faudrait un carton "
            "de frites pour demain."
        ),
        clients=clients,
        cadencier={},
        mentions_produits=[],
        telephone_appel="06 12 34 56 78",
    )

    assert resultat["client_retenu"] == "HOTEL_A"
    assert "departage_nom_exact" in resultat["raisons_decision"]


def test_telephone_configure_remplace_un_ancien_proprietaire() -> None:
    clients = [
        {"code_client": "ANCIEN", "telephones": ["0612345678"]},
        {"code_client": "CONFIRME", "telephones": []},
    ]

    enrichir_clients_avec_telephones(
        clients,
        {"CONFIRME": ["0612345678"]},
    )

    assert clients[0]["telephones"] == []
    assert clients[1]["telephones"] == ["0612345678"]


def test_normaliser_telephones_extrait_plusieurs_valeurs_sans_les_fusionner() -> None:
    assert normaliser_telephones(
        "06 12 34 56 78 // 07.98.76.54.32 - contact"
    ) == ["0612345678", "0798765432"]
    # Un prefixe incomplet apres le separateur n'est pas un second numero et
    # ne doit surtout pas etre concatene avec le precedent.
    assert normaliser_telephones("05 59 25 69 26 // 07") == ["0559256926"]


def test_normaliser_telephones_corrige_les_confusions_visuelles() -> None:
    assert normaliser_telephones("O6 I2 34 S6 7B") == ["0612345678"]
    # Excel peut supprimer le zero initial lorsqu'une cellule est numerique.
    assert normaliser_telephones(612345678) == ["0612345678"]


def test_identification_audio3_departage_par_cadencier() -> None:
    clients, cadencier = _charger_referentiels()

    transcription = (
        "Bonjour, c'est le bistrot des filles. "
        "Je voudrais un filet mignon de porc, 600 grammes, "
        "deux litres cinq de fraises sorbet, "
        "une boîte de mayonnaise cinq litres et vingt litres de crème."
    )

    mentions = extraire_mentions_produits(transcription)
    resultat = identifier_client(
        transcription=transcription,
        clients=clients,
        cadencier=cadencier,
        mentions_produits=mentions,
    )

    assert resultat["candidats"]
    assert resultat["candidats"][0]["code_client"] == "BISTFILLES"
    assert resultat["client_retenu"] == "BISTFILLES"
    if len(resultat["candidats"]) >= 2:
        assert (
            resultat["candidats"][0]["score_global"]
            >= resultat["candidats"][1]["score_global"]
        )


def test_zone_client_coupee_avant_produits() -> None:
    transcription = (
        "Et bonjour monsieur, c'est le Negua Biarritz à l'appareil, "
        "douze litres de crème, un jaune d'œuf liquide, un litre."
    )
    zone = extraire_zone_presentation_client(
        transcription
    )

    assert "negua biarritz" in zone
    assert "douze litres" not in zone


def test_alias_generique_ne_prend_pas_le_pas_sur_nom_distinctif() -> None:
    clients = [
        {
            "code_client": "FRONBIDA",
            "nom_client": "RESTAURANT DU FRONTON BIDART",
            "ville": "BIDART",
            "aliases": [
                "restaurant du fronton bidart",
                "fronton bidart",
                "fronton",
            ],
        },
        {
            "code_client": "AIRRIALTAR",
            "nom_client": "RESTAURANT L AIRRIAL",
            "ville": "TARNOS",
            "aliases": [
                "restaurant l airrial",
                "airrial",
                "restaurant",
            ],
        },
    ]

    resultat = identifier_client(
        transcription=(
            "bonjour restaurant du frontant a l appareil"
        ),
        clients=clients,
        cadencier={},
        mentions_produits=[],
    )

    assert resultat["client_retenu"] == "FRONBIDA"


def test_identification_audio6_negua() -> None:
    clients, cadencier = _charger_referentiels()

    transcription = (
        "Et bonjour monsieur, c'est le Negua Biarritz à l'appareil, "
        "douze litres de crème, un jaune d'œuf liquide, un litre, "
        "et ce sera pour demain, merci."
    )

    mentions = extraire_mentions_produits(transcription)
    resultat = identifier_client(
        transcription=transcription,
        clients=clients,
        cadencier=cadencier,
        mentions_produits=mentions,
    )

    assert resultat["client_retenu"] == "NEGUABTZ"


def test_identification_par_adresse_seule() -> None:
    clients = [
        {
            "code_client": "SPOTBAR",
            "nom_client": "SPOT BAR",
            "ville": "BIARRITZ",
            "adresse_1": "14 avenue de Verdun",
            "adresse_2": "",
            "code_postal": "64200",
            "aliases": [
                "spot bar",
            ],
        },
        {
            "code_client": "HOTPYR",
            "nom_client": "HOTEL PYRENEES ATLANTIQUES",
            "ville": "BIARRITZ",
            "adresse_1": "27 rue du Helder",
            "adresse_2": "",
            "code_postal": "64200",
            "aliases": [
                "hotel pyrenees atlantiques",
            ],
        },
    ]

    resultat = identifier_client(
        transcription=(
            "bonjour, c'est au 27 rue du helder a l'appareil, "
            "je voudrais deux litres de creme"
        ),
        clients=clients,
        cadencier={},
        mentions_produits=[
            {
                "texte_produit": "creme",
            }
        ],
    )

    assert resultat["client_retenu"] == "HOTPYR"
    assert resultat["candidats"][0]["score_adresse"] >= 90


def test_identification_client_annonce_en_fin_de_message() -> None:
    clients = [
        {
            "code_client": "PARIS1",
            "nom_client": "RESTAURANT LE PARIS",
            "ville": "BAYONNE",
            "adresse_1": "",
            "adresse_2": "",
            "code_postal": "",
            "aliases": [
                "restaurant le paris",
                "le paris",
            ],
            "derniere_vente_iso": "2026-03-20",
            "derniere_vente_ordinal": 739696,
            "nb_lignes_ventes": 12,
            "nb_lignes_ventes_recentes": 6,
            "nb_commandes_total": 4,
            "nb_commandes_recentes": 2,
            "montant_recent": 120.0,
        }
    ]

    resultat = identifier_client(
        transcription=(
            "je voudrais deux kilos de beurre doux pour demain "
            "merci restaurant le paris"
        ),
        clients=clients,
        cadencier={},
        mentions_produits=[
            {
                "texte_produit": "beurre doux",
            }
        ],
    )

    assert resultat["client_retenu"] == "PARIS1"
    assert "client_identifie_par_nom_exact" in resultat[
        "raisons_decision"
    ]


def test_homonymes_departages_par_recence_des_ventes() -> None:
    clients = [
        {
            "code_client": "PARIS_OLD",
            "nom_client": "RESTAURANT LE PARIS",
            "ville": "BAYONNE",
            "adresse_1": "",
            "adresse_2": "",
            "code_postal": "",
            "aliases": [
                "restaurant le paris",
            ],
            "derniere_vente_iso": "2026-03-10",
            "derniere_vente_ordinal": 739686,
            "nb_lignes_ventes": 40,
            "nb_lignes_ventes_recentes": 8,
            "nb_commandes_total": 10,
            "nb_commandes_recentes": 3,
            "montant_recent": 300.0,
        },
        {
            "code_client": "PARIS_RECENT",
            "nom_client": "RESTAURANT LE PARIS",
            "ville": "BAYONNE",
            "adresse_1": "",
            "adresse_2": "",
            "code_postal": "",
            "aliases": [
                "restaurant le paris",
            ],
            "derniere_vente_iso": "2026-03-25",
            "derniere_vente_ordinal": 739701,
            "nb_lignes_ventes": 35,
            "nb_lignes_ventes_recentes": 15,
            "nb_commandes_total": 9,
            "nb_commandes_recentes": 5,
            "montant_recent": 420.0,
        },
    ]

    resultat = identifier_client(
        transcription=(
            "bonjour c'est restaurant le paris a l'appareil"
        ),
        clients=clients,
        cadencier={},
        mentions_produits=[],
    )

    assert resultat["client_retenu"] == "PARIS_RECENT"
    assert "departage_recence_ventes" in resultat[
        "raisons_decision"
    ]


def test_variante_bouchon_basque_pointe_vers_la_part_des_anges() -> None:
    clients = [
        {
            "code_client": "PARTANGES",
            "nom_client": "LA PART DES ANGES",
            "ville": "BAYONNE",
            "adresse_1": "",
            "adresse_2": "",
            "code_postal": "",
            "aliases": [
                "la part des anges",
                "bouchon basque",
            ],
            "derniere_vente_iso": "2026-03-25",
            "derniere_vente_ordinal": 739701,
            "nb_lignes_ventes": 62,
            "nb_lignes_ventes_recentes": 28,
            "nb_commandes_total": 16,
            "nb_commandes_recentes": 7,
            "montant_recent": 650.0,
        },
        {
            "code_client": "PARTSOUST",
            "nom_client": "LA PART DES ANGES SARL",
            "ville": "SOUSTONS",
            "adresse_1": "",
            "adresse_2": "",
            "code_postal": "",
            "aliases": [
                "la part des anges",
                "bouchon basque",
            ],
            "derniere_vente_iso": "2026-03-20",
            "derniere_vente_ordinal": 739696,
            "nb_lignes_ventes": 60,
            "nb_lignes_ventes_recentes": 19,
            "nb_commandes_total": 14,
            "nb_commandes_recentes": 5,
            "montant_recent": 540.0,
        },
    ]

    resultat = identifier_client(
        transcription=(
            "bonjour c'est bouchon basque je voudrais deux kilos de beurre"
        ),
        clients=clients,
        cadencier={},
        mentions_produits=[
            {
                "texte_produit": "beurre",
            }
        ],
    )

    assert resultat["client_retenu"] == "PARTANGES"
