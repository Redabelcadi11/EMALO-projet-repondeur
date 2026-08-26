from __future__ import annotations

import extraire_informations as extraction
from src import llm_arbitrage


def _candidat(
    code: str,
    libelle: str,
    score: float,
    quantite: float,
    unite: str,
) -> dict:
    return {
        "code_article": code,
        "libelle_article": libelle,
        "score_texte": score,
        "score_global": score,
        "score_selection": score,
        "source_recherche": "cadencier_client",
        "semantiquement_compatible": True,
        "quantite_resolue": quantite,
        "unite_resolue": unite,
        "raisons": [],
    }


def test_llama_borne_remplace_un_choix_faible_par_candidat_existant(
    monkeypatch,
) -> None:
    cannelle = _candidat("CAN", "CANNELLE EN BATONS 1K", 48.0, 18, "POC")
    burrata = _candidat("BUR", "BURRATA VACHE 125G X6P", 29.0, 3, "CAR")
    produit = {
        "segment_id": "segment-7",
        "texte_source": "18 bourratins en 120 grammes",
        "quantite_principale": 18.0,
        "quantite_resolue": 18.0,
        "unite_resolue": "POC",
        "selection": cannelle,
        "candidats": [cannelle, burrata],
        "produit_fiable": True,
        "ambigu": False,
        "raisons_ambiguite": [],
    }
    monkeypatch.setattr(llm_arbitrage, "ollama_disponible", lambda: True)
    monkeypatch.setattr(
        llm_arbitrage,
        "arbitrer_produit_phonetique",
        lambda **_: burrata,
    )

    produits, audit = extraction.arbitrer_produits_ambigus_llama(
        [
            produit,
            {
                "segment_id": "segment-cannelle",
                "texte_source": "un sachet de cannelle",
                "quantite_principale": 1.0,
                "selection": cannelle,
                "candidats": [cannelle, burrata],
            },
        ],
        "CLIENT TEST",
    )

    assert produits[0]["selection"]["code_article"] == "BUR"
    assert produits[0]["quantite_resolue"] == 3
    assert produits[0]["unite_resolue"] == "CAR"
    assert audit[0]["applique"] is True


def test_llama_ne_remplace_pas_un_choix_faible_isole(monkeypatch) -> None:
    monkeypatch.setattr(llm_arbitrage, "ollama_disponible", lambda: True)
    called = False

    def should_not_be_called(**_):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(
        llm_arbitrage,
        "arbitrer_produit_phonetique",
        should_not_be_called,
    )
    candidat = _candidat("A", "ARTICLE TEST", 20.0, 1, "PI")
    produits, audit = extraction.arbitrer_produits_ambigus_llama(
        [{
            "segment_id": "segment-1",
            "texte_source": "un article test",
            "quantite_principale": 1.0,
            "selection": candidat,
            "candidats": [candidat, dict(candidat, code_article="B")],
        }],
        "CLIENT TEST",
    )

    assert produits[0]["selection"]["code_article"] == "A"
    assert audit == []
    assert called is False


def test_llama_arbitre_une_selection_isolee_faible_avec_alternative(
    monkeypatch,
) -> None:
    fruits_rouges = _candidat(
        "ROUGE", "COULIS FRUITS ROUGES 500G", 64.0, 3, "BARQ"
    )
    mangue = _candidat(
        "MANGUE", "COULIS MANGUE PASSION 500G", 38.0, 3, "BARQ"
    )
    # Les relations semantiques deterministes ont deja etabli que
    # ``fruits exotiques`` est incompatible avec ``fruits rouges`` et
    # compatible avec mangue/passion. Llama peut alors lever l'ambiguite
    # malgre une ressemblance textuelle brute plus faible.
    fruits_rouges["score_attribut_semantique"] = -30.0
    mangue["score_attribut_semantique"] = 20.0
    produit = {
        "segment_id": "segment-8",
        "texte_source": "3 coulis de fruits exotiques",
        "quantite_principale": 3.0,
        "quantite_resolue": 3.0,
        "unite_resolue": "BARQ",
        "selection": fruits_rouges,
        "candidats": [fruits_rouges, mangue],
        "produit_fiable": True,
        "produit_reconnu": True,
        "ambigu": False,
        "raisons_ambiguite": [],
    }
    monkeypatch.setattr(llm_arbitrage, "ollama_disponible", lambda: True)
    monkeypatch.setattr(
        llm_arbitrage,
        "arbitrer_produit_phonetique",
        lambda **_: mangue,
    )

    produits, audit = extraction.arbitrer_produits_ambigus_llama(
        [produit], "CLIENT TEST"
    )

    assert produits[0]["selection"]["code_article"] == "MANGUE"
    assert produits[0]["produit_fiable"] is True
    assert audit == [{
        "segment_id": "segment-8",
        "applique": True,
        "code_initial": "ROUGE",
        "code_article": "MANGUE",
        "candidats_envoyes": 2,
        "declencheur": "selection_faible_alternative_lexicale",
        "raison": "selection_par_arbitrage_llama_produit",
    }]


