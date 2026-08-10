from __future__ import annotations

from src.produits import extraire_mentions_produits


def test_remerciement_ne_devient_pas_un_produit() -> None:
    mentions = extraire_mentions_produits(
        "Il faudrait un carton d'oeufs, un sachet de filet de poulet, "
        "un peu de moutarde et un bidon d'huile d'olive. "
        "Je vous remercie, au revoir."
    )

    produits = [mention["produit_normalise"] for mention in mentions]
    assert len(produits) == 4
    assert not any("remerc" in produit for produit in produits)


def test_sous_titrage_ne_devient_pas_un_produit() -> None:
    mentions = extraire_mentions_produits(
        "Il me faudrait un foie gras et deux sachets de feuilles de briques. "
        "Sous-titrage FR."
    )

    produits = [mention["produit_normalise"] for mention in mentions]
    assert len(produits) == 2
    assert not any("titrage" in produit for produit in produits)


def test_unites_est_normalise_comme_pieces() -> None:
    mentions = extraire_mentions_produits(
        "Il me faudrait seize unités de burrata."
    )

    assert len(mentions) == 1
    assert mentions[0]["quantite_principale"] == 16
    assert mentions[0]["unite_principale"] == "PCE"
    assert mentions[0]["produit_normalise"] == "burrata"
