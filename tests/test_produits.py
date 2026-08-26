from __future__ import annotations

from src.produits import (
    _equivalence_synonyme_declaree_confirme_candidat,
    chercher_produits,
    extraire_mentions_produits,
)


def test_equivalence_synonyme_declaree_exige_phrase_complete_et_canonique() -> None:
    synonymes = {
        "huile gidolive": ["gilles d olive", "jus d olive"],
    }
    candidat = {
        "libelle_normalise": "huile gidolive 5l",
    }

    confirme, raison = _equivalence_synonyme_declaree_confirme_candidat(
        "20 litres de jus d olive",
        candidat,
        synonymes,
    )
    assert confirme is True
    assert raison == "equivalence_synonyme_declaree_confirmee=jus d olive"

    # Un mot generique seul ou un libelle d'une autre famille ne peut pas
    # franchir cette preuve de fiabilite.
    assert not _equivalence_synonyme_declaree_confirme_candidat(
        "20 litres d huile",
        candidat,
        synonymes,
    )[0]
    assert not _equivalence_synonyme_declaree_confirme_candidat(
        "20 litres de jus d olive",
        {"libelle_normalise": "huile de friture 10l"},
        synonymes,
    )[0]


def test_extraction_mentions_audio3_quatre_lignes() -> None:
    transcription = (
        "Bonjour, c'est le bistrot des filles. "
        "Je voudrais un filet mignon de porc, 600 grammes, "
        "deux litres cinq de fraises sorbet, "
        "une boîte de mayonnaise cinq litres et vingt litres de crème."
    )

    mentions = extraire_mentions_produits(transcription)

    assert len(mentions) >= 4
    assert any(
        "filet mignon de porc"
        in mention["produit_normalise"]
        for mention in mentions
    )
    assert any(
        "fraises sorbet"
        in mention["produit_normalise"]
        for mention in mentions
    )
    assert any(
        "mayonnaise"
        in mention["produit_normalise"]
        for mention in mentions
    )
    assert any(
        "creme" in mention["produit_normalise"]
        for mention in mentions
    )


def test_extraction_decimal_oral_et_precision() -> None:
    transcription = (
        "je voudrais une poitrine entière au piment erlita de 2,5 kg"
    )
    mentions = extraire_mentions_produits(transcription)

    assert len(mentions) == 1
    mention = mentions[0]
    assert "poitrine" in mention["produit_normalise"]

    # Le 2.5KG est conservé comme précision de la mention.
    assert mention["precisions_quantite"]
    precision = mention["precisions_quantite"][0]
    assert precision["quantite"] == 2.5
    assert precision["unite"] == "KG"


def test_scoring_produits_fiable_sur_cadencier() -> None:
    mentions = [
        {
            "texte_source": "5 litres de vanille creme glacee",
            "texte_normalise": "5 litres de vanille creme glacee",
            "produit_normalise": "vanille creme glacee",
            "texte_produit": "vanille creme glacee",
            "quantite_principale": 5.0,
            "quantite": 5.0,
            "unite_principale": "L",
            "unite_detectee": "L",
            "precisions_quantite": [],
            "ambigu": False,
            "raisons_ambiguite": [],
        }
    ]

    produits_client = [
        {
            "code_article": "A1",
            "libelle_article": "5L VANILLE ESSENTIELLE CREME GLACEE ARTISANALE",
            "libelle_normalise": "5l vanille essentielle creme glacee artisanale",
            "prix": 12.4,
        },
        {
            "code_article": "B2",
            "libelle_article": "MOUTARDE 1K",
            "libelle_normalise": "moutarde 1k",
            "prix": 3.1,
        },
    ]

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=produits_client,
        catalogue_global=produits_client,
        synonymes={},
        limite=3,
    )

    assert len(resultats) == 1
    resultat = resultats[0]
    assert resultat["selection"] is not None
    assert resultat["selection"]["code_article"] == "A1"
    assert resultat["produit_fiable"] is True


