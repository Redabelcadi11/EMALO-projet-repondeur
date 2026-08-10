from src.produits import extraire_mentions_produits


def test_contexte_glace_propage_saveurs_et_formats() -> None:
    mentions = extraire_mentions_produits(
        "Il me faut des glaces : vanille grand format 4, "
        "chocolat grand format 2, petit format 1 yaourt, "
        "une framboise, un citron, un caramel, "
        "deux fraises, deux mangues, deux pistaches et deux cafes."
    )
    lignes = {
        item["texte_produit"]: item["quantite_principale"]
        for item in mentions
    }

    assert lignes["glace vanille grand format"] == 4.0
    assert lignes["glace chocolat grand format"] == 2.0
    assert lignes["glace yaourt petit format"] == 1.0
    assert lignes["glace framboise"] == 1.0
    assert lignes["glace citron"] == 1.0
    assert lignes["glace caramel"] == 1.0
    assert lignes["glace fraises"] == 2.0
    assert lignes["glace mangues"] == 2.0
    assert lignes["glace pistaches"] == 2.0
    assert lignes["glace cafes"] == 2.0


def test_saveur_isolee_ne_devient_pas_glace_sans_contexte() -> None:
    mentions = extraire_mentions_produits("Il me faut deux citrons")
    assert mentions[0]["texte_produit"] == "citrons"
