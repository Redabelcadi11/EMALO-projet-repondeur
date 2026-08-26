from __future__ import annotations

from src.produits import (
    _generer_variantes_recherche,
    _incompatibilites_semantiques,
    _resoudre_quantite_commande_candidat,
    extraire_mentions_produits,
    chercher_produits,
)


def _article(
    code: str,
    libelle: str,
    unite: str = "PI",
    **champs: object,
) -> dict[str, object]:
    return {
        "code_article": code,
        "libelle_article": libelle,
        "libelle_normalise": libelle.casefold().replace(".", " "),
        "unite_vente": unite,
        "prix": 1.0,
        **champs,
    }


def _resoudre(texte: str, articles: list[dict[str, object]], synonymes=None):
    mentions = extraire_mentions_produits(texte)
    return chercher_produits(
        mentions=mentions,
        produits_client=articles,
        catalogue_global=articles,
        synonymes=synonymes or {},
        limite=5,
    )


def test_ainsi_que_disponibilite_ouvre_une_nouvelle_ligne_produit() -> None:
    mentions = extraire_mentions_produits(
        "30 x 1 kg de farine t55 ainsi que si vous avez de l huile "
        "d arachide en bidon de 5 litres"
    )

    produits = [mention["produit_normalise"] for mention in mentions]
    assert len(mentions) == 2
    assert produits[0] == "farine t55"
    assert "huile d arachide" in produits[1]


def test_coordination_de_deux_groupes_nominaux_ne_fusionne_pas_les_articles() -> None:
    mentions = extraire_mentions_produits(
        "une fourme d ambert et des pistoles de chocolat 64 pourcent"
    )

    assert [mention["produit_normalise"] for mention in mentions] == [
        "fourme d ambert",
        "pistoles de chocolat 64 pour cent",
    ]


def test_discours_ne_devient_pas_un_produit_par_simple_ressemblance_fuzzy() -> None:
    resultats = _resoudre(
        "1 belle journee pour demain",
        [_article("HUILE-TEST", "HUILE DE TOURNESOL 5L")],
    )

    assert resultats == []


def test_fragment_asr_court_ne_devient_pas_un_produit_par_prefixe() -> None:
    resultats = _resoudre(
        "1 saut de",
        [_article("PORC-TEST", "SAUTE DE PORC 2.5K", "POC")],
    )

    assert resultats == []


def test_article_asr_deforme_mais_structure_et_cadencier_reste_reconnu() -> None:
    resultats = _resoudre(
        "1 carton de sacoubelle en 150 litres",
        [_article("SACS-TEST", "SACS POUBELLE 150L X100P", "LOT")],
    )

    assert resultats[0]["produit_reconnu"] is True
    assert resultats[0]["selection"]["code_article"] == "SACS-TEST"


def test_nom_de_produit_court_mais_exact_reste_commandable() -> None:
    resultats = _resoudre(
        "1 burrata",
        [_article("BURRATA-TEST", "BURRATA 125G X8P", "COL")],
    )

    assert resultats[0]["produit_reconnu"] is True
    assert resultats[0]["selection"]["code_article"] == "BURRATA-TEST"


def test_flexion_plurielle_reste_une_preuve_positive_de_produit() -> None:
    resultats = _resoudre(
        "12 camemberts en",
        [_article("CAMEMBERT-TEST", "CAMEMBERT 250G", "PI")],
    )

    assert resultats[0]["produit_reconnu"] is True
    assert resultats[0]["selection"]["code_article"] == "CAMEMBERT-TEST"


def test_synonyme_canonique_est_developpe_dans_les_deux_sens() -> None:
    variantes = _generer_variantes_recherche(
        "cream cheese",
        {"cream cheese": ["fromage fouette", "arla"]},
    )

    assert "fromage fouette" in variantes
    assert "arla" in variantes


