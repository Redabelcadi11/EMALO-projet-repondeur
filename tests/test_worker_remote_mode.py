from __future__ import annotations

import json

import pytest

import worker_client


def test_remote_required_rejects_missing_instance(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "worker.json"
    config_path.write_text(
        json.dumps(
            {
                "enabled": False,
                "analysis_enabled": True,
                "require_remote": True,
                "url": "",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(worker_client, "CONFIG_PATH", config_path)

    with pytest.raises(RuntimeError, match="nouvelle instance non configuree"):
        worker_client.worker_url()


def test_remote_required_rejects_disabled_analysis(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "worker.json"
    config_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "analysis_enabled": False,
                "require_remote": True,
                "url": "http://127.0.0.1:8787",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(worker_client, "CONFIG_PATH", config_path)

    with pytest.raises(RuntimeError, match="creation de commande distante"):
        worker_client.is_remote_analysis_enabled()