def test_glace_vanille_madagascar_reste_sur_cadencier_glace() -> None:
    transcription = (
        "Bonjour, c'est le restaurant du Golfe de Biarritz le Phare. "
        "Je voudrais rajouter deux bagues de glace vanille, "
        "s'il vous plait, Madagascar. Merci."
    )

    mentions = extraire_mentions_produits(transcription)

    assert len(mentions) == 1
    assert mentions[0]["quantite"] == 2.0
    assert mentions[0]["unite_principale"] == "PCE"
    assert mentions[0]["produit_normalise"] == "glace vanille madagascar"

    produits_client = [
        {
            "code_article": "00020290",
            "libelle_article": "2.5L VANILLE DELICE CREME GLACEE ARTISANALE",
            "libelle_normalise": "2 5l vanille delice creme glacee artisanale",
            "prix": 19.96,
            "nb_ventes_article_total": 5,
            "nb_ventes_article_recentes": 2,
            "derniere_vente_article_ordinal": 120,
        },
        {
            "code_article": "00051701",
            "libelle_article": "AROME VANILLE 1L",
            "libelle_normalise": "arome vanille 1l",
            "prix": 8.0,
            "nb_ventes_article_total": 10,
            "nb_ventes_article_recentes": 4,
            "derniere_vente_article_ordinal": 130,
        },
    ]

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=produits_client,
        catalogue_global=produits_client,
        synonymes={
            "glace vanille": [
                "glace vanille",
                "vanille delice creme glacee",
            ],
            "arome vanille": ["arome vanille"],
        },
        limite=3,
    )

    assert resultats[0]["selection"]["code_article"] == "00020290"
    assert resultats[0]["produit_fiable"] is True


def test_message_baleine_nettoie_fin_et_precisions() -> None:
    transcription = (
        "Alors oui bonjour c'est la baleine. Pour demain s'il vous "
        "plait il nous faudrait quatre cartons de steak hache 120 "
        "grammes, trois cartons de talouac, un carton de pain du "
        "tirin, un carton de frites de temperature, un carton de "
        "croissant s'il vous plait, au beurre, deux bidons d'huile "
        "de friture, deux packs de citron lait entier et ce sera "
        "tout. pour demain, la palaine, la vache, pour la fin de "
        "l'annee. Merci."
    )

    mentions = extraire_mentions_produits(transcription)

    assert [m["produit_normalise"] for m in mentions] == [
        "steak hache",
        "talouac",
        "pain du tirin",
        "frites de temperature",
        "croissant",
        "huile de friture",
        "lait entier",
        "la palaine",
        "la vache",
    ]
    assert mentions[6]["quantite"] == 2.0
    assert mentions[6]["unite_principale"] == "PCE"


def test_precision_grammage_departage_steak_hache() -> None:
    mentions = extraire_mentions_produits(
        "quatre cartons de steak hache 120 grammes"
    )
    produits_client = [
        {
            "code_article": "150",
            "libelle_article": "STEAK HACHE BOUCHER ROND 150GX20P SURG",
            "libelle_normalise": "steak hache boucher rond 150gx20p surg",
            "prix": 13.0,
            "nb_ventes_article_total": 20,
            "nb_ventes_article_recentes": 10,
        },
        {
            "code_article": "120",
            "libelle_article": "STEAK HACHE BOUCHER ROND 120G X50P SURG",
            "libelle_normalise": "steak hache boucher rond 120g x50p surg",
            "prix": 12.0,
            "nb_ventes_article_total": 1,
            "nb_ventes_article_recentes": 1,
        },
    ]

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=produits_client,
        catalogue_global=produits_client,
        synonymes={},
        limite=3,
    )

    assert resultats[0]["selection"]["code_article"] == "120"


def test_synonyme_cadencier_departage_par_ventes_client() -> None:
    mentions = [
        {
            "texte_source": "2 kilos de grana padano",
            "texte_normalise": "2 kilos de grana padano",
            "produit_normalise": "grana padano",
            "texte_produit": "grana padano",
            "quantite_principale": 2.0,
            "quantite": 2.0,
            "unite_principale": "KG",
            "unite_detectee": "KG",
            "precisions_quantite": [],
            "ambigu": False,
            "raisons_ambiguite": [],
        }
    ]

    produits_client = [
        {
            "code_article": "G1",
            "libelle_article": "GRANA PADANO AOP RAPE 1K",
            "libelle_normalise": "grana padano aop rape 1k",
            "prix": 12.0,
            "nb_ventes_article_total": 4,
            "nb_ventes_article_recentes": 2,
            "derniere_vente_article_ordinal": 100,
        },
        {
            "code_article": "P1",
            "libelle_article": "PARMIGIANO REGGIANO DOP 1K",
            "libelle_normalise": "parmigiano reggiano dop 1k",
            "prix": 14.0,
            "nb_ventes_article_total": 12,
            "nb_ventes_article_recentes": 6,
            "derniere_vente_article_ordinal": 120,
        },
    ]

    synonymes = {
        "grana padano": [
            "grana padano",
            "grana",
            "parmegiano",
            "parmigiano reggiano",
        ]
    }

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=produits_client,
        catalogue_global=produits_client,
        synonymes=synonymes,
        limite=5,
    )

    assert resultats[0]["selection"] is not None
    assert resultats[0]["selection"]["code_article"] == "G1"
    assert (
        resultats[0]["selection"]["regle_selection"]
        == "cadencier_plus_vendu"
    )


