from __future__ import annotations

import extraire_informations as extraction


def test_commande_courte_xipiron_est_tracee_et_valide(
    tmp_path, monkeypatch
) -> None:
    config = tmp_path / "commandes-courtes-clients.json"
    config.write_text(
        """{
          "commandes_courtes": [{
            "client_code": "XIPIRONANGLET",
            "triggers": ["xipiron"],
            "occurrences_min": 2,
            "code_article": "00010900",
            "quantite": 1,
            "unite": "COL"
          }]
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        extraction,
        "CHEMIN_COMMANDES_COURTES_CLIENTS",
        config,
    )
    extraction.charger_commandes_courtes_clients.cache_clear()

    produits, audit = extraction.appliquer_commande_courte_client(
        transcription=(
            "bonsoir basco pour demain xipiron s il vous plait "
            "c est pour xipiron"
        ),
        client_code="XIPIRONANGLET",
        type_action="creation",
        mentions=[{"quantite_principale": None}],
        produits=[],
        produits_client=[
            {
                "code_article": "00010900",
                "libelle_article": "CHIPIRONS TEST",
                "prix": 12.0,
            }
        ],
    )

    assert audit and audit["appliquee"] is True
    assert produits[0]["selection"]["code_article"] == "00010900"
    assert produits[0]["quantite_resolue"] == 1.0
    assert produits[0]["unite_resolue"] == "COL"


def test_commande_courte_ne_remplace_jamais_un_produit_dicte(
    tmp_path, monkeypatch
) -> None:
    config = tmp_path / "commandes-courtes-clients.json"
    config.write_text(
        """{"commandes_courtes":[{
          "client_code":"XIPIRONANGLET", "triggers":["xipiron"],
          "code_article":"00010900", "quantite":1, "unite":"COL"
        }]}""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        extraction,
        "CHEMIN_COMMANDES_COURTES_CLIENTS",
        config,
    )
    extraction.charger_commandes_courtes_clients.cache_clear()
    produits_initiaux = [{"selection": None}]

    produits, audit = extraction.appliquer_commande_courte_client(
        transcription="xipiron et deux cartons de frites",
        client_code="XIPIRONANGLET",
        type_action="creation",
        mentions=[{"quantite_principale": 2.0}],
        produits=produits_initiaux,
        produits_client=[],
    )

    assert produits == produits_initiaux
    assert audit is None
