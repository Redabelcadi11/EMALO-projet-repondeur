from __future__ import annotations

from datetime import date

from extraire_informations import resoudre_date_livraison
from src.openai_arbitrage import build_payload, validate_decision
from src.produits import (
    chercher_produits,
    construire_catalogue_global,
    extraire_mentions_produits,
)


def test_formulations_de_commande_jusqu_alors_ignorees() -> None:
    cas = {
        "ce serait pour commander 5 pieces filet mignon": (5.0, "filet mignon"),
        "je souhaite recommander deux poches filet poulet": (2.0, "filet poulet"),
        "vous pourrez avoir deux boites piperade": (2.0, "piperade"),
    }
    for transcription, attendu in cas.items():
        mentions = extraire_mentions_produits(transcription)
        assert len(mentions) == 1
        assert mentions[0]["quantite_principale"] == attendu[0]
        assert mentions[0]["texte_produit"] == attendu[1]


def test_bloc_adjacent_repete_par_whisper_est_deduplique() -> None:
    mentions = extraire_mentions_produits(
        "un poulet, deux chantilly, trois ail, "
        "un poulet, deux chantilly, trois ail"
    )
    assert [item["texte_produit"] for item in mentions] == [
        "poulet",
        "chantilly",
        "ail",
    ]
    assert all(
        "repetition_transcription_supprimee" in item["raisons_ambiguite"]
        for item in mentions
    )


def test_catalogue_global_agrege_les_ventes_et_complete_le_referentiel() -> None:
    base = {
        "code_article": "A1",
        "libelle_article": "CREME ENTIERE",
        "libelle_normalise": "creme entiere",
        "prix": 5.0,
        "nb_ventes_article_recentes": 1,
        "derniere_vente_article_iso": "2026-06-01",
        "derniere_vente_article_ordinal": 100,
    }
    cadencier = {
        "C1": [{**base, "nb_ventes_article_total": 5}],
        "C2": [{**base, "nb_ventes_article_total": 7}],
    }
    catalogue = construire_catalogue_global(
        cadencier,
        [{"code_article": "A2", "libelle_article": "PIPERADE"}],
    )
    par_code = {item["code_article"]: item for item in catalogue}
    assert par_code["A1"]["nb_ventes_article_total"] == 12
    assert par_code["A2"]["source_article"] == "referentiel_articles"


def test_conditionnement_x6_convertit_les_pieces_en_cartons() -> None:
    mentions = extraire_mentions_produits("12 pieces burrata")
    produit = {
        "code_article": "B1",
        "libelle_article": "BURRATA X6",
        "libelle_normalise": "burrata x6",
        "prix": 8.0,
        "unite_vente": "CAR",
        "quantite_habituelle_commande": 2.0,
        "ratio_net_par_unite": 0.6,
        "nb_ventes_article_total": 10,
        "nb_ventes_article_recentes": 4,
        "derniere_vente_article_ordinal": 100,
    }
    resultat = chercher_produits(
        mentions, [produit], [produit], {}, 3
    )[0]
    assert resultat["quantite_resolue"] == 2.0
    assert resultat["unite_resolue"] == "CAR"


def test_demain_apres_minuit_reste_sur_la_date_operationnelle() -> None:
    resultat = resoudre_date_livraison(
        "livraison demain",
        date_reference=date(2026, 7, 9),
        heure_reference=1,
    )
    assert resultat["date_iso"] == "2026-07-09"


def test_arbitrage_global_possible_seulement_si_cadencier_faible() -> None:
    commande = {
        "clients_candidats": [{"code_client": "C1"}],
        "produits": [
            {
                "candidats": [
                    {"code_article": "CAD", "dans_cadencier_client": True, "score_global": 45},
                    {"code_article": "GLOB", "dans_cadencier_client": False, "score_global": 85},
                ]
            }
        ],
    }
    decision = {
        "client_code": "C1",
        "produits": [
            {"index": 0, "code_article": "GLOB", "quantite": 2, "unite": "CAR", "confidence": 0.9}
        ],
    }
    assert validate_decision(commande, decision, {}) == (True, [])
    commande["produits"][0]["candidats"][0]["score_global"] = 75
    valide, erreurs = validate_decision(commande, decision, {})
    assert not valide
    assert "produit_0_global_malgre_cadencier_fiable" in erreurs


def test_payload_ia_limite_a_cinq_candidats_par_produit() -> None:
    commande = {
        "produits": [
            {"candidats": [{"code_article": str(index)} for index in range(8)]}
        ]
    }
    payload = build_payload(commande, {})
    assert len(payload["produits_detectes"][0]["candidats"]) == 5
