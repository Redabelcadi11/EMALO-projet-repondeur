from __future__ import annotations

import pytest

from src.produits import (
    analyser_role_semantique_clause,
    extraire_mentions_produits,
)


TENOY = (
    "Oui, bonjour, c'est la maison Tenoy a Leon dans les Landes. "
    "Je souhaitais completer ma commande pour ce vendredi 21 aout avec "
    "des glaces en tholin. Il me faudrait un bac de chocolat, un pistache, "
    "un mangue, un citron vert, un framboise, deux caramels sales et deux "
    "vanilles en 5 litres. Je vous remercie."
)


def _produits(texte: str) -> list[str]:
    return [
        mention["produit_normalise"]
        for mention in extraire_mentions_produits(texte)
    ]


def test_tenoy_ne_cree_ni_client_ni_discours_ni_date_comme_produit() -> None:
    mentions = extraire_mentions_produits(TENOY)
    produits = [mention["produit_normalise"] for mention in mentions]

    assert len(mentions) == 7
    assert all(mention["quantite_principale"] in {1.0, 2.0} for mention in mentions)
    assert not any("commande" in produit for produit in produits)
    assert not any("aout" in produit or "tholin" in produit for produit in produits)
    assert produits == [
        "glace chocolat",
        "glace pistache",
        "glace mangue",
        "glace citron vert",
        "glace framboise",
        "glace caramels sales",
        "glace vanilles en",
    ]


@pytest.mark.parametrize(
    "texte",
    (
        "pour vendredi 21 aout, deux sacs de farine",
        "pour lundi 3 septembre 2026, deux sacs de farine",
        "le 9 janvier, deux sacs de farine",
        "demain matin, deux sacs de farine",
    ),
)
def test_date_n_est_jamais_interpretee_comme_quantite_article(texte: str) -> None:
    mentions = extraire_mentions_produits(texte)

    assert len(mentions) == 1
    assert mentions[0]["produit_normalise"] == "farine"
    assert mentions[0]["quantite_principale"] == 2.0


def test_discours_de_complement_date_sans_article_est_rejete() -> None:
    texte = "je souhaitais completer ma commande pour ce vendredi"

    assert analyser_role_semantique_clause(texte) == "ORDER_DISCOURSE"
    assert extraire_mentions_produits(texte) == []


def test_identite_etablissement_sans_quantite_est_rejetee() -> None:
    texte = "maison Tenoy a Leon dans les Landes"

    assert analyser_role_semantique_clause(texte) == "CLIENT"
    assert extraire_mentions_produits(texte) == []


def test_entete_de_famille_n_est_pas_une_ligne_mais_transmet_le_contexte() -> None:
    produits = _produits(
        "Pour les glaces, deux vanilles, un chocolat et trois pistaches."
    )

    assert produits == ["glace vanilles", "glace chocolat", "glace pistaches"]


def test_produit_sans_quantite_n_est_pas_supprime_hors_structure_entete() -> None:
    assert _produits("des tomates sechees") == ["tomates sechees"]


def test_date_preserve_le_produit_place_apres_une_presentation_client() -> None:
    produits = _produits(
        "Maison Amae a Saint Jean de Luz pour demain il me faudrait "
        "6l de lait, 15 burrata."
    )

    assert produits == ["lait", "burrata"]


def test_date_finale_ne_supprime_pas_le_dernier_produit() -> None:
    produits = _produits(
        "Pour la Tireuse Biarritz pour mercredi 12 aout. Je voudrais "
        "six poches de mozzarella, six poches de galettes de ble et "
        "six pots de guacamole pour la Tireuse Biarritz pour mercredi "
        "12 aout."
    )

    assert produits == ["mozzarella", "galettes de ble", "guacamole"]
