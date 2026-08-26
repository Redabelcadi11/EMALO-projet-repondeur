from __future__ import annotations

from src.produits import _resoudre_quantite_commande_candidat


def mention(quantite: float, unite: str) -> dict:
    return {
        "quantite_principale": quantite,
        "unite_principale": unite,
        "conditionnement_multiple": None,
        "texte_source": "",
    }


def candidat(code: str, libelle: str) -> dict:
    return {
        "code_article": code,
        "libelle_article": libelle,
        "libelle_normalise": libelle.casefold(),
        "unite_vente": "",
        "quantite_habituelle_commande": 0,
        "ratio_net_par_unite": 0,
    }


def test_deux_cartons_frites_donnent_huit_poches() -> None:
    resultat = _resoudre_quantite_commande_candidat(
        mention(2, "CAR"),
        candidat(
            "000S0685",
            "FRITE ALLUMETTE 7/7 BI-TEMP LUTOSA 2.5K",
        ),
    )

    assert resultat["quantite_resolue"] == 8
    assert resultat["unite_resolue"] == "POC"
    assert (
        "colisage_controle_references_officiel"
        in resultat["raisons_resolution"]
    )


def test_controle_officiel_prime_sur_facteur_rabas_estime() -> None:
    resultat = _resoudre_quantite_commande_candidat(
        mention(2, "CAR"),
        candidat(
            "00011115",
            "RABAS - LAMELLE DE CALAMAR PANEE 1K",
        ),
    )

    assert resultat["quantite_resolue"] == 8
    assert resultat["unite_resolue"] == "POC"


def test_seize_burratas_donnent_trois_cartons() -> None:
    resultat = _resoudre_quantite_commande_candidat(
        mention(16, "PCE"),
        candidat(
            "00404831",
            "BURRATA VACHE 125G X6P",
        ),
    )

    assert resultat["quantite_resolue"] == 3
    assert resultat["unite_resolue"] == "CAR"


def test_un_carton_sucre_donne_cinq_paquets() -> None:
    resultat = _resoudre_quantite_commande_candidat(
        mention(1, "CAR"),
        candidat("00P51315", "SUCRE SEMOULE 1K"),
    )

    assert resultat["quantite_resolue"] == 5
    assert resultat["unite_resolue"] == "PAQUET"


def test_un_colis_lait_reste_un_pack() -> None:
    resultat = _resoudre_quantite_commande_candidat(
        mention(1, "COL"),
        candidat(
            "00401120",
            "LAIT 1/2 ECREME UHT 6X1L",
        ),
    )

    assert resultat["quantite_resolue"] == 1
    assert resultat["unite_resolue"] == "PACK"