def test_variantes_synonymes_sont_stables_et_ne_perdent_pas_un_alias_long() -> None:
    synonymes = {
        "grana padano": [
            "grana padano",
            "grana",
            "parmegiano",
            "parmigiano reggiano",
        ]
    }

    variantes = _generer_variantes_recherche("grana padano", synonymes)

    assert variantes == sorted(
        variantes,
        key=lambda variante: (-len(variante), variante),
    )
    assert "parmigiano reggiano" in variantes


def test_synonyme_fort_du_cadencier_evite_un_fallback_referentiel_hors_famille() -> None:
    mention = extraire_mentions_produits("2 pots de cream cheese")
    cadencier = [
        _article(
            "FOUETTE-TEST",
            "FROMAGE FOUETTE ARLA PRO 1.5KG",
            "BOITE",
        )
    ]
    catalogue = [
        *cadencier,
        _article(
            "DESSERT-TEST",
            "CREME CHEESECAKE SURGELEE 900G",
            "PI",
        ),
    ]

    resultats = chercher_produits(
        mentions=mention,
        produits_client=cadencier,
        catalogue_global=catalogue,
        synonymes={
            "cream cheese": ["fromage fouette", "arla", "philadelphia"]
        },
        limite=5,
    )

    assert resultats[0]["selection"]["code_article"] == "FOUETTE-TEST"
    assert resultats[0]["produit_reconnu"] is True


def test_etat_cru_explicite_exclut_une_preparation_panee() -> None:
    incompatibilites = _incompatibilites_semantiques(
        "crevettes crues surgelees",
        "crevette croute pomme de terre panee",
    )

    assert "etat_transformation_contradictoire" in incompatibilites


def test_synonyme_de_famille_et_etat_explicite_retrouvent_le_cadencier() -> None:
    articles = [
        _article(
            "PANE-TEST",
            "CREVETTE CROUTE POMME DE TERRE 300G X10P",
            "POC",
        ),
        _article(
            "CRU-TEST",
            "QUEUE DE GAMBAS CRUE DECONGELEE 30/40 X1K",
            "POC",
        ),
    ]

    resultats = _resoudre(
        "2 kilos de crevettes crues surgelees",
        articles,
        {"gambas": ["crevettes", "crevette"]},
    )

    assert resultats[0]["selection"]["code_article"] == "CRU-TEST"
    assert resultats[0]["produit_reconnu"] is True


def test_variante_farinee_explicite_ne_devient_pas_variante_panee_cadencier() -> None:
    cadencier = [
        _article(
            "PANE-TEST",
            "RABAS LAMELLE DE CALAMAR PANEE 1K",
            "POC",
        )
    ]
    catalogue = [
        *cadencier,
        _article("FARINE-TEST", "RABAS GOURMET FARINEES 1K", "POC"),
    ]

    resultats = chercher_produits(
        mentions=extraire_mentions_produits("2 cartons de rabas en farinata"),
        produits_client=cadencier,
        catalogue_global=catalogue,
        synonymes={
            "rabas": ["rabas", "rabas en farinata", "rabas farinees"]
        },
        limite=5,
    )

    assert resultats[0]["selection"]["code_article"] == "FARINE-TEST"


def test_ratio_historique_sans_dimension_n_est_pas_une_contenance_litre() -> None:
    resolution = _resoudre_quantite_commande_candidat(
        {
            "quantite_principale": 10.0,
            "unite_principale": "L",
            "conditionnement_multiple": None,
            "texte_source": "10 litres d olive noire extra",
        },
        _article(
            "OLIVE-TEST",
            "OLIVE NOIRE DENOYAUTEE 5/1",
            "BOITE",
            ratio_net_par_unite=1.0,
        ),
    )

    assert resolution["quantite_resolue"] is None
    assert "dimension_physique_article_inconnue" in resolution["raisons_resolution"]