def test_score_cadencier_parfait_n_empeche_pas_recherche_catalogue_global() -> None:
    """Regression Exp26 (17 aout 2026) : un score cadencier de 100 sur un
    article ne doit pas empecher la recherche du catalogue global pour la
    meme mention. Cas reel diagnostique : "1 seau de moutarde" scorait 100
    sur MOUTARDE ANCIENNE 1K (cadencier) alors que la commande demandait
    MOUTARDE 5K (catalogue global, jamais meme candidate car la recherche
    globale etait sautee au-dessus du seuil)."""
    mentions = [
        {
            "texte_source": "1 seau de moutarde",
            "texte_normalise": "1 seau de moutarde",
            "produit_normalise": "moutarde",
            "texte_produit": "moutarde",
            "quantite_principale": 1.0,
            "quantite": 1.0,
            "unite_principale": "SEAU",
            "unite_detectee": "SEAU",
            "precisions_quantite": [],
            "ambigu": False,
            "raisons_ambiguite": [],
        }
    ]

    produits_client = [
        {
            "code_article": "M1",
            "libelle_article": "MOUTARDE ANCIENNE 1K",
            "libelle_normalise": "moutarde ancienne 1k",
            "prix": 5.0,
            "nb_ventes_article_total": 20,
            "nb_ventes_article_recentes": 8,
            "derniere_vente_article_ordinal": 150,
        }
    ]
    catalogue_global = produits_client + [
        {
            "code_article": "M2",
            "libelle_article": "MOUTARDE 5K",
            "libelle_normalise": "moutarde 5k",
            "prix": 15.0,
            "nb_ventes_article_total": 0,
            "nb_ventes_article_recentes": 0,
            "derniere_vente_article_ordinal": -1,
        }
    ]

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=produits_client,
        catalogue_global=catalogue_global,
        synonymes={},
        limite=10,
    )

    codes_candidats = {
        candidat["code_article"] for candidat in resultats[0]["candidats"]
    }
    assert "M1" in codes_candidats
    assert "M2" in codes_candidats, (
        "MOUTARDE 5K (catalogue global) doit rester candidate meme quand "
        "MOUTARDE ANCIENNE 1K (cadencier) atteint un score de 100"
    )


def test_plusieurs_correspondances_hors_cadencier_prend_meilleur_score() -> None:
    mentions = [
        {
            "texte_source": "3 cream cheese",
            "texte_normalise": "3 cream cheese",
            "produit_normalise": "cream cheese",
            "texte_produit": "cream cheese",
            "quantite_principale": 3.0,
            "quantite": 3.0,
            "unite_principale": "PCE",
            "unite_detectee": "PCE",
            "precisions_quantite": [],
            "ambigu": False,
            "raisons_ambiguite": [],
        }
    ]

    catalogue_global = [
        {
            "code_article": "C1",
            "libelle_article": "FROMAGE FOUETTE PHILADELPHIA 2K",
            "libelle_normalise": "fromage fouette philadelphia 2k",
            "prix": 9.0,
        },
        {
            "code_article": "C2",
            "libelle_article": "FROMAGE FOUETTE ARLA PRO 1.5K",
            "libelle_normalise": "fromage fouette arla pro 1 5k",
            "prix": 7.5,
        },
    ]

    synonymes = {
        "cream cheese": [
            "cream cheese",
            "fromage fouette",
            "arla",
        ]
    }

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=[],
        catalogue_global=catalogue_global,
        synonymes=synonymes,
        limite=5,
    )

    assert resultats[0]["selection"] is not None
    assert resultats[0]["selection"]["code_article"] == "C2"
    assert (
        resultats[0]["selection"]["regle_selection"]
        == "catalogue_score_frequence"
    )


