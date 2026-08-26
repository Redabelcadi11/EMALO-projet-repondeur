from __future__ import annotations

import json
from pathlib import Path

import src.clients as clients
import src.produits as produits
from src.contexte_asr import construire_hotwords_par_telephone
from transcrire_audios import (
    BEAM_SIZE,
    WORD_TIMESTAMPS,
    transcription_liste_longue_a_controler,
)


def _candidat(libelle: str, **extra):
    base = {
        "code_article": "999999",
        "libelle_article": libelle,
        "libelle_normalise": libelle.lower(),
        "source_recherche": "cadencier_client",
        "source_article": "historique_client",
        "dans_cadencier_client": True,
        "semantiquement_compatible": True,
        "score_texte": 90.0,
        "score_global": 100.0,
        "nb_ventes_article_total": 5,
        "nb_ventes_article_recentes": 2,
        "prix": 1.0,
    }
    base.update(extra)
    return base


def test_un_descripteur_isole_ne_prouve_pas_un_produit_compose():
    candidat = _candidat("TARTARE BOEUF AUX COUTEAUX")
    prouve, raisons = produits._preuve_positive_noyau_produit(
        "couteau",
        candidat,
        [],
        {"quantite_principale": 2.0, "unite_principale": "CAR"},
    )
    assert prouve is False
    assert "noyau_unique_secondaire_du_produit_compose" in raisons


def test_le_vrai_noyau_compose_reste_reconnu():
    candidat = _candidat("TARTARE BOEUF AUX COUTEAUX")
    prouve, _ = produits._preuve_positive_noyau_produit(
        "tartare boeuf",
        candidat,
        [],
        {"quantite_principale": 2.0, "unite_principale": "CAR"},
    )
    assert prouve is True


def test_un_nom_usuel_simple_n_est_pas_bloque_par_fromage_de():
    candidat = _candidat("FROMAGE DE BREBIS")
    assert produits._noyau_unique_est_secondaire_du_libelle(
        "brebis", candidat
    ) is False


def test_une_famille_secondaire_ne_remplace_pas_la_famille_principale():
    candidat = _candidat("HUILE D OLIVE EXTRA VIERGE")
    assert produits._noyau_unique_est_secondaire_du_libelle(
        "olive", candidat
    ) is True


def test_un_synonyme_ne_specialise_plus_un_terme_generique():
    variantes = produits._generer_variantes_recherche(
        "moutarde",
        {"moutarde de dijon": ["moutarde"]},
    )
    assert "moutarde" in variantes
    assert "moutarde de dijon" not in variantes


def test_une_vraie_correction_asr_reste_autorisee():
    variantes = produits._generer_variantes_recherche(
        "chistora",
        {"txistorra": ["chistora"]},
    )
    assert "txistorra" in variantes


def test_prix_local_zero_ne_retire_plus_un_bon_candidat_cadencier():
    assert produits._candidat_commandable(
        _candidat("MAYONNAISE 5KG", prix=0.0)
    )


def test_prix_zero_n_ouvre_pas_un_article_global_inactif():
    candidat = _candidat(
        "MAYONNAISE 5KG",
        prix=0.0,
        source_recherche="catalogue_global",
        source_article="catalogue_global",
        dans_cadencier_client=False,
        nb_ventes_article_total=0,
        nb_ventes_article_recentes=0,
    )
    assert produits._candidat_commandable(candidat) is False


def test_recapitulatif_peut_contenir_un_ajout_reel():
    mentions = produits.extraire_mentions_produits(
        "2 cartons mayonnaise, 3 cartons ketchup. "
        "Je repete la commande: 2 cartons mayonnaise, "
        "3 cartons ketchup, 1 carton moutarde."
    )
    textes = [
        str(item.get("produit_normalise") or "")
        for item in mentions
    ]
    assert any("moutarde" in texte for texte in textes)


def test_secours_phonetique_global_reste_borne(monkeypatch):
    candidat = _candidat(
        "FREGOLA SARDA",
        code_article="123456",
        source_recherche="catalogue_global",
        source_article="catalogue_global",
        dans_cadencier_client=False,
        score_texte=40.0,
        score_global=40.0,
        quantite_resolue=2.0,
        unite_resolue="COL",
        nb_ventes_article_total=0,
        nb_ventes_article_recentes=0,
    )
    faux_resultat = [{
        "texte_source": "2 colis fregolla",
        "produit_normalise": "fregolla",
        "quantite_principale": 2.0,
        "modalite_demande": "CERTAINE",
        "role_semantique": "PRODUCT_ITEM",
        "produit_fiable": False,
        "produit_reconnu": False,
        "seconde_passe_produit": False,
        "statut_couverture": "NON_IDENTIFIE",
        "ambigu": True,
        "raisons_ambiguite": ["selection_article_non_nette"],
        "candidats": [candidat],
        "selection": None,
    }]
    monkeypatch.setattr(
        produits,
        "_ORIGINAL_CHERCHER_PRODUITS",
        lambda *args, **kwargs: faux_resultat,
    )
    resultat = produits.chercher_produits([], [], [], {})[0]
    assert resultat["produit_reconnu"] is True
    assert resultat["selection"]["code_article"] == "123456"
    assert any(
        str(raison).startswith("secours_phonetique_global_borne=")
        for raison in resultat["selection"].get("raisons", [])
    )


