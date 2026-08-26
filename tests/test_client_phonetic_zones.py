from __future__ import annotations

from src.clients import (
    candidats_pour_arbitrage_llm,
    client_requiert_arbitrage_llm,
    enrichir_alias_avec_variantes,
    filtrer_mentions_client_resolu,
    identifier_client,
)
from src import llm_arbitrage
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


def test_nom_phonetique_partiel_exige_une_ville_compatible() -> None:
    clients = [
        _client("CIBLE", "LE KANTTU", "HENDAYE", ["kanttu"]),
        _client("AUTRE", "LE CANTOU", "OLORON", ["cantou"]),
    ]
    resultat = identifier_client(
        "Bonsoir, le cantuo sur Hendaya, il me faudrait deux cartons de frites.",
        clients,
        {},
        extraire_mentions_produits("deux cartons de frites"),
        telephone_appel="0612345678",
    )

    assert resultat["client_retenu"] == "CIBLE"
    assert resultat["candidats"][0]["score_ville"] >= 85


def test_ville_explicite_et_enseigne_asr_contredisent_telephone_sans_confondre_matin() -> None:
    clients = [
        {
            **_client(
                "BAHIABID",
                "RESTAURANT LE BAHIA BEACH",
                "BIDART",
                ["bahia beach"],
            ),
            "telephones": ["0559265969"],
        },
        {
            **_client(
                "BEBERTBTZ",
                "BEBERT PERSO",
                "BIDART",
                ["bebert perso"],
            ),
            "telephones": ["0763003079"],
        },
        _client(
            "MATTIN",
            "RESTAURANT CHEZ MATTIN",
            "CIBOURE",
            ["chez mattin"],
        ),
    ]
    transcription = (
        "Bonjour, c'est le Bayabich a Bidart pour le mardi matin. "
        "Deux cartons de chipiron."
    )

    resultat = identifier_client(
        transcription,
        clients,
        {"BAHIABID": [], "BEBERTBTZ": [], "MATTIN": []},
        extraire_mentions_produits("Deux cartons de chipiron."),
        telephone_appel="0763003079",
    )
    par_code = {
        candidat["code_client"]: candidat
        for candidat in resultat["candidats"]
    }

    # La ville explicite et l'enseigne ASR forte battent ici le telephone
    # contradictoire ; le terme horaire "mardi matin" ne cree pas MATTIN.
    assert resultat["client_retenu"] == "BAHIABID"
    assert "enseigne_ville_contredit_telephone" in resultat[
        "raisons_decision"
    ]
    assert "MATTIN" not in par_code
    assert par_code["BAHIABID"]["score_ville"] == 100
    assert par_code["BAHIABID"]["score_enseigne_contextuel"] >= 70
    assert client_requiert_arbitrage_llm(
        resultat["candidats"], resultat["client_retenu"]
    ) is False

    candidats_llm = candidats_pour_arbitrage_llm(
        resultat["candidats"], resultat["client_retenu"]
    )
    assert {candidat["code_client"] for candidat in candidats_llm} == {
        "BAHIABID", "BEBERTBTZ"
    }


def test_nom_court_dans_adresse_declenche_arbitrage_client() -> None:
    clients = [
        _client("LAMERPARIS", "LA MER", "PARIS", ["la mer"]),
        {
            **_client(
                "OCEANHDYE",
                "L OCEAN HENDAYE",
                "HENDAYE",
                ["l ocean hendaye"],
            ),
            "adresse_1": "1 boulevard de la mer",
        },
    ]
    resultat = identifier_client(
        "Bonsoir, restaurant L Ocean a Indail, boulevard de la mer.",
        clients,
        {"LAMERPARIS": [], "OCEANHDYE": []},
        [],
    )

    assert resultat["client_retenu"] == "LAMERPARIS"
    assert client_requiert_arbitrage_llm(
        resultat["candidats"],
        resultat["client_retenu"],
    ) is True


def test_presentation_enseigne_ville_asr_est_exclue_sans_perdre_un_produit() -> None:
    client = _client(
        "CIBLE",
        "RESTAURANT EXEMPLE",
        "BIDART",
        ["enseigne exemple"],
    )
    candidat = {
        "score_ville": 100.0,
        "score_enseigne_contextuel": 85.0,
    }
    mentions = [
        {
            "segment_id": "segment-1",
            "texte_source": "ensigne exampeule a bidart pour mardi matin",
            "produit_normalise": "ensigne exampeule a bidart",
            "quantite_principale": None,
        },
        {
            "segment_id": "segment-2",
            "texte_source": "deux cartons de chipiron",
            "produit_normalise": "chipiron",
            "quantite_principale": 2,
        },
    ]

    conservees, exclues = filtrer_mentions_client_resolu(
        mentions,
        client,
        candidat,
        zone_client="bonjour c est ensigne exampeule a bidart",
    )

    assert [mention["segment_id"] for mention in conservees] == ["segment-2"]
    assert exclues == [
        {
            "segment_id": "segment-1",
            "texte_source": "ensigne exampeule a bidart pour mardi matin",
            "role_semantique": "CLIENT",
        }
    ]


