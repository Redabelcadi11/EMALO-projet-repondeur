from __future__ import annotations

from pathlib import Path

from src.clients import (
    calculer_score_adresse,
    enrichir_alias_avec_variantes,
    enrichir_clients_avec_telephones,
    identifier_client,
)
from src.normalisation import normaliser_texte
from src.produits import (
    charger_synonymes_produits,
    chercher_produits,
    extraire_mentions_produits,
)


COMPLEMENT_BELLOTEKA = (
    "La bibliotheque, c'est pour faire un complement sur la commande "
    "que j'ai passee precedemment, je vais rajouter, s'il vous plait, "
    "quatre poches de filets de poulet. Merci."
)

COMMANDE_BELLOTEKA = (
    "Bonsoir a la bibliotheque. Pour demain, s'il vous plait, il me "
    "faudrait six litres de creme liquide, une boite en conserve de "
    "piquillos, cinq kilos, une boite en conserve de concentre de "
    "tomates, un bidon d'acide, cinq bouteilles de vinaigre blanc et "
    "cinq kilos de pate penne. Pour la bibliotheque, merci."
)


def _article(
    code: str,
    libelle: str,
    unite: str,
    prix: float,
    ratio: float = 0.0,
    quantite_habituelle: float = 1.0,
    ventes: int = 5,
) -> dict:
    return {
        "code_article": code,
        "libelle_article": libelle,
        "libelle_normalise": normaliser_texte(libelle),
        "unite_vente": unite,
        "prix": prix,
        "ratio_net_par_unite": ratio,
        "quantite_habituelle_commande": quantite_habituelle,
        "nb_ventes_article_total": ventes,
        "nb_ventes_article_recentes": 2,
        "derniere_vente_article_iso": "2026-06-19",
        "derniere_vente_article_ordinal": 739786,
    }


def _cadencier_belloteka() -> list[dict]:
    return [
        _article("00401203", "CREME UHT 35% HELIOR 6X1L", "PACK", 4.799, 1.0),
        _article("00090122", "PIQUILLOS LANIERES PERU 3/1", "BOITE", 10.989, 3.0),
        _article("00050817", "DOUBLE CONCENTRE DE TOMATE 28% 4/4", "BOITE", 4.266, 0.88),
        _article("03051243", "ACIDE ASCORBIQUE 1K", "PI", 5.0, 1.0),
        _article("00051268", "VINAIGRE BLANC 8° 1,5L", "PI", 1.179, 1.5, 3.0, 21),
        _article("00004108", "BARILLA PENNE RIGATE 5K", "POC", 4.19, 5.0),
        _article(
            "00095619",
            "FILET DE POULET JAUNE SELECTION DU BOUCHER 250G S/V X10",
            "POC",
            9.0,
            0.0,
            2.0,
        ),
    ]


def test_complement_ne_produit_que_le_filet_de_poulet() -> None:
    mentions = extraire_mentions_produits(COMPLEMENT_BELLOTEKA)

    assert [mention["produit_normalise"] for mention in mentions] == [
        "filets de poulet"
    ]
    assert mentions[0]["quantite"] == 4.0


def test_belloteka_est_identifiee_sans_faux_match_adresse_c() -> None:
    clients = [
        {
            "code_client": "BELLOTEBTZ",
            "nom_client": "LA BELLOTEKA BIARRITZ",
            "ville": "BIARRITZ",
            "adresse_1": "8 RUE DU CENTRE",
            "adresse_2": "",
            "code_postal": "64200",
            "telephones": [],
            "aliases": ["la belloteka biarritz"],
        },
        {
            "code_client": "LACARCE",
            "nom_client": "LACARCE PHILIPPE",
            "ville": "CIBOURE",
            "adresse_1": "APPARTEMENT 61 ETAGE 6",
            "adresse_2": "BATIMENT C",
            "code_postal": "64500",
            "telephones": ["0540395867"],
            "aliases": ["lacarce philippe"],
        },
    ]
    enrichir_alias_avec_variantes(
        clients,
        {"BELLOTEBTZ": ["la bibliotheque", "bibliotheque"]},
    )
    enrichir_clients_avec_telephones(
        clients,
        {"BELLOTEBTZ": ["0609511676"]},
    )
    cadencier = {"BELLOTEBTZ": _cadencier_belloteka()}

    resultat = identifier_client(
        transcription=COMPLEMENT_BELLOTEKA,
        clients=clients,
        cadencier=cadencier,
        mentions_produits=extraire_mentions_produits(COMPLEMENT_BELLOTEKA),
        telephone_appel="0609511676",
    )

    assert resultat["client_retenu"] == "BELLOTEBTZ"
    score_adresse, _ = calculer_score_adresse(
        "la bibliotheque c est pour faire un complement",
        "APPARTEMENT 61 ETAGE 6",
        "BATIMENT C",
        "64500",
    )
    assert score_adresse < 100.0


def test_commande_belloteka_utilise_les_six_references_du_cadencier() -> None:
    pool = _cadencier_belloteka()
    mentions = extraire_mentions_produits(COMMANDE_BELLOTEKA)
    synonymes = charger_synonymes_produits(
        Path(__file__).resolve().parents[1] / "config" / "synonymes-produits.json"
    )

    produits = chercher_produits(
        mentions=mentions,
        produits_client=pool,
        catalogue_global=pool,
        synonymes=synonymes,
    )

    assert [mention["produit_normalise"] for mention in mentions] == [
        "creme liquide",
        "piquillos",
        "concentre de tomates",
        "acide",
        "vinaigre blanc",
        "pate penne",
    ]
    assert [produit["selection"]["code_article"] for produit in produits] == [
        "00401203",
        "00090122",
        "00050817",
        "03051243",
        "00051268",
        "00004108",
    ]
    assert all(produit["produit_fiable"] for produit in produits)

