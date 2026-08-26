from __future__ import annotations

from src.produits import (
    _bonus_preference_metier,
    _bonus_regle_apprentissage,
    _candidat_commandable,
    _score_selection_ponderee,
)


def _candidat(**overrides: object) -> dict:
    candidat = {
        "prix": 2.0,
        "score_texte": 70.0,
        "score_conditionnement": 20.0,
        "dans_cadencier_client": True,
        "nb_ventes_article_total": 2,
        "nb_ventes_article_recentes": 1,
        "derniere_vente_article_ordinal": 739780,
        "source_article": "historique_client",
        "libelle_normalise": "article test",
        "unite_vente": "PI",
    }
    candidat.update(overrides)
    return candidat


def test_candidat_sans_prix_recemment_vendu_et_tres_proche_est_admis() -> None:
    assert _candidat_commandable(
        _candidat(
            prix=0.0,
            score_texte=90.0,
        )
    )
    assert not _candidat_commandable(
        _candidat(
            prix=0.0,
            score_texte=60.0,
        )
    )


def test_candidat_sans_prix_semantiquement_confirme_et_tres_vendu_est_admis() -> None:
    candidat = _candidat(
        prix=0.0,
        score_texte=58.0,
        score_conditionnement=76.0,
        dans_cadencier_client=False,
        nb_ventes_article_total=96,
        nb_ventes_article_recentes=86,
        derniere_vente_article_ordinal=739787,
        raisons=["preference_filet_poulet_cru_sous_vide"],
    )
    assert _candidat_commandable(candidat)
    candidat["raisons"] = []
    assert not _candidat_commandable(candidat)


def test_score_favorise_l_usage_client_recent() -> None:
    ancien = _candidat(
        nb_ventes_article_total=20,
        nb_ventes_article_recentes=0,
        derniere_vente_article_ordinal=739710,
    )
    recent = _candidat(
        nb_ventes_article_total=5,
        nb_ventes_article_recentes=4,
        derniere_vente_article_ordinal=739785,
    )

    assert _score_selection_ponderee(
        recent
    ) > _score_selection_ponderee(ancien)


def test_preferences_semantiques_generales() -> None:
    bonus_oeuf, raison_oeuf = _bonus_preference_metier(
        {
            "produit_normalise": "oeufs",
            "texte_source": "une boite d oeufs",
        },
        _candidat(
            libelle_normalise="oeuf arradoy moyen 53 63 x90p",
        ),
    )
    bonus_jambon, raison_jambon = _bonus_preference_metier(
        {
            "produit_normalise": "jambon blanc tranche",
            "texte_source": "un jambon blanc tranche",
        },
        _candidat(
            libelle_normalise="jambon cuit superieur 20 tranches",
        ),
    )

    assert bonus_oeuf >= 20
    assert raison_oeuf == "preference_oeuf_coquille_par_defaut"
    assert bonus_jambon >= 20
    assert raison_jambon == "preference_jambon_blanc_cuit"


def test_preferences_distinguent_les_variantes_metier_proches() -> None:
    cas = [
        (
            "pointes de parmesan",
            "2 pointes de parmesan",
            "parmigiano reggiano dop 18 mois 1 1k",
            "preference_parmesan_bloc",
        ),
        (
            "sauce ketchup",
            "2 bouteilles de sauce ketchup",
            "ketchup 950ml",
            "preference_ketchup_hors_dosette",
        ),
        (
            "mozzarella pas la rapee mais des morceaux",
            "des morceaux de mozzarella pas la rapee",
            "mozzarella cossette 40 ue 2kg",
            "preference_mozzarella_cossette_non_rapee",
        ),
        (
            "semoule moyenne",
            "un sac de semoule moyenne",
            "couscous grain moyen dari 5k",
            "preference_semoule_moyenne_couscous",
        ),
    ]
    for produit, source, libelle, raison_attendue in cas:
        bonus, raison = _bonus_preference_metier(
            {"produit_normalise": produit, "texte_source": source},
            _candidat(libelle_normalise=libelle),
        )
        assert bonus >= 38
        assert raison == raison_attendue


def test_oeufs_prefere_le_colisage_le_plus_proche() -> None:
    mention = {
        "produit_normalise": "oeufs",
        "texte_source": "180 oeufs",
        "quantite_principale": 180,
    }
    bonus_180, _ = _bonus_preference_metier(
        mention,
        _candidat(libelle_normalise="oeuf moyen x180p"),
    )
    bonus_360, _ = _bonus_preference_metier(
        mention,
        _candidat(libelle_normalise="oeuf moyen x360p"),
    )
    assert bonus_180 > bonus_360


def test_preferences_couvrent_pluriels_formats_et_phonetique() -> None:
    cas = [
        (
            "pulpes de cerises noires en boiron",
            "5 pulpes de cerises noires en boiron",
            "puree cerise noire 100 boiron 1k",
            "preference_puree_cerise_noire",
        ),
        (
            "olives noires en 4 quarts",
            "6 boites d olives noires en 4 quarts",
            "olive noire denoyautee 4 4",
            "preference_olive_noire_4_4",
        ),
        (
            "coeurs d artichauts de bon duel",
            "les coeurs d artichauts de bon duel",
            "fond artichaut bonduelle 60 70 2 5k",
            "preference_artichaut_bonduelle",
        ),
        (
            "poulets prets a cuire",
            "4 poulets prets a cuire",
            "poulet fermier jaune 1 5k x4p",
            "preference_poulet_entier_pret_a_cuire",
        ),
    ]
    for produit, source, libelle, raison_attendue in cas:
        bonus, raison = _bonus_preference_metier(
            {"produit_normalise": produit, "texte_source": source},
            _candidat(libelle_normalise=libelle),
        )
        assert bonus >= 48
        assert raison == raison_attendue


def test_regle_apprise_exige_mention_et_libelle(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.produits._charger_regles_apprentissage",
        lambda: [
            {
                "id": "parmesan_bloc",
                "mention_all": ["parmesan", "bloc"],
                "label_all": ["parmigiano"],
                "label_none": ["rape"],
                "bonus": 60,
                "enabled": True,
            }
        ],
    )

    assert _bonus_regle_apprentissage(
        "parmesan en bloc",
        "un parmesan en bloc",
        "parmigiano reggiano 18 mois",
    ) == (60.0, "preference_apprise_parmesan_bloc")
    assert _bonus_regle_apprentissage(
        "parmesan rape",
        "une poche de parmesan rape",
        "parmigiano reggiano 18 mois",
    ) == (0.0, None)
