from __future__ import annotations

import src.produits as produits
from transcrire_audios import transcription_liste_longue_a_controler


def _reappro(code: str, libelle: str, score: float = 35.0) -> dict:
    return {
        "code_article": code,
        "libelle_article": libelle,
        "libelle_normalise": libelle.lower(),
        "source_recherche": "catalogue_reappro",
        "source_article": "catalogue_reappro",
        "dans_cadencier_client": False,
        "semantiquement_compatible": True,
        "score_texte": score,
        "score_global": score,
        "score_conditionnement": 0.0,
        "score_conditionnement_physique_sur": 0.0,
        "score_attribut_semantique": 0.0,
        "bonus_historique_compatible": 0.0,
        "bonus_reappro_fallback": 0.0,
        "bonus_volume_historique": 0.0,
        "nb_ventes_article_total": 0,
        "nb_ventes_article_recentes": 0,
        "derniere_vente_article_ordinal": -1,
        "quantite_resolue": 1.0,
        "unite_resolue": "COL",
        "prix": 1.0,
        "raisons": [],
    }


def test_liste_sans_connecteurs_declenche_aussi_la_seconde_ecoute():
    assert transcription_liste_longue_a_controler(
        "deux mayonnaise trois ketchup quatre moutarde",
        duree_audio=22.0,
        nb_segments=3,
    ) is True


def test_dedup_differee_preserve_meme_article_avec_quantite_differente():
    mentions = [
        {
            "produit_normalise": "sucre semoule",
            "quantite_principale": 2,
            "unite_principale": "CAR",
            "raisons_ambiguite": ["repetition_transcription_supprimee"],
        },
        {
            "produit_normalise": "farine t55",
            "quantite_principale": 1,
            "unite_principale": "CAR",
            "raisons_ambiguite": [],
        },
        {
            "produit_normalise": "sucre semoule",
            "quantite_principale": 2,
            "unite_principale": "CAR",
            "raisons_ambiguite": [],
        },
        {
            "produit_normalise": "farine t55",
            "quantite_principale": 1,
            "unite_principale": "CAR",
            "raisons_ambiguite": [],
        },
        {
            "produit_normalise": "sucre semoule",
            "quantite_principale": 3,
            "unite_principale": "CAR",
            "raisons_ambiguite": [],
        },
    ]
    resultat = produits._dedupliquer_repetitions_differees_sures(mentions)
    sucres = [
        item for item in resultat
        if item["produit_normalise"] == "sucre semoule"
    ]
    assert [item["quantite_principale"] for item in sucres] == [2, 3]


def test_secours_reappro_est_porte_par_la_variante_pas_par_le_mot_sauce():
    sriracha = _reappro("A", "SAUCE SRIRACHA ROUGE")
    barbecue = _reappro("B", "SAUCE BARBECUE ROUGE")

    score_sriracha = produits._score_phonetique_reappro(
        "sauce shiracha rouge",
        sriracha,
    )
    score_barbecue = produits._score_phonetique_reappro(
        "sauce shiracha rouge",
        barbecue,
    )

    assert score_sriracha >= 90.0
    assert score_sriracha - score_barbecue >= 8.0


def test_secours_reappro_reste_dans_la_famille_explicitement_dite():
    bon = _reappro("A", "SAUCE SRIRACHA ROUGE")
    hors_famille = _reappro("B", "PUREE SRIRACHA ROUGE", score=70.0)

    selection, score = produits._selection_secours_reappro(
        "sauce shiracha rouge",
        [bon, hors_famille],
    )

    assert selection is not None
    assert selection["code_article"] == "A"
    assert score >= 90.0


def test_secours_reappro_ne_s_ouvre_pas_sans_famille_explicite():
    candidat = _reappro("A", "PRODUIT SRIRACHA ROUGE")
    selection, score = produits._selection_secours_reappro(
        "shiracha rouge",
        [candidat],
    )
    assert selection is None
    assert score == 0.0
