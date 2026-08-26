from __future__ import annotations

from datetime import date

import extraire_informations as extraction


def test_date_fichier_en_soiree_est_le_lendemain() -> None:
    """Un appel a 23 h sans date vise la prochaine livraison, le lendemain."""
    resultat = extraction.resoudre_date_livraison(
        "commande sans date",
        date_reference=date(2026, 7, 8),
        heure_reference=23,
    )

    assert resultat["date_iso"] == "2026-07-09"
    assert resultat["expression"] == "defaut_soiree_date_demain"


def test_date_fichier_a_22h_est_le_lendemain() -> None:
    resultat = extraction.resoudre_date_livraison(
        "commande sans date",
        date_reference=date(2026, 7, 8),
        heure_reference=22,
    )

    assert resultat["date_iso"] == "2026-07-09"
    assert resultat["expression"] == "defaut_soiree_date_demain"


def test_demain_dicte_a_23h_est_le_lendemain_civil() -> None:
    resultat = extraction.resoudre_date_livraison(
        "commande pour demain matin",
        date_reference=date(2026, 7, 8),
        heure_reference=23,
    )

    assert resultat["date_iso"] == "2026-07-09"
    assert resultat["date_par_defaut"] is False


def test_demain_dicte_apres_minuit_reste_le_jour_civil_courant() -> None:
    resultat = extraction.resoudre_date_livraison(
        "commande pour demain matin",
        date_reference=date(2026, 7, 9),
        heure_reference=1,
    )

    assert resultat["date_iso"] == "2026-07-09"
    assert resultat["date_par_defaut"] is False


def test_date_fichier_en_journee_est_le_lendemain() -> None:
    """Appel en journee (ex: 14h) -> livraison le lendemain."""
    resultat = extraction.resoudre_date_livraison(
        "commande sans date",
        date_reference=date(2026, 7, 8),
        heure_reference=14,
    )

    assert resultat["date_iso"] == "2026-07-09"
    assert resultat["expression"] == "defaut_journee_date_demain"


def test_date_fichier_apres_minuit_reste_le_meme_jour() -> None:
    resultat = extraction.resoudre_date_livraison(
        "commande sans date",
        date_reference=date(2026, 7, 9),
        heure_reference=1,
    )

    assert resultat["date_iso"] == "2026-07-09"
    assert resultat["expression"] == "defaut_nuit_date_du_jour"


def test_unite_copilote_remplace_unite_generique(tmp_path, monkeypatch) -> None:
    reference = tmp_path / "unites-articles.csv"
    reference.write_text(
        "code_article;unite\n00020295;BOITE\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(extraction, "CHEMIN_UNITES_ARTICLES", reference)
    extraction.charger_unites_articles.cache_clear()

    lignes, raisons = extraction.construire_lignes_commande(
        [
            {
                "selection": {
                    "code_article": "00020295",
                    "libelle_article": "TEST",
                    "prix": 1.0,
                },
                "quantite_principale": 2.0,
                "unite_principale": "PCE",
                "produit_fiable": True,
                "ambigu": False,
            }
        ]
    )

    assert raisons == []
    assert lignes[0]["unite"] == "BOITE"
