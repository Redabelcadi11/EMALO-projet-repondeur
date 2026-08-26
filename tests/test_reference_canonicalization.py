from __future__ import annotations

from extraire_informations import _canonicaliser_code_article_reference


def test_ancien_code_sucre_devient_reference_officielle() -> None:
    assert (
        _canonicaliser_code_article_reference(
            "00050315",
            "SUCRE SEMOULE 1K",
        )
        == "00P51315"
    )


def test_code_officiel_existant_reste_inchange() -> None:
    assert (
        _canonicaliser_code_article_reference(
            "00404831",
            "BURRATA VACHE 125G X6P",
        )
        == "00404831"
    )


def test_libelle_inconnu_ne_change_pas_le_code() -> None:
    assert (
        _canonicaliser_code_article_reference(
            "ANCIEN-CODE",
            "ARTICLE ABSENT DU CONTROLE",
        )
        == "ANCIEN-CODE"
    )