def test_produit_prix_zero_ignore_et_problematique() -> None:
    mentions = [
        {
            "texte_source": "1 cream cheese",
            "texte_normalise": "1 cream cheese",
            "produit_normalise": "cream cheese",
            "texte_produit": "cream cheese",
            "quantite_principale": 1.0,
            "quantite": 1.0,
            "unite_principale": "PCE",
            "unite_detectee": "PCE",
            "precisions_quantite": [],
            "ambigu": False,
            "raisons_ambiguite": [],
        }
    ]

    catalogue_global = [
        {
            "code_article": "Z1",
            "libelle_article": "FROMAGE FOUETTE PHILADELPHIA 2K",
            "libelle_normalise": "fromage fouette philadelphia 2k",
            "prix": 0.0,
        }
    ]

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=[],
        catalogue_global=catalogue_global,
        synonymes={
            "cream cheese": [
                "cream cheese",
                "fromage fouette",
            ]
        },
        limite=5,
    )

    assert resultats[0]["selection"] is None
    assert resultats[0]["ambigu"] is True
    assert (
        "candidat_catalogue_prix_zero"
        in resultats[0]["raisons_ambiguite"]
    )


def test_quantite_absente_n_est_pas_inventee_depuis_habitude_client() -> None:
    mentions = [
        {
            "texte_source": "mozzarella rapee",
            "texte_normalise": "mozzarella rapee",
            "produit_normalise": "mozzarella rapee",
            "texte_produit": "mozzarella rapee",
            "quantite_principale": None,
            "quantite": None,
            "unite_principale": None,
            "unite_detectee": None,
            "precisions_quantite": [],
            "ambigu": False,
            "raisons_ambiguite": [],
            "conditionnement_multiple": None,
        }
    ]

    produits_client = [
        {
            "code_article": "M1",
            "libelle_article": "MOZZARELLA RAPE 45% CANTADORA 2.5K",
            "libelle_normalise": "mozzarella rape 45 cantadora 2.5k",
            "prix": 10.0,
            "quantite_habituelle_commande": 2.0,
            "ratio_net_par_unite": 2.5,
            "nb_ventes_article_total": 10,
            "nb_ventes_article_recentes": 4,
            "derniere_vente_article_ordinal": 100,
        }
    ]

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=produits_client,
        catalogue_global=produits_client,
        synonymes={},
        limite=3,
    )

    assert resultats[0]["selection"] is not None
    assert resultats[0]["quantite_resolue"] is None
    assert resultats[0]["produit_fiable"] is False


def test_phrase_presentation_n_est_pas_un_produit() -> None:
    mentions = extraire_mentions_produits(
        "Bonjour, je suis Elienthal Cuisine a l'appareil."
    )

    assert mentions == []


def test_sac_et_sachet_sont_traites_comme_unites() -> None:
    mentions = extraire_mentions_produits(
        "un sac de ricotta et 5 sachets de beignets de crevettes"
    )

    assert len(mentions) == 2
    assert mentions[0]["texte_produit"] == "ricotta"
    assert mentions[0]["quantite_principale"] == 1.0
    assert mentions[1]["texte_produit"] == "beignets de crevettes"


def test_oeufs_90_donne_un_carton() -> None:
    mentions = extraire_mentions_produits(
        "90 oeuf"
    )

    produits_client = [
        {
            "code_article": "O1",
            "libelle_article": "OEUF ARRADOY MOYEN 53/63 X90P",
            "libelle_normalise": "oeuf arradoy moyen 53 63 x90p",
            "prix": 28.0,
            "quantite_habituelle_commande": 1.0,
            "ratio_net_par_unite": 5.4,
            "nb_ventes_article_total": 30,
            "nb_ventes_article_recentes": 8,
            "derniere_vente_article_ordinal": 120,
        }
    ]

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=produits_client,
        catalogue_global=produits_client,
        synonymes={},
        limite=3,
    )

    assert resultats[0]["selection"] is not None
    assert resultats[0]["quantite_resolue"] == 1.0
    assert resultats[0]["unite_resolue"] == "CAR"