def test_llama_sans_choix_ne_valide_pas_un_article_faible_hors_sens(
    monkeypatch,
) -> None:
    sesame = _candidat("SESAME", "GRAINE SESAME BLANC 1K", 38.0, 6, "BOITE")
    cumin = _candidat("CUMIN", "CUMIN MOULU 350G", 40.0, 6, "BOITE")
    produit = {
        "segment_id": "segment-5",
        "texte_source": "6 boites de cumin en grain",
        "quantite_principale": 6.0,
        "quantite_resolue": 6.0,
        "unite_resolue": "BOITE",
        "selection": sesame,
        "candidats": [sesame, cumin],
        "produit_fiable": True,
        "produit_reconnu": True,
        "ambigu": False,
        "raisons_ambiguite": [],
    }
    monkeypatch.setattr(llm_arbitrage, "ollama_disponible", lambda: True)
    monkeypatch.setattr(
        llm_arbitrage,
        "arbitrer_produit_phonetique",
        lambda **_: None,
    )

    produits, audit = extraction.arbitrer_produits_ambigus_llama(
        [produit], "CLIENT TEST"
    )

    assert produits[0]["produit_fiable"] is False
    assert produits[0]["produit_reconnu"] is False
    assert produits[0]["ambigu"] is True
    assert "llm_produit_sans_choix" in produits[0]["raisons_ambiguite"]
    assert audit[0]["raison"] == "llama_sans_choix_ligne_a_confirmer"


def test_llama_ne_revoit_pas_un_choix_texte_fort(monkeypatch) -> None:
    monkeypatch.setattr(llm_arbitrage, "ollama_disponible", lambda: True)
    called = False

    def should_not_be_called(**_):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(
        llm_arbitrage,
        "arbitrer_produit_phonetique",
        should_not_be_called,
    )
    fort = _candidat("FORT", "KETCHUP SEAU 5L", 88.0, 1, "BID")
    autre = _candidat("AUTRE", "KETCHUP FLACON 1L", 45.0, 1, "PI")
    extraction.arbitrer_produits_ambigus_llama(
        [{
            "segment_id": "segment-1",
            "texte_source": "un seau de ketchup 5 litres",
            "quantite_principale": 1.0,
            "selection": fort,
            "candidats": [fort, autre],
        }],
        "CLIENT TEST",
    )

    assert called is False


def test_llama_ne_remplace_pas_un_meilleur_candidat_sans_signal_semantique(
    monkeypatch,
) -> None:
    concasse = _candidat("CONCASSE", "POIVRE NOIR CONCASSE 1K", 62.65, 1, "POC")
    moulu = _candidat("MOULU", "POIVRE GRIS MOULU 470G", 62.08, 1, "BOITE")
    produit = {
        "segment_id": "segment-poivre",
        "texte_source": "un sachet de poivre mignonnette",
        "quantite_principale": 1.0,
        "quantite_resolue": 1.0,
        "unite_resolue": "POC",
        "selection": concasse,
        "candidats": [concasse, moulu],
        "produit_fiable": True,
        "produit_reconnu": True,
        "ambigu": False,
        "raisons_ambiguite": [],
    }
    monkeypatch.setattr(llm_arbitrage, "ollama_disponible", lambda: True)
    monkeypatch.setattr(
        llm_arbitrage,
        "arbitrer_produit_phonetique",
        lambda **_: moulu,
    )

    produits, audit = extraction.arbitrer_produits_ambigus_llama(
        [produit], "CLIENT TEST"
    )

    assert produits[0]["selection"]["code_article"] == "CONCASSE"
    assert audit[0]["raison"] == (
        "llama_remplacement_rejete_protection_deterministe"
    )


def test_llama_ne_sort_pas_du_cadencier_si_la_famille_y_est_plausible(
    monkeypatch,
) -> None:
    pain_client = _candidat(
        "CLIENT", "PAIN BUNS BRIOCHE NATURE 11CM X36P", 58.0, 2, "COL"
    )
    pain_client["dans_cadencier_client"] = True
    pain_client["noyau_eligible_signaux_secondaires"] = True
    pain_secours = _candidat(
        "SECOURS", "PAIN BUNS GEANT 12CM X30P", 63.0, 2, "CAR"
    )
    pain_secours["dans_cadencier_client"] = False
    pain_secours["source_recherche"] = "catalogue_reappro"
    pain_secours["noyau_eligible_signaux_secondaires"] = True
    produit = {
        "segment_id": "segment-pain",
        "texte_source": "2 pains burgers",
        "quantite_principale": 2.0,
        "quantite_resolue": 2.0,
        "unite_resolue": "COL",
        "selection": pain_client,
        "candidats": [pain_client, pain_secours],
        "produit_fiable": True,
        "produit_reconnu": True,
        "ambigu": False,
        "raisons_ambiguite": [],
    }
    monkeypatch.setattr(llm_arbitrage, "ollama_disponible", lambda: True)
    monkeypatch.setattr(
        llm_arbitrage,
        "arbitrer_produit_phonetique",
        lambda **_: pain_secours,
    )

    produits, audit = extraction.arbitrer_produits_ambigus_llama(
        [produit], "CLIENT TEST"
    )

    assert produits[0]["selection"]["code_article"] == "CLIENT"
    assert audit[0]["raison"] == (
        "llama_secours_rejete_cadencier_plausible"
    )


def test_llama_ne_recoit_pas_une_mention_sans_quantite(monkeypatch) -> None:
    monkeypatch.setattr(llm_arbitrage, "ollama_disponible", lambda: True)
    called = False

    def should_not_be_called(**_):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(
        llm_arbitrage,
        "arbitrer_produit_phonetique",
        should_not_be_called,
    )
    candidat = _candidat("A", "ARTICLE TEST", 20.0, 1, "PI")
    produits, audit = extraction.arbitrer_produits_ambigus_llama(
        [{
            "segment_id": "segment-1",
            "texte_source": "bonjour client test",
            "quantite_principale": None,
            "selection": candidat,
            "candidats": [candidat, dict(candidat, code_article="B")],
        }],
        "CLIENT TEST",
    )

    assert produits[0]["selection"]["code_article"] == "A"
    assert audit == []
    assert called is False
