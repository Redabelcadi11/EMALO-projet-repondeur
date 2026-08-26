from __future__ import annotations

from src.normalisation import normaliser_texte
from src.produits import chercher_produits


def _article(
    code: str,
    libelle: str,
    volume_historique_total: float,
) -> dict:
    return {
        "code_article": code,
        "libelle_article": libelle,
        "libelle_normalise": normaliser_texte(libelle),
        "unite_vente": "PI",
        "prix": 5.0,
        "nb_ventes_article_total": 3,
        "nb_ventes_article_recentes": 3,
        "volume_historique_total": volume_historique_total,
        "source_article": "historique_client",
    }


def test_volume_historique_departage_des_variantes_proches() -> None:
    """Le volume livre prevaut sur un simple nombre de lignes egal."""
    mirin = _article(
        "MIRIN",
        "VIN BLANC MIRIN CUISSON 400ML",
        1.6,
    )
    vce = _article(
        "VCE",
        "VIN BLANC VCE 11 DEG 10L",
        20.0,
    )
    mention = {
        "texte_source": "5 litres de vin blanc",
        "texte_normalise": "5 litres de vin blanc",
        "produit_normalise": "vin blanc",
        "texte_produit": "vin blanc",
        "quantite_principale": 5.0,
        "quantite": 5.0,
        "unite_principale": "L",
        "unite_detectee": "L",
        "precisions_quantite": [],
        "conditionnement_multiple": None,
        "ambigu": False,
        "raisons_ambiguite": [],
    }

    resultat = chercher_produits(
        [mention],
        [mirin, vce],
        [mirin, vce],
        {},
    )[0]

    assert resultat["selection"]["code_article"] == "VCE"
    assert "volume_historique_client_departage" in resultat[
        "selection"
    ]["raisons"]


def test_volume_historique_ne_sauve_pas_un_candidat_hors_sujet() -> None:
    eau = _article("EAU", "EAU MINERALE 1L", 1000.0)
    vin = _article("VIN", "VIN BLANC 1L", 1.0)
    mention = {
        "texte_source": "5 litres de vin blanc",
        "texte_normalise": "5 litres de vin blanc",
        "produit_normalise": "vin blanc",
        "texte_produit": "vin blanc",
        "quantite_principale": 5.0,
        "quantite": 5.0,
        "unite_principale": "L",
        "unite_detectee": "L",
        "precisions_quantite": [],
        "conditionnement_multiple": None,
        "ambigu": False,
        "raisons_ambiguite": [],
    }

    resultat = chercher_produits(
        [mention],
        [eau, vin],
        [eau, vin],
        {},
    )[0]

    assert resultat["selection"]["code_article"] == "VIN"
