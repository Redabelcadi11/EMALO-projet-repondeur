from src.produits import (
    _incompatibilites_semantiques,
    _resoudre_quantite_commande_candidat,
    _score_correspondance_produit,
    extraire_mentions_produits,
)


def test_tempete_de_repetition_whisper_est_reduite() -> None:
    transcription = (
        "Il faudrait un pot de bouillon, deux litres de lait de coco, "
        "un bidon de blanc d'oeuf, un pot de ricotta, "
        "un litre de lait de coco, un bidon de blanc d'oeuf, un pot de ricotta, "
        "un litre de lait de coco, un bidon de blanc d'oeuf, un pot de ricotta, "
        "un litre de lait de coco, un pot de ricotta et un pot de mascarpone."
    )
    mentions = extraire_mentions_produits(transcription)
    produits = [item["texte_produit"] for item in mentions]
    assert produits.count("lait de coco") == 1
    assert produits.count("blanc d oeuf") == 1
    assert produits.count("ricotta") == 1
    assert "mascarpone" in produits


def test_quantite_habituelle_ne_devient_pas_un_facteur_colisage() -> None:
    resultat = _resoudre_quantite_commande_candidat(
        {
            "quantite_principale": 2,
            "unite_principale": "CAR",
            "conditionnement_multiple": None,
        },
        {
            "libelle_normalise": "tagliatelle aux oeufs 500g",
            "unite_vente": "BOITE",
            "quantite_habituelle_commande": 8,
        },
    )
    assert (resultat["quantite_resolue"], resultat["unite_resolue"]) == (2.0, "BOITE")


def test_carton_sans_unite_article_reste_un_colis() -> None:
    resultat = _resoudre_quantite_commande_candidat(
        {
            "quantite_principale": 1,
            "unite_principale": "CAR",
            "conditionnement_multiple": None,
            "texte_source": "1 carton de cuisse de poulet",
        },
        {
            "libelle_normalise": "cuisse de poulet x5k",
            "unite_vente": "",
            "quantite_habituelle_commande": 1,
            "ratio_net_par_unite": 5,
        },
    )
    assert (resultat["quantite_resolue"], resultat["unite_resolue"]) == (1.0, "COL")


def test_oeufs_simples_ne_selectionnent_pas_une_brioche() -> None:
    oeufs = _score_correspondance_produit("oeufs", "oeufs frais x90p", None)
    brioche = _score_correspondance_produit("oeufs", "brioche tressee aux oeufs frais", None)
    assert oeufs > brioche + 30


def test_jambon_blanc_ne_selectionne_pas_du_blanc_oeuf() -> None:
    jambon = _score_correspondance_produit("jambon blanc", "jambon blanc superieur", None)
    oeuf = _score_correspondance_produit("jambon blanc", "blanc oeuf liquide", None)
    assert jambon > oeuf + 30


def test_grand_format_glace_prefere_cinq_litres() -> None:
    grand = _score_correspondance_produit(
        "glace vanille grand format", "5l vanille creme glacee artisanale", None
    )
    petit = _score_correspondance_produit(
        "glace vanille grand format", "2.5l vanille creme glacee artisanale", None
    )
    assert grand > petit + 25


def test_variantes_produit_explicites_sont_bloquantes() -> None:
    assert _incompatibilites_semantiques(
        "sucre semoule", "sucre glace 1kg"
    ) == ["variante_sucre_contradictoire"]
    assert _incompatibilites_semantiques(
        "mozzarella rapee", "burrata vache 125g x6p"
    )
    assert _incompatibilites_semantiques(
        "parmesan en copeaux", "parmigiano reggiano bloc 1kg"
    ) == ["forme_parmesan_contradictoire"]
    assert _incompatibilites_semantiques(
        "jus de citron", "pulco citron 70cl", ["pulqueau"]
    ) == ["exclusion_client_contredite"]
    assert _incompatibilites_semantiques(
        "creme liquide", "blanc oeuf liquide 2l"
    ) == ["famille_creme_absente"]


def test_oeuf_entier_et_jaune_oeuf_restent_deux_lignes() -> None:
    mentions = extraire_mentions_produits(
        "un carton d oeuf et un litre de jaune d oeuf"
    )
    assert [item["produit_normalise"] for item in mentions] == [
        "oeuf",
        "jaune d oeuf",
    ]
