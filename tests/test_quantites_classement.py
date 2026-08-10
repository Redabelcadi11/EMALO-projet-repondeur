from pathlib import Path

import extraire_informations as extraction
from src.produits import (
    _resoudre_quantite_commande_candidat,
    _score_selection_ponderee,
)


def _resoudre(quantite: float, unite: str, candidat: dict) -> dict:
    mention = {
        "quantite_principale": quantite,
        "unite_principale": unite,
        "conditionnement_multiple": None,
    }
    return _resoudre_quantite_commande_candidat(mention, candidat)


def test_quantite_kg_reste_en_kg_quand_unite_vente_kg() -> None:
    resultat = _resoudre(
        2,
        "KG",
        {
            "libelle_normalise": "beurre doux 250g",
            "unite_vente": "KG",
            "ratio_net_par_unite": 0.25,
        },
    )
    assert (resultat["quantite_resolue"], resultat["unite_resolue"]) == (2.0, "KG")


def test_six_litres_d_un_pack_six_fois_un_litre_font_un_pack() -> None:
    resultat = _resoudre(
        6,
        "L",
        {
            "libelle_normalise": "lait uht 6x1l",
            "unite_vente": "PACK",
            "ratio_net_par_unite": 1.03,
        },
    )
    assert (resultat["quantite_resolue"], resultat["unite_resolue"]) == (1.0, "PACK")


def test_cartons_convertis_selon_colisage_officiel() -> None:
    resultat = _resoudre(
        2,
        "CAR",
        {
            "code_article": "00404828",
            "libelle_normalise": "mozzarella rapee 2.5k",
            "unite_vente": "POC",
            "quantite_habituelle_commande": 99,
        },
    )
    assert (resultat["quantite_resolue"], resultat["unite_resolue"]) == (8.0, "POC")


def test_seize_pieces_en_cartons_de_six_arrondissent_a_trois() -> None:
    resultat = _resoudre(
        16,
        "PCE",
        {
            "libelle_normalise": "burrata 125g x6p",
            "unite_vente": "CAR",
        },
    )
    assert (resultat["quantite_resolue"], resultat["unite_resolue"]) == (3.0, "CAR")


def test_unite_interne_piece_devient_pi_en_sortie(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "unites-articles.csv"
    reference.write_text("code_article;unite\n", encoding="utf-8")
    monkeypatch.setattr(extraction, "CHEMIN_UNITES_ARTICLES", reference)
    extraction.charger_unites_articles.cache_clear()
    lignes, _ = extraction.construire_lignes_commande(
        [
            {
                "selection": {
                    "code_article": "TEST",
                    "libelle_article": "TEST",
                    "prix": 1.0,
                },
                "quantite_resolue": 1.0,
                "unite_resolue": "PCE",
                "produit_fiable": True,
                "ambigu": False,
            }
        ]
    )
    assert lignes[0]["unite"] == "PI"


def test_classement_pondere_priorise_cadencier_pertinent() -> None:
    client = {
        "score_texte": 65.0,
        "score_conditionnement": 25.0,
        "dans_cadencier_client": True,
        "nb_ventes_article_total": 8,
        "nb_ventes_article_recentes": 3,
    }
    global_ = {
        "score_texte": 82.0,
        "score_conditionnement": 25.0,
        "dans_cadencier_client": False,
        "nb_ventes_article_total": 8,
        "nb_ventes_article_recentes": 3,
    }
    assert _score_selection_ponderee(client) > _score_selection_ponderee(global_)
