from __future__ import annotations

from src.produits import (
    _selectionner_meilleur_candidat,
    chercher_produits,
    extraire_mentions_produits,
)


def _candidat(code: str, libelle: str, score: float, ventes: int = 0) -> dict:
    return {
        "code_article": code,
        "libelle_article": libelle,
        "libelle_normalise": libelle.lower(),
        "prix": 1.0,
        "score_texte": score,
        "score_global": score,
        "score_conditionnement": 0.0,
        "nb_ventes_article_total": ventes,
        "nb_ventes_article_recentes": ventes,
        "derniere_vente_article_ordinal": 739800,
        "dans_cadencier_client": True,
        "source_recherche": "cadencier_client",
        "semantiquement_compatible": True,
        "raisons": [],
    }


def test_forme_bloc_ne_cree_pas_une_famille_produit() -> None:
    choix, _ = _selectionner_meilleur_candidat(
        [
            _candidat("PARM", "PARMESAN EN BLOC", 80),
            _candidat("FETA", "FETA EN BLOC", 88, ventes=100),
        ],
        texte_source="parmesan bloc",
    )
    assert choix is not None and choix["code_article"] == "PARM"


def test_forme_pain_ne_cree_pas_une_famille_produit() -> None:
    choix, _ = _selectionner_meilleur_candidat(
        [
            _candidat("BURGER", "PAIN BURGER", 80),
            _candidat("MOZZA", "MOZZARELLA PAIN", 88, ventes=100),
        ],
        texte_source="pain burger",
    )
    assert choix is not None and choix["code_article"] == "BURGER"


def test_preparation_emincee_ne_cree_pas_une_famille_produit() -> None:
    choix, _ = _selectionner_meilleur_candidat(
        [
            _candidat("POIV", "POIVRON EMINCE SURGELE", 80),
            _candidat("OIGN", "OIGNON EMINCE SURGELE", 88, ventes=100),
        ],
        texte_source="poivron emince",
    )
    assert choix is not None and choix["code_article"] == "POIV"


def test_historique_reste_departageur_dans_la_meme_famille() -> None:
    choix, _ = _selectionner_meilleur_candidat(
        [
            _candidat("CHED1", "CHEDDAR ROUGE TRANCHE", 80),
            _candidat("CHED2", "CHEDDAR ROUGE BLOC", 82, ventes=100),
        ],
        texte_source="cheddar rouge",
    )
    assert choix is not None and choix["code_article"] == "CHED2"


def test_seconde_passe_applique_un_par_defaut_apres_preuve_forte() -> None:
    mention = {
        "texte_source": "du fromage affine",
        "texte_normalise": "du fromage affine",
        "produit_normalise": "fromage affine",
        "texte_produit": "fromage affine",
        "quantite_principale": None,
        "quantite": None,
        "unite_principale": None,
        "unite_detectee": None,
        "precisions_quantite": [],
        "ambigu": True,
        "raisons_ambiguite": ["quantite_absente_a_resoudre"],
        "role_semantique": "PRODUCT_ITEM",
    }
    article = _candidat("FROM", "FROMAGE AFFINE", 90)
    resultat = chercher_produits(
        [mention], [article], [article], {}, limite=5
    )[0]

    assert resultat["selection"]["code_article"] == "FROM"
    assert resultat["produit_fiable"] is True
    assert resultat["produit_reconnu"] is True
    # La quantite par defaut est appliquee avant la seconde passe : la ligne
    # est donc deja fiable et ne doit pas etre marquee comme recuperee.
    assert resultat["seconde_passe_produit"] is False
    assert resultat["quantite_resolue"] == 1.0


def test_dimension_orpheline_complete_le_produit_precedent() -> None:
    mentions = extraire_mentions_produits(
        "six paquets de galettes de ble, 30 centimetres"
    )

    assert len(mentions) == 1
    assert "30 cm" in mentions[0]["produit_normalise"]


def test_attribut_technique_orphelin_complete_le_produit_precedent() -> None:
    mentions = extraire_mentions_produits(
        "un kilo de gelatine, 120 blooms"
    )

    assert len(mentions) == 1
    assert "120 blooms" in mentions[0]["produit_normalise"]


def test_qualificatif_couleur_orphelin_complete_le_produit_precedent() -> None:
    mentions = extraire_mentions_produits(
        "deux poches de mozzarella, la verte"
    )

    assert len(mentions) == 1
    assert "verte" in mentions[0]["produit_normalise"]


def test_transition_ouvre_un_second_noyau_sans_quantite() -> None:
    mentions = extraire_mentions_produits(
        "90 oeufs et ensuite des glaces"
    )
    produits = [mention["produit_normalise"] for mention in mentions]

    assert any("oeuf" in produit for produit in produits)
    assert any("glace" in produit for produit in produits)


def test_disponibilite_positive_ouvre_un_second_noyau() -> None:
    mentions = extraire_mentions_produits(
        "un carton de panini et si vous en avez de la glace cookie"
    )
    produits = [mention["produit_normalise"] for mention in mentions]

    assert any("panini" in produit for produit in produits)
    assert any("glace cookie" in produit for produit in produits)
