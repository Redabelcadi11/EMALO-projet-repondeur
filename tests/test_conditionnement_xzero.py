from src.produits import chercher_produits, extraire_mentions_produits


def test_conditionnement_xzero_ne_provoque_pas_de_division_par_zero() -> None:
    mentions = extraire_mentions_produits("2 creme")
    produit = {
        "code_article": "X0",
        "libelle_article": "CREME X0",
        "libelle_normalise": "creme x0",
        "prix": 1.0,
        "unite_vente": "PCE",
        "quantite_habituelle_commande": 2.0,
        "ratio_net_par_unite": 0.0,
        "nb_ventes_article_total": 1,
        "nb_ventes_article_recentes": 1,
        "derniere_vente_article_ordinal": 1,
    }
    resultat = chercher_produits(
        mentions, [produit], [produit], {}, 3
    )[0]
    assert resultat["quantite_resolue"] == 2.0