def test_contenance_explicitement_ecrite_permet_la_conversion_litre() -> None:
    resolution = _resoudre_quantite_commande_candidat(
        {
            "quantite_principale": 10.0,
            "unite_principale": "L",
            "conditionnement_multiple": None,
            "texte_source": "10 litres d huile d olive extra vierge",
        },
        _article(
            "HUILE-TEST",
            "HUILE OLIVE EXTRA VIERGE 5L",
            "BID",
            ratio_net_par_unite=1.0,
        ),
    )

    assert (resolution["quantite_resolue"], resolution["unite_resolue"]) == (
        2.0,
        "BID",
    )


def test_quantite_et_cadencier_ne_prouvent_jamais_un_produit_absent() -> None:
    articles = [
        _article("PAIN-TEST", "PAIN BUNS BRIOCHE NATURE X36P", "COL"),
        _article("FROMAGE-TEST", "CAMEMBERT PETIT 250G", "PI"),
    ]

    resultat = _resoudre(
        "1 petit point direct comment pour demain",
        articles,
    )[0]

    assert resultat["produit_reconnu"] is False
    # Le meilleur candidat reste visible dans le diagnostic, mais ne devient
    # jamais une ligne commandable sans noyau produit prouvé.
    assert "product_gate_noyau_non_prouve" in resultat["raisons_ambiguite"]


def test_noyau_explicitement_prononce_passe_avant_historique_client() -> None:
    yaourt = _article(
        "YAOURT-TEST",
        "YAOURT DE VACHE NATURE 3.5K",
        "POT",
        nb_ventes_article_total=1,
        nb_ventes_article_recentes=1,
    )
    pain = _article(
        "PAIN-TEST",
        "PAIN BUNS BRIOCHE NATURE X36P",
        "COL",
        nb_ventes_article_total=10_000,
        nb_ventes_article_recentes=10_000,
    )

    resultat = _resoudre("3 kilos de yaourt nature", [yaourt, pain])[0]

    assert resultat["produit_reconnu"] is True
    assert resultat["selection"]["code_article"] == "YAOURT-TEST"


def test_phonetique_catalogue_repare_un_noyau_asr_sans_prior_historique() -> None:
    morilles = _article(
        "MORILLES-TEST",
        "MORILLES ENTIERES SURGELEES 1KG",
        "COL",
        nb_ventes_article_total=1,
    )
    anchois = _article(
        "ANCHOIS-TEST",
        "FILET ANCHOIS MARINES PROVENCAL 800G",
        "COL",
        nb_ventes_article_total=10_000,
    )

    resultat = _resoudre(
        "2 cartons de maurice surgelee",
        [morilles, anchois],
    )[0]

    assert resultat["produit_reconnu"] is True
    assert resultat["selection"]["code_article"] == "MORILLES-TEST"


def test_phonetique_multi_mots_repare_un_mot_soude_ou_decoupe() -> None:
    surimi = _article("SURIMI-TEST", "MIETTES DE SURIMI 500G", "POC")
    fromage = _article(
        "FROMAGE-TEST",
        "EMMENTAL RAPE 1K",
        "POC",
        nb_ventes_article_total=10_000,
    )

    resultat = _resoudre(
        "1 kilo de souris mi rape",
        [surimi, fromage],
    )[0]

    assert resultat["produit_reconnu"] is True
    assert resultat["selection"]["code_article"] == "SURIMI-TEST"


def test_attribut_explicite_ecarte_une_transformation_contradictoire() -> None:
    rape = _article("RAPE-TEST", "EMMENTAL RAPE 1K", "POC")
    fouette = _article(
        "FOUETTE-TEST",
        "FROMAGE FOUETTE NATURE 500G",
        "POT",
        nb_ventes_article_total=10_000,
    )

    resultat = _resoudre(
        "2 poches de fromage rape",
        [rape, fouette],
    )[0]

    assert resultat["produit_reconnu"] is True
    assert resultat["selection"]["code_article"] == "RAPE-TEST"


