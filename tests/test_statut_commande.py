from __future__ import annotations

from datetime import date

from extraire_informations import determiner_statut_commande
from extraire_informations import extraire_date_livraison
from extraire_informations import extraire_mentions_suppression
from extraire_informations import preparer_exports_commandes
from extraire_informations import resoudre_date_livraison


def test_statut_problematique_si_client_absent() -> None:
    resultat = {
        "client_retenu": None,
        "produits": [],
    }

    statut, raisons, _ = determiner_statut_commande(
        resultat
    )

    assert statut == "PROBLEMATIQUE"
    assert "client_non_mentionne_ou_non_identifie" in raisons


def test_statut_problematique_si_produit_non_vendu() -> None:
    resultat = {
        "client_retenu": "CLIENT1",
        "produits": [
            {
                "selection": None,
            }
        ],
    }

    statut, raisons, _ = determiner_statut_commande(
        resultat
    )

    assert statut == "PROBLEMATIQUE"
    assert any(
        raison.startswith("produit_non_vendu")
        for raison in raisons
    )


def test_statut_validee_meme_sans_date() -> None:
    resultat = {
        "client_retenu": "CLIENT1",
        "produits": [
            {
                "selection": {
                    "code_article": "A1",
                    "libelle_article": "TEST",
                    "score_global": 60.0,
                    "source_recherche": "cadencier_client",
                    "prix": 10.0,
                },
                "quantite_principale": 2.0,
                "unite_principale": "PCE",
                "texte_source": "2 pieces test",
                "produit_fiable": True,
                "ambigu": False,
            }
        ],
    }

    statut, raisons, lignes = determiner_statut_commande(
        resultat
    )

    assert statut == "VALIDEE"
    assert raisons == []
    assert len(lignes) == 1


def test_statut_problematique_si_produit_non_fiable() -> None:
    resultat = {
        "client_retenu": "CLIENT1",
        "produits": [
            {
                "selection": {
                    "code_article": "A1",
                    "libelle_article": "TEST",
                    "score_global": 61.0,
                    "source_recherche": "catalogue_global",
                    "prix": 10.0,
                },
                "quantite_principale": 2.0,
                "unite_principale": "PCE",
                "texte_source": "2 pieces test",
                "produit_fiable": False,
                "ambigu": True,
            }
        ],
    }

    statut, raisons, _ = determiner_statut_commande(
        resultat
    )

    assert statut == "PROBLEMATIQUE"
    assert "produit_non_fiable_ligne_1" in raisons


def test_date_par_defaut_si_absente() -> None:
    resultat = resoudre_date_livraison(
        transcription="bonjour je voudrais deux kilos de beurre",
        date_reference=date(2026, 6, 1),
    )

    assert resultat["date_iso"] == "2026-06-01"
    assert resultat["date_par_defaut"] is True


def test_date_par_defaut_journee_demain() -> None:
    resultat = resoudre_date_livraison(
        transcription="bonjour commande sans date",
        heure_reference=15,
        jour_reference=date(2026, 6, 1),
    )

    assert resultat["date_iso"] == "2026-06-02"
    assert resultat["date_par_defaut"] is True


def test_date_par_defaut_nuit_aujourdhui() -> None:
    resultat = resoudre_date_livraison(
        transcription="bonjour commande sans date",
        heure_reference=2,
        jour_reference=date(2026, 6, 1),
    )

    assert resultat["date_iso"] == "2026-06-01"
    assert resultat["date_par_defaut"] is True


def test_date_retenue_est_la_premiere_mentionnee() -> None:
    resultat = extraire_date_livraison(
        transcription=(
            "bonjour livraison lundi ou le 30/09/2026"
        ),
        date_reference=date(2026, 6, 9),
    )

    assert resultat is not None
    assert resultat["expression"] == "lundi"
    assert resultat["date_iso"] == "2026-06-15"


def test_suppression_sans_quantite_extrait_le_produit() -> None:
    mentions = extraire_mentions_suppression(
        "bonjour merci de supprimer le beurre doux"
    )

    assert len(mentions) == 1
    assert mentions[0]["produit_normalise"] == "beurre doux"
    assert mentions[0]["unite_principale"] is None


