from __future__ import annotations

from src.clients import identifier_client
from src.produits import (
    _analyser_conditionnement_article,
    _resoudre_quantite_commande_candidat,
)


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


def _resoudre_glace(
    quantite: float,
    unite: str | None,
    texte_source: str,
    libelle: str,
) -> dict:
    return _resoudre_quantite_commande_candidat(
        {
            "quantite_principale": quantite,
            "unite_principale": unite,
            "conditionnement_multiple": None,
            "texte_source": texte_source,
        },
        {
            "code_article": "GLACE-TEST",
            "libelle_article": libelle,
            "libelle_normalise": libelle.casefold().replace(".", " "),
            "unite_vente": "BOITE",
        },
    )


def test_format_decimal_implicite_d_un_bac_n_est_pas_une_quantite_fractionnaire() -> None:
    resultat = _resoudre_glace(
        2.5,
        None,
        "2.5 citron vert",
        "2.5L CITRON VERT SORBET ARTISANAL",
    )

    assert (resultat["quantite_resolue"], resultat["unite_resolue"]) == (
        1.0,
        "BOITE",
    )


def test_quantite_commerciale_explicite_ne_devient_jamais_un_format_de_bac() -> None:
    resultat = _resoudre_glace(
        5,
        "BOITE",
        "5 boites de glace chocolat",
        "5L CHOCOLAT CREME GLACEE ARTISANALE",
    )

    assert (resultat["quantite_resolue"], resultat["unite_resolue"]) == (
        5.0,
        "BOITE",
    )


def test_volume_explicitement_prononce_reste_converti_en_nombre_de_bacs() -> None:
    resultat = _resoudre_glace(
        5,
        "L",
        "5 litres de glace chocolat",
        "5L CHOCOLAT CREME GLACEE ARTISANALE",
    )

    assert (resultat["quantite_resolue"], resultat["unite_resolue"]) == (
        1.0,
        "BOITE",
    )


def test_compte_de_pieces_sans_x_dans_le_libelle_est_structure() -> None:
    candidat = {
        "code_article": "VIANDE-TEST",
        "libelle_article": "BAVETTE TRANCHEE 10P +/-200G",
        "libelle_normalise": "bavette tranchee 10p 200g",
        "unite_vente": "POC",
    }

    meta = _analyser_conditionnement_article(candidat)
    resultat = _resoudre_quantite_commande_candidat(
        {
            "quantite_principale": 20,
            "unite_principale": None,
            "conditionnement_multiple": None,
            "texte_source": "20 bavettes tranchees sous vide",
        },
        candidat,
    )

    assert meta["nb_items_par_unite"] == 10
    assert (resultat["quantite_resolue"], resultat["unite_resolue"]) == (
        2.0,
        "POC",
    )


def test_emballage_explicitement_prononce_ne_se_divise_pas_par_son_colisage() -> None:
    resultat = _resoudre_quantite_commande_candidat(
        {
            "quantite_principale": 20,
            "unite_principale": "POC",
            "conditionnement_multiple": None,
            "texte_source": "20 poches de bavettes tranchees",
        },
        {
            "code_article": "VIANDE-TEST",
            "libelle_article": "BAVETTE TRANCHEE 10P +/-200G",
            "libelle_normalise": "bavette tranchee 10p 200g",
            "unite_vente": "POC",
        },
    )

    assert (resultat["quantite_resolue"], resultat["unite_resolue"]) == (
        20.0,
        "POC",
    )


def test_nom_phonetique_distinctif_n_est_pas_evince_par_des_villes_seules() -> None:
    clients = [
        _client(
            "BIURARTE",
            "SAS BI UR ARTE",
            "HENDAYE",
            ["bi ur arte", "biurarte"],
        ),
        *[
            _client(
                f"DECOY{index}",
                f"ETABLISSEMENT TEMOIN {index}",
                "ANDAIL",
                [f"etablissement temoin {index}"],
            )
            for index in range(12)
        ],
    ]
    transcription = (
        "Commande pour le biourarte a Andail, il me faudra un carton de "
        "tagliatelles."
    )

    resultat = identifier_client(
        transcription=transcription,
        clients=clients,
        cadencier={},
        mentions_produits=[],
    )

    assert resultat["client_retenu"] == "BIURARTE"


def test_enseigne_explicite_apres_la_date_reste_une_zone_client() -> None:
    clients = [
        _client(
            "PARISHEND",
            "BRASSERIE DE L HOTEL DE PARIS",
            "HENDAYE",
            ["brasserie de l hotel de paris"],
        ),
        _client(
            "AUTREHEND",
            "BRASSERIE DU PORT",
            "HENDAYE",
            ["brasserie du port"],
        ),
    ]
    transcription = (
        "Bonjour, pour ce jeudi a la brasserie de l'hotel de Paris a "
        "Hendaye, j'aurais besoin d'un kilo d'amandes."
    )

    resultat = identifier_client(
        transcription=transcription,
        clients=clients,
        cadencier={},
        mentions_produits=[],
    )

    assert resultat["client_retenu"] == "PARISHEND"
    assert "brasserie de l hotel de paris" in resultat["zone_client"] or any(
        candidat["code_client"] == "PARISHEND"
        and candidat["match_nom_exact"]
        for candidat in resultat["candidats"]
    )
