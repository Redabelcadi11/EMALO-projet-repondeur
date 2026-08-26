from __future__ import annotations

from extraire_informations import charger_reappro_basco
from src.produits import (
    chercher_produits,
)


def test_reappro_actif_expose_des_libelles_normalises() -> None:
    charger_reappro_basco.cache_clear()
    reappro = charger_reappro_basco()

    par_code = {article["code_article"]: article for article in reappro}
    assert par_code["03051900"]["libelle_normalise"] == (
        "lait avoine alpro boisson vegetal 1l"
    )
    assert par_code["03051901"]["libelle_normalise"] == (
        "lait amande alpro boisson vegetal 1l"
    )


def test_grand_pool_reappro_retrouve_les_boissons_vegetales() -> None:
    charger_reappro_basco.cache_clear()
    reappro = charger_reappro_basco()
    mentions = [
        {
            "texte_source": "6 litres de lait d avoine longue dlc",
            "produit_normalise": "lait d avoine longue dlc",
            "quantite_principale": 6.0,
            "unite_principale": "L",
        },
        {
            "texte_source": "6 litres de lait d amande longue dlc",
            "produit_normalise": "lait d amande longue dlc",
            "quantite_principale": 6.0,
            "unite_principale": "L",
        },
    ]

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=[],
        catalogue_global=[],
        synonymes={},
        catalogue_reappro=reappro,
    )

    attendus = ["03051900", "03051901"]
    for resultat, code_attendu in zip(resultats, attendus, strict=True):
        candidat = next(
            candidat
            for candidat in resultat["candidats"]
            if candidat["code_article"] == code_attendu
        )
        assert candidat["source_recherche"] == "catalogue_reappro"
        assert candidat["score_texte"] == 54.0