def test_morceau_animal_explicite_bat_historique_d_un_autre_morceau() -> None:
    """Une cotelette ne devient jamais une epaule via le cadencier."""
    epaule = _article(
        "EPAULE-TEST",
        "EPAULE AGNEAU ENTIERE +/-1.3K",
        "PI",
        nb_ventes_article_total=10_000,
        nb_ventes_article_recentes=10_000,
    )
    jus = _article(
        "JUS-TEST",
        "JUS D AGNEAU 900G",
        "BOITE",
        nb_ventes_article_total=20_000,
        nb_ventes_article_recentes=20_000,
    )
    cote = _article(
        "COTE-TEST",
        "COTE D AGNEAU SURGELE 40/60G +/-1.3K",
        "POC",
    )

    resultat = chercher_produits(
        extraire_mentions_produits("3 kilos de cotelettes d agneau"),
        [epaule, jus],
        [epaule, jus, cote],
        {},
        limite=5,
    )[0]

    assert resultat["selection"]["code_article"] == "COTE-TEST"
    incompatibilites = _incompatibilites_semantiques(
        "3 kilos de cotelettes d agneau",
        "EPAULE AGNEAU ENTIERE +/-1.3K",
    )
    assert "morceau_animal_contradictoire" in incompatibilites
    assert "morceau_animal_explicite_absent" in _incompatibilites_semantiques(
        "3 kilos de cotelettes d agneau",
        "JUS D AGNEAU 900G",
    )


def test_alias_multi_mots_accepte_ordre_inverse_et_suffixe_asr_borne() -> None:
    synonymes = {
        "cream cheese": ["fromage fouette", "creme cheese", "arla"]
    }
    variantes_inversees = _generer_variantes_recherche(
        "cheese creme",
        synonymes,
    )
    variantes_suffixees = _generer_variantes_recherche(
        "cream cheeseur la",
        synonymes,
    )
    assert "fromage fouette" in variantes_inversees
    assert "fromage fouette la" in variantes_suffixees


def test_disponibilite_apres_second_produit_ne_fusionne_pas_avec_le_premier() -> None:
    mentions = extraire_mentions_produits(
        "1 litre d arome vanille et des gambas si vous avez "
        "des gambas decortiquees"
    )

    assert [mention["produit_normalise"] for mention in mentions] == [
        "arome vanille",
        "gambas si vous avez des gambas decortiquees",
    ]


def test_forme_physique_absente_du_libelle_n_est_pas_une_contradiction() -> None:
    incompatibilites = _incompatibilites_semantiques(
        "pistoles de chocolat 64 pourcent",
        "chocolat guayaquil 64% 5k",
    )

    assert "forme_chocolat_contradictoire" not in incompatibilites


def test_article_marque_inactif_ne_peut_pas_battre_un_article_actif() -> None:
    actif = _article("ACTIF-TEST", "SAUCE SOJA SALEE 1L", "PI")
    inactif = _article(
        "INACTIF-TEST",
        "SAUCE SOJA SALEE PREMIUM 1L ***",
        "PI",
        nb_ventes_article_total=10_000,
        nb_ventes_article_recentes=10_000,
    )

    resultat = _resoudre("2 sauces soja salees", [actif, inactif])[0]

    assert resultat["produit_reconnu"] is True
    assert resultat["selection"]["code_article"] == "ACTIF-TEST"


def test_disponibilite_avec_verbe_metier_separe_deux_produits() -> None:
    mentions = extraire_mentions_produits(
        "2 litres de lait de coco et si vous faites du tahin je veux bien 2 kilos"
    )

    assert len(mentions) >= 2
    assert mentions[0]["produit_normalise"] == "lait de coco"
    assert mentions[1]["produit_normalise"].startswith("tahin")


def test_si_asr_sans_condition_restaure_six_et_un_second_produit() -> None:
    mentions = extraire_mentions_produits(
        "une caisse d oeufs si burrata et deux kilos de mascarpone"
    )

    assert [mention["produit_normalise"] for mention in mentions[:3]] == [
        "oeufs",
        "burrata",
        "mascarpone",
    ]
    assert mentions[1]["quantite_principale"] == 6.0