def test_conditionnement_plus_proche_est_retenu() -> None:
    mentions = [
        {
            "texte_source": "1 kilo de mozzarella rapee",
            "texte_normalise": "1 kilo de mozzarella rapee",
            "produit_normalise": "mozzarella rapee",
            "texte_produit": "mozzarella rapee",
            "quantite_principale": 1.0,
            "quantite": 1.0,
            "unite_principale": "KG",
            "unite_detectee": "KG",
            "precisions_quantite": [],
            "ambigu": False,
            "raisons_ambiguite": [],
            "conditionnement_multiple": None,
        }
    ]

    produits_client = [
        {
            "code_article": "M25",
            "libelle_article": "MOZZARELLA RAPE 45% CANTADORA 2.5K",
            "libelle_normalise": "mozzarella rape 45 cantadora 2.5k",
            "prix": 12.0,
            "quantite_habituelle_commande": 1.0,
            "ratio_net_par_unite": 2.5,
            "nb_ventes_article_total": 8,
            "nb_ventes_article_recentes": 3,
            "derniere_vente_article_ordinal": 100,
        },
        {
            "code_article": "M50",
            "libelle_article": "MOZZARELLA RAPE 45% CANTADORA 5K",
            "libelle_normalise": "mozzarella rape 45 cantadora 5k",
            "prix": 11.0,
            "quantite_habituelle_commande": 1.0,
            "ratio_net_par_unite": 5.0,
            "nb_ventes_article_total": 8,
            "nb_ventes_article_recentes": 3,
            "derniere_vente_article_ordinal": 100,
        },
    ]

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=produits_client,
        catalogue_global=produits_client,
        synonymes={},
        limite=5,
    )

    assert resultats[0]["selection"] is not None
    assert resultats[0]["selection"]["code_article"] == "M25"
    assert resultats[0]["quantite_resolue"] == 1.0


def test_carton_lait_utilise_unite_commande_officielle() -> None:
    mentions = [
        {
            "texte_source": "1 carton de lait",
            "texte_normalise": "1 carton de lait",
            "produit_normalise": "lait",
            "texte_produit": "lait",
            "quantite_principale": 1.0,
            "quantite": 1.0,
            "unite_principale": "CAR",
            "unite_detectee": "CAR",
            "precisions_quantite": [],
            "ambigu": False,
            "raisons_ambiguite": [],
            "conditionnement_multiple": None,
        }
    ]

    produits_client = [
        {
            "code_article": "00401120",
            "libelle_article": "LAIT ENTIER UHT 6X1L",
            "libelle_normalise": "lait entier uht 6x1l",
            "prix": 1.2,
            "quantite_habituelle_commande": 6.0,
            "ratio_net_par_unite": 1.0,
            "nb_ventes_article_total": 20,
            "nb_ventes_article_recentes": 6,
            "derniere_vente_article_ordinal": 100,
        }
    ]

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=produits_client,
        catalogue_global=produits_client,
        synonymes={},
        limite=3,
    )

    assert resultats[0]["selection"] is not None
    assert resultats[0]["quantite_resolue"] == 1.0
    assert resultats[0]["unite_resolue"] == "PACK"


def test_beurre_sans_precision_prefere_beurre_doux() -> None:
    mentions = [
        {
            "texte_source": "2 beurre",
            "texte_normalise": "2 beurre",
            "produit_normalise": "beurre",
            "texte_produit": "beurre",
            "quantite_principale": 2.0,
            "quantite": 2.0,
            "unite_principale": None,
            "unite_detectee": None,
            "precisions_quantite": [],
            "ambigu": False,
            "raisons_ambiguite": [],
            "conditionnement_multiple": None,
        }
    ]

    produits_client = [
        {
            "code_article": "BD",
            "libelle_article": "BEURRE DOUX 250G",
            "libelle_normalise": "beurre doux 250g",
            "prix": 2.0,
            "quantite_habituelle_commande": 10.0,
            "ratio_net_par_unite": 0.25,
            "nb_ventes_article_total": 30,
            "nb_ventes_article_recentes": 10,
            "derniere_vente_article_ordinal": 100,
        },
        {
            "code_article": "BS",
            "libelle_article": "BEURRE DEMI SEL 250G",
            "libelle_normalise": "beurre demi sel 250g",
            "prix": 2.0,
            "quantite_habituelle_commande": 10.0,
            "ratio_net_par_unite": 0.25,
            "nb_ventes_article_total": 30,
            "nb_ventes_article_recentes": 10,
            "derniere_vente_article_ordinal": 100,
        },
    ]

    resultats = chercher_produits(
        mentions=mentions,
        produits_client=produits_client,
        catalogue_global=produits_client,
        synonymes={},
        limite=5,
    )

    assert resultats[0]["selection"] is not None
    assert resultats[0]["selection"]["code_article"] == "BD"


def test_phrase_rajout_ignoree() -> None:
    mentions = extraire_mentions_produits("je vais faire un rajout")
    assert not any("rajout" in m["produit_normalise"] for m in mentions)
    
    mentions2 = extraire_mentions_produits("je vais rajouter 90 oeufs")
    assert len(mentions2) == 1
    assert "oeuf" in mentions2[0]["produit_normalise"]

def test_phrase_commande_ignoree() -> None:
    mentions = extraire_mentions_produits("c est pour ma commande")
    assert mentions == []