def test_export_suppression_retire_ligne_validee() -> None:
    commandes = [
        {
            "genere_le": "2026-06-09T10:00:00",
            "fichier_audio": "appel1.ogg",
            "client_retenu": "CLIENT1",
            "client_nom_retenu": "Restaurant Test",
            "date_livraison": {
                "date_iso": "2026-09-30"
            },
            "statut": "VALIDEE",
            "type_action_commande": "creation",
            "lignes_commande": [
                {
                    "ordre_ligne": 1,
                    "code_article": "BEURRE1",
                    "libelle_article": "BEURRE DOUX 10K",
                    "quantite": 10.0,
                    "unite": "KG",
                    "score_article": 95.0,
                    "source_recherche": "cadencier_client",
                    "texte_source": "10 kg de beurre doux",
                    "prix": 25.0,
                },
                {
                    "ordre_ligne": 2,
                    "code_article": "MOUT1",
                    "libelle_article": "MOUTARDE 1K",
                    "quantite": 1.0,
                    "unite": "KG",
                    "score_article": 92.0,
                    "source_recherche": "cadencier_client",
                    "texte_source": "1 kg de moutarde",
                    "prix": 4.0,
                },
            ],
            "raisons_problematiques": [],
            "transcription": "",
            "mentions_produits": [],
        },
        {
            "genere_le": "2026-06-09T10:05:00",
            "fichier_audio": "appel2.ogg",
            "client_retenu": "CLIENT1",
            "client_nom_retenu": "Restaurant Test",
            "date_livraison": {
                "date_iso": "2026-09-30"
            },
            "statut": "VALIDEE",
            "type_action_commande": "suppression",
            "lignes_commande": [
                {
                    "ordre_ligne": 1,
                    "code_article": "BEURRE1",
                    "libelle_article": "BEURRE DOUX 10K",
                    "quantite": 1.0,
                    "unite": None,
                    "score_article": 91.0,
                    "source_recherche": "cadencier_client",
                    "texte_source": "beurre doux",
                    "prix": 25.0,
                }
            ],
            "raisons_problematiques": [],
            "transcription": "supprimer le beurre doux",
            "mentions_produits": [
                {
                    "produit_normalise": "beurre doux",
                }
            ],
        },
    ]

    lignes_validees, lignes_problematiques = (
        preparer_exports_commandes(
            commandes=commandes,
            run_id="RUN1",
        )
    )

    assert len(lignes_validees) == 1
    assert lignes_validees[0]["code_article"] == "MOUT1"
    assert lignes_problematiques == []


def test_export_suppression_introuvable_est_problematique() -> None:
    commandes = [
        {
            "genere_le": "2026-06-09T10:05:00",
            "fichier_audio": "appel2.ogg",
            "client_retenu": "CLIENT1",
            "client_nom_retenu": "Restaurant Test",
            "date_livraison": {
                "date_iso": "2026-09-30"
            },
            "statut": "VALIDEE",
            "type_action_commande": "suppression",
            "lignes_commande": [
                {
                    "ordre_ligne": 1,
                    "code_article": "BEURRE1",
                    "libelle_article": "BEURRE DOUX 10K",
                    "quantite": 1.0,
                    "unite": None,
                    "score_article": 91.0,
                    "source_recherche": "cadencier_client",
                    "texte_source": "beurre doux",
                    "prix": 25.0,
                }
            ],
            "raisons_problematiques": [],
            "transcription": "supprimer le beurre doux",
            "mentions_produits": [
                {
                    "produit_normalise": "beurre doux",
                }
            ],
        },
    ]

    lignes_validees, lignes_problematiques = (
        preparer_exports_commandes(
            commandes=commandes,
            run_id="RUN1",
        )
    )

    assert lignes_validees == []
    assert len(lignes_problematiques) == 1
    assert (
        "suppression_produit_introuvable"
        in lignes_problematiques[0][
            "raisons_problematiques"
        ]
    )
