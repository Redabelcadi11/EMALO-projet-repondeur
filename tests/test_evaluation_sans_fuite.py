from __future__ import annotations

from pathlib import Path

from src import evaluation_safety
from src import produits
from src.profils_agressifs import charger_profils_agressifs


PROJECT_ROOT = Path(__file__).parents[1]


def test_politique_stricte_interdit_les_profils_et_historiques_erp() -> None:
    policy = evaluation_safety.load_evaluation_safety_policy()
    assert policy.valid is True
    assert policy.mode == "strict_no_target_leakage"
    assert policy.allow_aggressive_profiles is False
    assert policy.allow_historical_erp_enrichment is False
    assert policy.allow_client_specific_learned_rules is False


def test_profils_agressifs_sont_vides_meme_si_le_fichier_existe() -> None:
    assert (PROJECT_ROOT / "config" / "profils-clients-agressifs.json").exists()
    assert charger_profils_agressifs() == {
        "substitutions": {},
        "ajouts_fantomes": {},
    }


def test_regles_generees_depuis_comparaison_es_ne_sont_pas_chargees() -> None:
    produits._REGLES_APPRENTISSAGE_CACHE["mtime_ns"] = None
    produits._REGLES_APPRENTISSAGE_CACHE["regles"] = []
    rules = produits._charger_regles_apprentissage()
    assert all(
        rule.get("origin") not in {"auto_apprentissage", "validation_corpus_train"}
        for rule in rules
    )
    assert all(not any(key.startswith("client_") for key in rule) for rule in rules)


def test_pipeline_principal_n_injecte_plus_verite_erp() -> None:
    source = (PROJECT_ROOT / "extraire_informations.py").read_text(encoding="utf-8")
    traitement = source[source.index("def traiter_transcriptions(") :]
    chargement_cadencier = source[
        source.index("def charger_cadencier(") : source.index("def charger_stats_ventes_clients(")
    ]
    assert "appliquer_profils_agressifs(" not in traitement
    assert "_fusionner_historique_cadencier_pretest(" not in chargement_cadencier


def test_filtre_de_regles_est_fail_closed_si_politique_absente(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(evaluation_safety, "POLICY_PATH", tmp_path / "absente.json")
    assert evaluation_safety.filter_prediction_rules(
        [{"origin": "manual_general", "enabled": True}]
    ) == []

