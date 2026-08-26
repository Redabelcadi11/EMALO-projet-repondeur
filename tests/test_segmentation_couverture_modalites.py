from __future__ import annotations

from src.produits import (
    chercher_produits,
    decouper_clauses_produits,
    extraire_mentions_produits,
)
from src.ui_product_details import projection_produit_reconnu


def _produits(texte: str) -> list[dict]:
    return extraire_mentions_produits(texte)


def test_enum_quantite_compacte_ne_fusionne_pas_deux_produits() -> None:
    mentions = _produits(
        "6 pots de guacam de mamia et 6l de creme brulee"
    )

    assert [item["produit_normalise"] for item in mentions] == [
        "guacam de mamia",
        "creme brulee",
    ]
    assert [item["quantite_principale"] for item in mentions] == [6.0, 6.0]
    assert mentions[1]["unite_principale"] == "L"


def test_enum_quantite_compacte_reste_generique() -> None:
    mentions = _produits("2 cartons de chipiron et 3kg de beurre")

    assert [item["produit_normalise"] for item in mentions] == [
        "chipiron",
        "beurre",
    ]


def test_libelle_compose_non_quantifie_n_est_pas_coupe() -> None:
    clauses = decouper_clauses_produits("1 fromage ail et fines herbes")

    assert clauses == ["1 fromage ail et fines herbes"]


def test_formulations_habituelles_modifient_le_produit_precedent() -> None:
    formulations = (
        "1 carton de ravioles epinards, toujours les memes",
        "1 carton de ravioles epinards, celles qu on prend d habitude",
        "1 carton de croquettes, ancienne reference",
        "1 sac de riz, celui qu on prend habituellement",
    )

    for texte in formulations:
        mentions = _produits(texte)
        assert len(mentions) == 1, texte
        assert mentions[0]["preference_historique_compatible"] is True
        assert mentions[0]["modalite_demande"] == "HABITUELLE"


def test_formulation_habituelle_inline_ne_pollue_pas_le_nom_produit() -> None:
    riz = _produits("1 sac de riz qu on prend d habitude")[0]
    croquettes = _produits("5 cartons de croquettes anciennes references")[0]

    assert riz["produit_normalise"] == "riz"
    assert riz["preference_historique_compatible"] is True
    assert croquettes["produit_normalise"] == "croquettes"
    assert croquettes["preference_historique_compatible"] is True


def test_alternative_reste_une_seule_demande() -> None:
    mentions = _produits(
        "si vous avez une pate d arachide ou un beurre de cacahuete"
    )

    assert len(mentions) == 1
    assert mentions[0]["modalite_demande"] == "ALTERNATIVE"
    assert mentions[0]["alternatives_produit"] == [
        "pate d arachide",
        "beurre de cacahuete",
    ]


def test_matching_alternative_ne_cree_qu_un_resultat() -> None:
    catalogue = [
        {
            "code_article": "ARACHIDE",
            "libelle_article": "PATE ARACHIDE 1KG",
            "libelle_normalise": "pate arachide 1kg",
            "prix": 10.0,
            "unite_vente": "PI",
            "nb_ventes_article_total": 1,
            "nb_ventes_article_recentes": 1,
        },
        {
            "code_article": "CACAHUETE",
            "libelle_article": "BEURRE CACAHUETE 1KG",
            "libelle_normalise": "beurre cacahuete 1kg",
            "prix": 10.0,
            "unite_vente": "PI",
            "nb_ventes_article_total": 10,
            "nb_ventes_article_recentes": 10,
        },
    ]
    resultats = chercher_produits(
        _produits("si vous avez une pate d arachide ou un beurre de cacahuete"),
        catalogue,
        catalogue,
        {},
    )

    assert len(resultats) == 1
    assert resultats[0]["statut_couverture"] == "AMBIGU"
    assert {item["code_article"] for item in resultats[0]["candidats"]} == {
        "ARACHIDE",
        "CACAHUETE",
    }


def test_demande_conditionnelle_est_annotee_sans_etre_dupliquee() -> None:
    mentions = _produits("si vous avez 2 cartons de chipiron")

    assert len(mentions) == 1
    assert mentions[0]["produit_normalise"] == "chipiron"
    assert mentions[0]["modalite_demande"] == "CONDITIONNELLE"


def test_condition_ne_contamine_pas_le_produit_precedent() -> None:
    mentions = _produits(
        "1 sauce ketchup et si vous avez 2 cartons de chipiron"
    )

    assert [item["modalite_demande"] for item in mentions] == [
        "CERTAINE",
        "CONDITIONNELLE",
    ]


def test_ui_detail_affiche_un_vrai_produit_non_identifie() -> None:
    produit = {
        "segment_id": "segment-2",
        "segment_index": 2,
        "texte_source": "1 barquette de chicharron",
        "produit_normalise": "chicharron",
        "produit_reconnu": False,
        "produit_fiable": False,
        "statut_couverture": "NON_IDENTIFIE",
        "quantite_principale": 1.0,
        "unite_principale": "BARQ",
        "raisons_ambiguite": ["score_produit_trop_faible"],
        "selection": None,
    }

    projection = projection_produit_reconnu(produit, None, 2)

    assert projection is not None
    assert projection["recognized"] is False
    assert projection["coverage_status"] == "NON_IDENTIFIE"
    assert projection["source_text"] == "1 barquette de chicharron"


def test_ui_detail_masque_toujours_une_phrase_hors_commande() -> None:
    produit = {
        "segment_id": "segment-1",
        "segment_index": 1,
        "texte_source": "merci au revoir",
        "produit_normalise": "merci au revoir",
        "produit_reconnu": False,
        "produit_fiable": False,
        "statut_couverture": "HORS_COMMANDE",
        "raisons_ambiguite": ["product_gate_noyau_non_prouve"],
        "selection": None,
    }

    assert projection_produit_reconnu(produit, None, 1) is None