def test_croquette_ne_declenche_pas_la_famille_distincte_croque_monsieur() -> None:
    resultat = _resoudre(
        "1 carton de croquettes de morue",
        [_article("CROQUETTE-TEST", "CROQUETTE PREMIUM MORUE 30G X4K", "COL")],
    )[0]

    assert resultat["produit_reconnu"] is True
    assert resultat["selection"]["code_article"] == "CROQUETTE-TEST"


def test_phonetique_composee_bat_un_homonyme_partiel_du_cadencier() -> None:
    articles = [
        _article("SURIMI-TEST", "MIETTES DE SURIMI 500G", "POC"),
        _article(
            "SOURIS-TEST",
            "SOURIS AGNEAU ARRIERE SURGELEE 450G",
            "POC",
            nb_ventes_article_total=10_000,
        ),
    ]

    resultat = _resoudre("1 kilo de souris mi rape", articles)[0]

    assert resultat["produit_reconnu"] is True
    assert resultat["selection"]["code_article"] == "SURIMI-TEST"


def test_forme_fragmentee_explicite_ecarte_un_fromage_non_rape() -> None:
    articles = [
        _article("RAPE-TEST", "EMMENTAL RAPE 1K", "POC"),
        _article(
            "CROQUETTE-TEST",
            "CROQUETTE FROMAGE BLEU ARTISANALE 3K",
            "COL",
            nb_ventes_article_total=10_000,
        ),
    ]

    resultat = _resoudre("2 poches de fromage rape", articles)[0]

    assert resultat["produit_reconnu"] is True
    assert resultat["selection"]["code_article"] == "RAPE-TEST"


def test_yaourt_sans_contexte_glace_ne_devient_pas_creme_glacee() -> None:
    articles = [
        _article("YAOURT-TEST", "YAOURT DE VACHE NATURE 3.5K", "SEAU"),
        _article(
            "GLACE-TEST",
            "2.5L YAOURT NATURE CREME GLACEE ARTISANALE",
            "BOITE",
            nb_ventes_article_total=10_000,
        ),
    ]

    resultat = _resoudre(
        "3 kilos de yaourt nature",
        articles,
        {"creme glacee yaourt": ["yaourt nature"]},
    )[0]

    assert resultat["selection"]["code_article"] == "YAOURT-TEST"


def test_petit_emballage_conserve_la_quantite_un() -> None:
    mentions = extraire_mentions_produits(
        "il me faudrait un petit sachet de brisure de speculoos"
    )

    assert len(mentions) == 1
    assert mentions[0]["quantite_principale"] == 1.0
    assert "speculoos" in mentions[0]["produit_normalise"]


def test_quantite_formulee_apres_le_produit_est_rattachee() -> None:
    mentions = extraire_mentions_produits(
        "2 litres de lait de coco et si vous faites du tahin "
        "je veux bien 2 kilos"
    )

    tahin = next(
        mention for mention in mentions if "tahin" in mention["produit_normalise"]
    )
    assert tahin["quantite_principale"] == 2.0
    assert tahin["unite_principale"] == "KG"


def test_quantite_dans_clause_separee_est_rattachee_au_produit() -> None:
    mentions = extraire_mentions_produits(
        "2 litres de lait de coco et si vous faites du tahin, "
        "je veux bien 2 kilos"
    )

    tahin = next(
        mention for mention in mentions if "tahin" in mention["produit_normalise"]
    )
    assert tahin["quantite_principale"] == 2.0
    assert tahin["unite_principale"] == "KG"
    assert not any(
        mention["produit_normalise"].startswith("je veux")
        for mention in mentions
    )


def test_produit_compose_ne_detourne_pas_un_noyau_explicite() -> None:
    jambon = _article(
        "JAMBON-TEST", "JAMBON IBERIQUE ENTIER 5K", "PI",
        nb_ventes_article_total=2,
    )
    chips = _article(
        "CHIPS-TEST", "CHIPS SAVEUR JAMBON IBERIQUE X20P", "COL",
        nb_ventes_article_total=10_000,
    )
    mentions = extraire_mentions_produits("une piece de jambon iberique")
    resultat = chercher_produits(
        mentions, [jambon], [jambon, chips], {}, limite=5
    )[0]

    assert resultat["selection"]["code_article"] == "JAMBON-TEST"