def test_arbitre_llama_client_est_borne_aux_candidats(monkeypatch) -> None:
    candidats = [
        {
            "code_client": "LAMERPARIS",
            "nom_client": "LA MER",
            "ville": "PARIS",
            "adresse_1": "",
        },
        {
            "code_client": "OCEANHDYE",
            "nom_client": "L OCEAN HENDAYE",
            "ville": "HENDAYE",
            "adresse_1": "SASU MEL KF",
            "adresse_2": "1 boulevard de la mer",
        },
    ]
    capture: dict[str, str] = {}

    def repondre(prompt: str, **kwargs: object) -> str:
        capture["prompt"] = prompt
        return "2"

    monkeypatch.setattr(
        llm_arbitrage,
        "_call_ollama",
        repondre,
    )

    choix = llm_arbitrage.arbitrer_client_ambigu(
        "restaurant l ocean a indail boulevard de la mer",
        candidats,
    )

    assert choix == candidats[1]
    assert "1 boulevard de la mer" in capture["prompt"]


def test_client_resolu_est_exclu_des_mentions_sans_perdre_le_produit() -> None:
    client = _client(
        "CIBLE",
        "CAFE DU PORT",
        "ANGLET",
        ["cafe du port"],
    )
    mentions = [
        {
            "segment_id": "segment-1",
            "texte_source": "cafe du port anglette",
            "produit_normalise": "cafe du port anglette",
        },
        {
            "segment_id": "segment-2",
            "texte_source": "deux cartons de gaufres",
            "produit_normalise": "gaufres",
        },
        {
            "segment_id": "segment-3",
            "texte_source": "anglette",
            "produit_normalise": "anglette",
            "quantite_principale": None,
        },
    ]
    conservees, exclues = filtrer_mentions_client_resolu(
        mentions,
        client,
        {
            "nom_distinctif": True,
            "match_nom_exact": False,
            "match_telephone_exact": False,
        },
    )

    assert [mention["segment_id"] for mention in conservees] == ["segment-2"]
    assert exclues == [
        {
            "segment_id": "segment-1",
            "texte_source": "cafe du port anglette",
            "role_semantique": "CLIENT",
        },
        {
            "segment_id": "segment-3",
            "texte_source": "anglette",
            "role_semantique": "CLIENT",
        },
    ]


def test_produit_quantifie_homonyme_enseigne_garde_sa_source_quantifiee() -> None:
    """Un article homonyme de l'enseigne reste une ligne de commande."""
    client = _client(
        "BALEINEHDYE",
        "LA BALEINE HENDAYE - SAS TALOAK",
        "HENDAYE",
        ["la baleine hendaye", "sas taloak", "baleine hendaye"],
    )
    candidat = {
        "match_telephone_exact": True,
        "match_nom_exact": True,
        "nom_distinctif": True,
        "score_ville": 100.0,
        "score_enseigne_contextuel": 96.0,
    }
    mentions = extraire_mentions_produits(
        "bonjour c est la baleine sas taloak, "
        "quatre cartons de taloak"
    )

    conservees, exclues = filtrer_mentions_client_resolu(
        mentions,
        client,
        candidat,
        zone_client="bonjour c est la baleine sas taloak",
    )

    assert [item["texte_source"] for item in conservees] == [
        "4 cartons de taloak"
    ]
    assert conservees[0]["quantite_principale"] == 4.0
    assert exclues == []


def test_adresse_complete_client_resolu_ne_devient_pas_un_produit() -> None:
    client = {
        **_client("OCEANHDYE", "L OCEAN HENDAYE", "HENDAYE", ["l ocean"]),
        "adresse_1": "SASU MEL KF",
        "adresse_2": "1 boulevard de la mer",
    }
    mentions = [
        {
            "segment_id": "segment-1",
            "texte_source": "boulevard de la mer",
            "produit_normalise": "boulevard de la mer",
        },
        {
            "segment_id": "segment-2",
            "texte_source": "deux packs de lait",
            "produit_normalise": "lait",
        },
    ]

    conservees, exclues = filtrer_mentions_client_resolu(mentions, client)

    assert [mention["segment_id"] for mention in conservees] == ["segment-2"]
    assert exclues == [
        {
            "segment_id": "segment-1",
            "texte_source": "boulevard de la mer",
            "role_semantique": "CLIENT",
        }
    ]


def test_enseigne_abregee_et_ville_sont_exclues_apres_telephone_verrouille() -> None:
    client = _client(
        "CLIENT",
        "LA PLANCHA D ILBARRITZ",
        "BIDART",
        ["la plancha d ilbarritz", "plancha"],
    )
    candidat = {
        "match_alias_telephone_confirme": True,
        "match_telephone_info_exact": False,
        "match_telephone_exact": True,
        "match_nom_exact": False,
        "nom_distinctif": False,
        "score_ville": 100.0,
        "score_enseigne_contextuel": 70.0,
    }
    mentions = [
        {
            "segment_id": "client",
            "texte_source": "la plancha bidar",
            "produit_normalise": "plancha bidar",
            "quantite_principale": None,
        },
        {
            "segment_id": "produit",
            "texte_source": "deux huiles pour plancha",
            "produit_normalise": "huiles pour plancha",
            "quantite_principale": 2.0,
        },
    ]

    conservees, exclues = filtrer_mentions_client_resolu(
        mentions, client, candidat
    )

    assert [item["segment_id"] for item in conservees] == ["produit"]
    assert [item["segment_id"] for item in exclues] == ["client"]
