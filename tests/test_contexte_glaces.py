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


def test_enumeration_glace_canonise_une_saveur_flechie_ambiguë() -> None:
    mentions = extraire_mentions_produits(
        "Pour les glaces, deux pistaches, deux carameles et une fraise."
    )
    lignes = {
        item["texte_produit"]: item["quantite_principale"]
        for item in mentions
    }

    assert lignes["glace caramel"] == 2.0


def test_contexte_glace_ne_transforme_pas_un_noyau_place_avant_la_saveur() -> None:
    mentions = extraire_mentions_produits(
        "Un carton de muffins au chocolat. Deux glaces chocolat. "
        "Deux glaces coco."
    )
    produits = [item["produit_normalise"] for item in mentions]

    assert "glaces chocolat" in produits
    assert "muffins au chocolat" in produits
    assert "glace muffins au chocolat" not in produits