def test_type_de_fromage_explicite_ecarte_plat_et_fromage_generique() -> None:
    brebis = _article("BREBIS-TEST", "BREBIS FERMIER 3K", "PI")
    fouette = _article("FOUETTE-TEST", "FROMAGE FOUETTE 1.5K", "SEAU")
    tartiflette = _article(
        "PLAT-TEST", "TARTIFLETTE AU FROMAGE DE BREBIS 3K", "PI",
        nb_ventes_article_total=10_000,
    )
    mentions = extraire_mentions_produits("une meule de fromage de brebis")
    resultat = chercher_produits(
        mentions, [brebis, fouette], [brebis, fouette, tartiflette], {}, limite=5
    )[0]

    assert resultat["selection"]["code_article"] == "BREBIS-TEST"


def test_copeaux_et_petales_sont_la_meme_forme_produit() -> None:
    raisons = _incompatibilites_semantiques(
        "parmesan en copeaux", "grana padano petales 500g"
    )

    assert not any("forme_decoupe" in raison for raison in raisons)


def test_sucre_en_poudre_accepte_semoule_sans_devenir_sucre_roux() -> None:
    semoule = _article("SEMOULE-TEST", "SUCRE SEMOULE 1K", "POC")
    roux = _article(
        "ROUX-TEST", "SUCRE ROUX POUDRE CASSONNADE 1K", "BOITE",
        nb_ventes_article_total=10_000,
    )
    resultat = _resoudre("7 kilos de sucre en poudre", [semoule, roux])[0]

    assert resultat["selection"]["code_article"] == "SEMOULE-TEST"


def test_noyau_exact_distinctif_catalogue_reste_visible() -> None:
    distracteur = _article("GAUFRE-TEST", "GAUFRE BRUXELLES X24P", "CAR")
    speculoos = _article(
        "SPECULOOS-TEST", "SPECULOOS CONCASSE 750G", "POC",
        nb_ventes_article_total=1,
    )
    mentions = extraire_mentions_produits(
        "un petit sachet de brisure de speculoos"
    )
    resultat = chercher_produits(
        mentions, [distracteur], [distracteur, speculoos], {}, limite=5
    )[0]

    assert resultat["produit_reconnu"] is True
    assert resultat["selection"]["code_article"] == "SPECULOOS-TEST"


def test_connecteur_par_ne_declenche_pas_un_fallback_hors_cadencier() -> None:
    standard = _article(
        "OEUF-STANDARD", "OEUF MOYEN 53/63 X90P", "COL",
        nb_ventes_article_total=3,
    )
    plein_air = _article(
        "OEUF-AIR", "OEUF MOYEN PLEIN AIR 53/63 X90P", "COL",
        nb_ventes_article_total=10_000,
    )
    mentions = extraire_mentions_produits("un carton d oeuf moyen par 90")
    resultat = chercher_produits(
        mentions, [standard], [standard, plein_air], {}, limite=5
    )[0]

    assert resultat["selection"]["code_article"] == "OEUF-STANDARD"


def test_produit_cadencier_tres_precis_sans_quantite_prend_un_par_defaut() -> None:
    articles = [
        _article(
            "GAMBAS-DECO-TEST",
            "QUEUE DE GAMBAS DECORTIQUEE 30/40 X1K",
            "POC",
        ),
        _article("GAMBAS-TEST", "GAMBAS ENTIERE CRUE 20/30 2K", "BOITE"),
    ]

    resultat = _resoudre(
        "des gambas si vous avez des gambas decortiquees",
        articles,
    )[0]

    assert resultat["produit_reconnu"] is True
    assert resultat["selection"]["code_article"] == "GAMBAS-DECO-TEST"
    assert resultat["quantite_resolue"] == 1.0
