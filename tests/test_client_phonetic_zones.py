from __future__ import annotations

from src.clients import enrichir_alias_avec_variantes, identifier_client
from src.produits import extraire_mentions_produits


def _client(code: str, nom: str, ville: str, aliases: list[str]) -> dict:
    return {
        "code_client": code,
        "nom_client": nom,
        "ville": ville,
        "adresse_1": "",
        "adresse_2": "",
        "code_postal": "",
        "telephones": [],
        "aliases": aliases,
    }


def test_hibaya_est_rapproche_de_ibaia_avec_bayonne_et_cadencier() -> None:
    clients = [
        _client("IBAIABA", "IBAIA LMDB", "BAYONNE", ["ibaia"]),
        _client("IBAIA", "HOTEL IBAIA", "HENDAYE", ["ibaia"]),
    ]
    cadencier = {
        "IBAIABA": [
            {
                "code_article": "00444832",
                "libelle_article": "BURRATA DI BUFALA 125G X8P",
                "libelle_normalise": "burrata di bufala 125g x8p",
            },
            {
                "code_article": "00010903",
                "libelle_article": "CHIPIRON PATAGONICA 900G",
                "libelle_normalise": "chipiron patagonica 900g",
            },
        ]
    }
    transcription = (
        "Bonjour pour le restaurant Hibaya a Bayonne. Pour aujourd'hui, "
        "il me faudra un carton de burrata de bufala et deux cartons de chipiron."
    )

    resultat = identifier_client(
        transcription,
        clients,
        cadencier,
        extraire_mentions_produits(transcription),
    )

    assert resultat["client_retenu"] == "IBAIABA"


def test_corps_commande_ne_peut_plus_devenir_nom_client() -> None:
    clients = [
        _client("TICABAMAYA", "LE TI CABANON MAYARCO", "SAINT JEAN DE LUZ", ["ti cabanon"]),
        _client("SARDA", "SARDA YVAN", "HENDAYE", ["sarda"]),
        _client("NONAME", "BAR AU VINGT", "BAYONNE", ["au vingt"]),
    ]
    enrichir_alias_avec_variantes(
        clients,
        {"TICABAMAYA": ["ticabannon", "ti cabanon acotz"]},
    )
    transcription = (
        "Bonsoir, c'est le restaurant Ticabannon a Cotes. Pour demain matin, "
        "il nous faudrait vingt litres de vin blanc, deux kilos de frigo la "
        "sarda et un carton de rabas."
    )

    resultat = identifier_client(
        transcription,
        clients,
        {"TICABAMAYA": []},
        extraire_mentions_produits(transcription),
    )

    assert resultat["client_retenu"] == "TICABAMAYA"
    assert resultat["candidats"][0]["code_client"] == "TICABAMAYA"


def test_livraison_et_dimension_ne_creent_pas_de_faux_produits() -> None:
    transcription = (
        "Bonjour pour le restaurant Hibaya a Bayonne. Pour aujourd'hui, "
        "il me faudra un carton de burrata, des poches sous vide en petites "
        "20-30 si vous avez et un carton de rabas pour le restaurant Hibaya "
        "a Bayonne pour aujourd'hui."
    )

    produits = [
        mention["produit_normalise"]
        for mention in extraire_mentions_produits(transcription)
    ]

    assert "pour aujourd hui" not in produits
    assert not any(produit.startswith("30 si vous avez") for produit in produits)
    assert any("20x30" in produit for produit in produits)
    assert "rabas" in produits


def test_verbes_de_commande_et_client_final_ne_sont_pas_des_produits() -> None:
    ruisseau = (
        "Michel, au restaurant du ruisseau a Bidart. Il me faudrait prendre "
        "demain deux cartons de cote d'agneau. Merci."
    )
    francois = (
        "Le bar Francois Bayens. Il me faudrait rajouter une boite 5-1 de "
        "concassus de tomates et il me faudrait egalement un sac de 5 kilos "
        "de riz US pour le bar Francois Bayens. Merci."
    )

    mentions_ruisseau = extraire_mentions_produits(ruisseau)
    mentions_francois = extraire_mentions_produits(francois)

    assert [m["produit_normalise"] for m in mentions_ruisseau] == [
        "cote d agneau"
    ]
    assert [m["produit_normalise"] for m in mentions_francois] == [
        "concassus de tomates",
        "riz us",
    ]


def test_nom_compose_avec_particules_bat_ressemblance_phonetique_courte() -> None:
    clients = [
        _client("MAISONPIERRE", "SAS LA MAISON DE PIERRE", "HASPARREN", ["maison de pierre"]),
        _client("MADISOLANO", "MADISON", "ANGLET", ["madison"]),
        _client("PIERREBAY", "CHEZ PIERRE", "BAYONNE", ["chez pierre"]),
    ]
    transcription = (
        "Bonjour, c'est le restaurant La Maison de Pierre a Aspary. "
        "Il me faudrait dix kilos de fraises surgelees."
    )
    resultat = identifier_client(
        transcription, clients, {"MAISONPIERRE": []},
        extraire_mentions_produits(transcription),
    )
    assert resultat["client_retenu"] == "MAISONPIERRE"
    assert resultat["candidats"][0]["match_nom_exact"] is True


def test_doublon_enseigne_prefere_code_avec_cadencier() -> None:
    clients = [
        _client("BASTA", "RESTAURANT LE BASTA", "BIARRITZ", ["le basta"]),
        _client("BASTABTZ", "LE BASTA EURL", "BIARRITZ", ["le basta"]),
    ]
    transcription = "Bonjour, le restaurant Le Basta. Il me faudrait quinze burrata."
    cadencier = {
        "BASTABTZ": [{
            "code_article": "00444832",
            "libelle_article": "BURRATA DI BUFALA 125G X8P",
            "libelle_normalise": "burrata di bufala 125g x8p",
        }]
    }
    resultat = identifier_client(
        transcription, clients, cadencier,
        extraire_mentions_produits(transcription),
    )
    assert resultat["client_retenu"] == "BASTABTZ"
