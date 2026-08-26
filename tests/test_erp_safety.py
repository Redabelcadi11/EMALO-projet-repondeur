from __future__ import annotations

import json
from pathlib import Path

import pytest

import copilote_integration as copilote
from src import erp_safety


PROJECT_ROOT = Path(__file__).parents[1]


def test_politique_courante_autorise_les_lectures_et_bloque_les_ecritures() -> None:
    status = erp_safety.erp_safety_status()
    assert status.policy_valid is True
    assert status.mode == "evaluation"
    assert status.evaluation_lock is True
    assert status.reads_allowed is True
    assert status.writes_allowed is False
    erp_safety.assert_erp_read_allowed("test lecture locale")
    with pytest.raises(erp_safety.ERPWriteBlocked, match="ERP_WRITE_BLOCKED"):
        erp_safety.assert_erp_write_allowed("test ecriture interdite")


def test_politique_absente_echoue_en_mode_ferme(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "politique-absente.json"
    monkeypatch.setattr(erp_safety, "DEFAULT_POLICY_PATH", missing)
    status = erp_safety.erp_safety_status()
    assert status.policy_valid is False
    assert status.evaluation_lock is True
    assert status.writes_allowed is False
    with pytest.raises(erp_safety.ERPWriteBlocked, match="politique absente"):
        erp_safety.assert_erp_write_allowed("test politique absente")


def test_variables_environnement_ne_contournent_pas_le_verrou_evaluation(monkeypatch) -> None:
    monkeypatch.setenv("REPONDEUR_ERP_MODE", "production")
    monkeypatch.setenv(
        "REPONDEUR_ERP_WRITE_CONFIRMATION",
        "J_AUTORISE_EXPLICITEMENT_LES_ECRITURES_ERP",
    )
    status = erp_safety.erp_safety_status()
    assert status.evaluation_lock is True
    assert status.writes_allowed is False


def test_reactivation_exige_une_politique_production_et_confirmation(tmp_path, monkeypatch) -> None:
    policy_path = tmp_path / "erp-safety.json"
    policy_path.write_text(
        json.dumps(
            {
                "mode": "production",
                "evaluation_lock": False,
                "allow_erp_reads": True,
                "allow_erp_writes": True,
                "write_confirmation_env": "TEST_ERP_CONFIRMATION",
                "write_confirmation_value": "confirmation-factice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(erp_safety, "DEFAULT_POLICY_PATH", policy_path)
    assert erp_safety.erp_safety_status().writes_allowed is False
    monkeypatch.setenv("TEST_ERP_CONFIRMATION", "confirmation-factice")
    assert erp_safety.erp_safety_status().writes_allowed is True


def test_implementations_python_bloquent_avant_reseau_ou_sous_processus(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Un acces externe ERP a ete tente pendant le test")

    monkeypatch.setattr(copilote.subprocess, "run", forbidden)
    monkeypatch.setattr(copilote.http.client, "HTTPConnection", forbidden)

    with pytest.raises(erp_safety.ERPWriteBlocked, match="ERP_WRITE_BLOCKED"):
        copilote.send_service_request("TEST-BLOQUE", [])
    with pytest.raises(erp_safety.ERPWriteBlocked, match="ERP_WRITE_BLOCKED"):
        copilote.send_direct_request("TEST-BLOQUE", [])
    with pytest.raises(erp_safety.ERPWriteBlocked, match="ERP_WRITE_BLOCKED"):
        copilote.acquire_send_lock()


def test_automatisation_playwright_verrouille_toutes_les_etapes_mutantes() -> None:
    source = (PROJECT_ROOT / "scripts" / "copilote_order.py").read_text(encoding="utf-8")
    for function_name in (
        "create_order_for_client",
        "fill_general_information",
        "open_articles_step",
        "enter_article_line",
        "save_order",
    ):
        start = source.index(f"def {function_name}(")
        next_function = source.find("\ndef ", start + 1)
        block = source[start : next_function if next_function >= 0 else len(source)]
        assert "assert_erp_write_allowed(" in block


def test_scripts_groovy_mutants_appellent_le_garde_avant_le_service_erp() -> None:
    cases = {
        "send_order_service.groovy": ("assertErpWriteAllowed", "new RemoteServiceFactoryImpl"),
        "probe_line_quantities.groovy": ("assertErpWriteAllowed", "new RemoteServiceFactoryImpl"),
    }
    for name, (guard_marker, external_marker) in cases.items():
        source = (PROJECT_ROOT / "copilote" / name).read_text(encoding="utf-8")
        assert source.index(guard_marker) < source.index(external_marker)


def test_extracteur_erp_reste_strictement_en_lecture() -> None:
    source = (PROJECT_ROOT / "copilote" / "extract_repondeur_orders.groovy").read_text(
        encoding="utf-8"
    )
    assert "saveCdeBatch" not in source
    assert "CommandeService) factory.getService(CommandeService.ROLE)).create(" not in source
    assert ".loadNumCde(" in source
    assert "tableauService.execute2(" in source