def test_secours_global_ne_reouvre_pas_couteau_vers_tartare(monkeypatch):
    candidat = _candidat(
        "TARTARE BOEUF AUX COUTEAUX",
        source_recherche="catalogue_global",
        source_article="catalogue_global",
        dans_cadencier_client=False,
        score_texte=40.0,
        score_global=40.0,
        quantite_resolue=2.0,
        unite_resolue="CAR",
        nb_ventes_article_total=0,
        nb_ventes_article_recentes=0,
    )
    faux_resultat = [{
        "texte_source": "2 cartons couteau",
        "produit_normalise": "couteau",
        "quantite_principale": 2.0,
        "modalite_demande": "CERTAINE",
        "role_semantique": "PRODUCT_ITEM",
        "produit_fiable": False,
        "produit_reconnu": False,
        "statut_couverture": "NON_IDENTIFIE",
        "ambigu": True,
        "raisons_ambiguite": ["selection_article_non_nette"],
        "candidats": [candidat],
        "selection": None,
    }]
    monkeypatch.setattr(
        produits,
        "_ORIGINAL_CHERCHER_PRODUITS",
        lambda *args, **kwargs: faux_resultat,
    )
    resultat = produits.chercher_produits([], [], [], {})[0]
    assert resultat["produit_reconnu"] is False


def test_liste_moyenne_est_recontrolee_si_des_unites_manquent():
    assert transcription_liste_longue_a_controler(
        "deux mayonnaise puis trois ketchup et quatre moutarde",
        duree_audio=22.0,
        nb_segments=3,
    )


def test_whisper_utilise_des_defauts_plus_precis():
    assert BEAM_SIZE >= 3
    assert WORD_TIMESTAMPS is True


def test_hotwords_couvrent_reference_rare_et_attributs_critiques():
    clients_data = [
        {
            "code_client": "C1",
            "nom_client": "Restaurant Test",
            "ville": "Pau",
            "aliases": [],
            "telephones": ["0612345678"],
            "telephones_confirmes": [],
        }
    ]
    cadencier = {
        "C1": [
            {
                "code_article": "1",
                "libelle_article": "FRITES SURGELE",
                "nb_ventes_article_recentes": 120,
                "nb_ventes_article_total": 500,
            },
            {
                "code_article": "2",
                "libelle_article": "TXISTORRA FRAIS",
                "nb_ventes_article_recentes": 0,
                "nb_ventes_article_total": 1,
            },
        ]
    }
    hotwords = construire_hotwords_par_telephone(
        clients_data,
        cadencier,
        limite_termes=20,
    )["0612345678"].casefold()
    assert "restaurant test" in hotwords
    assert "txistorra" in hotwords
    assert "frais" in hotwords
    assert "surgele" in hotwords


def test_cadencier_client_reste_tres_prioritaire_dans_le_moteur_produit():
    commun = {
        "score_texte": 60.0,
        "score_attribut_semantique": 0.0,
        "score_conditionnement_physique_sur": 0.0,
        "bonus_historique_compatible": 0.0,
        "bonus_reappro_fallback": 0.0,
        "score_conditionnement": 0.0,
        "nb_ventes_article_total": 0,
        "nb_ventes_article_recentes": 0,
        "derniere_vente_article_ordinal": -1,
        "bonus_volume_historique": 0.0,
        "source_article": "",
        "raisons": [],
    }
    cad = dict(commun, source_recherche="cadencier_client")
    global_ = dict(commun, source_recherche="catalogue_global")
    assert (
        produits._legacy._score_selection_ponderee(cad)
        - produits._legacy._score_selection_ponderee(global_)
    ) == 50.0


def test_score_cadencier_client_est_reduit_pour_identifier_un_client():
    mentions = [
        {
            "produit_normalise": "mayonnaise",
            "texte_produit": "mayonnaise",
        }
    ]
    produits_client = [
        {
            "code_article": "1",
            "libelle_article": "MAYONNAISE",
            "libelle_normalise": "mayonnaise",
        }
    ]
    score_brut, _, _ = clients._ORIGINAL_SCORE_CADENCIER(
        mentions_produits=mentions,
        produits_client=produits_client,
    )
    score_actif, _, _ = clients.calculer_score_cadencier(
        mentions_produits=mentions,
        produits_client=produits_client,
    )
    assert score_actif == round(score_brut * 0.25, 2)


def test_regles_demandees_par_le_metier_restent_inchangees():
    root = Path(__file__).resolve().parents[1]
    regles = json.loads(
        (root / "config" / "regles-metier-sures.json").read_text(
            encoding="utf-8"
        )
    )
    assert regles["telephone_exact_verrouille"] is True
    assert regles["reappro_variante_intra_famille"] is False

    source = (
        root / "extraire_informations.py"
    ).read_text(encoding="utf-8")
    assert "codes_info.intersection(codes_cadencier)" in source
