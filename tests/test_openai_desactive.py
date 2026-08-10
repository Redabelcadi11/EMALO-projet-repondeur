from __future__ import annotations

import json
from pathlib import Path

from src import openai_arbitrage


def test_configuration_openai_est_desactivee() -> None:
    config_path = Path(__file__).parents[1] / "config" / "openai-recognition.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["enabled"] is False


def test_cle_environnement_ne_peut_pas_reactiver_openai(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "cle-factice-ne-doit-pas-etre-lue")
    assert openai_arbitrage.api_key_available() is False
    assert openai_arbitrage.load_config()["enabled"] is False


def test_arbitrage_reste_desactive_meme_avec_commande_problematique() -> None:
    resultat = openai_arbitrage.arbitrer_commande(
        {"statut": "PROBLEMATIQUE", "transcription": "donnees privees"}
    )
    assert resultat == {
        "enabled": False,
        "api_key_available": False,
        "applied": False,
        "skipped": "traitement_exclusivement_sur_instance_locale",
    }


def test_fonction_reseau_est_verrouillee() -> None:
    try:
        openai_arbitrage._call_openai({}, {})
    except RuntimeError as exc:
        assert "desactivee" in str(exc)
    else:
        raise AssertionError("La fonction reseau OpenAI aurait du etre verrouillee")


def test_pipeline_principal_n_importe_plus_arbitre_openai() -> None:
    source = (Path(__file__).parents[1] / "extraire_informations.py").read_text(
        encoding="utf-8"
    )
    assert "from src.openai_arbitrage import arbitrer_commande" not in source
    assert "traitement_exclusivement_sur_instance_locale" in source
