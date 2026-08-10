from __future__ import annotations

from extraire_informations import construire_lignes_commande


def _produit(
    code: str,
    quantite: float,
    *,
    fiable: bool,
    ambigu: bool,
    score: float,
) -> dict:
    return {
        "produit_fiable": fiable,
        "ambigu": ambigu,
        "quantite_resolue": quantite,
        "unite_resolue": "PCE",
        "unite_principale": "PCE",
        "texte_source": f"{quantite:g} article {code}",
        "selection": {
            "code_article": code,
            "libelle_article": f"ARTICLE {code}",
            "score_global": score,
            "score_selection": score,
            "source_recherche": "cadencier_client",
            "prix": 1.0,
        },
    }


def test_consolide_un_article_repete_et_garde_occurrence_fiable() -> None:
    lignes, raisons = construire_lignes_commande(
        [
            _produit(
                "A1",
                2.0,
                fiable=False,
                ambigu=True,
                score=45.0,
            ),
            _produit(
                "A1",
                12.0,
                fiable=True,
                ambigu=False,
                score=80.0,
            ),
        ]
    )

    assert len(lignes) == 1
    assert lignes[0]["code_article"] == "A1"
    assert lignes[0]["quantite"] == 12.0
    assert lignes[0]["ordre_ligne"] == 1
    assert "article_duplique_consolide_A1" in raisons


def test_ne_consolide_pas_deux_articles_differents() -> None:
    lignes, _ = construire_lignes_commande(
        [
            _produit(
                "A1",
                1.0,
                fiable=True,
                ambigu=False,
                score=80.0,
            ),
            _produit(
                "A2",
                2.0,
                fiable=True,
                ambigu=False,
                score=80.0,
            ),
        ]
    )

    assert [ligne["code_article"] for ligne in lignes] == [
        "A1",
        "A2",
    ]
    assert [ligne["ordre_ligne"] for ligne in lignes] == [1, 2]
