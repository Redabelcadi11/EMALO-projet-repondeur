from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.generer_predictions_evaluation import (
    assert_forbidden_paths_inaccessible,
    validate_manifest,
)
from scripts.preparer_manifest_evaluation import build_manifest
from scripts.transcrire_lot_worker import assert_loopback_endpoint, select_audio_files
from src.evaluation_metrics import aggregate, compare_order


def test_manifest_ne_contient_aucune_verite(tmp_path: Path) -> None:
    audio = "2026-08-12_01-02-03_De-0600000000.wav"
    transcript = tmp_path / f"{Path(audio).stem}__transcription.json"
    transcript.write_text(json.dumps({"texte": "deux cartons de tomates"}))
    corpus = {
        "rows": [
            {
                "audio": audio,
                "split": "final_holdout",
                "truth_order_number": "123456",
                "truth_client": "SECRET",
                "truth_lines": [{"code": "00000001", "quantity": 2}],
            }
        ]
    }
    manifest = build_manifest(corpus, tmp_path)
    serialized = json.dumps(manifest)
    assert "SECRET" not in serialized
    assert "123456" not in serialized
    assert "00000001" not in serialized
    assert set(manifest["rows"][0]) == {"audio", "transcription_sha256"}


def test_predicteur_refuse_un_champ_cible() -> None:
    manifest = {
        "schema": "emalo-evaluation-input/v1",
        "dataset_id": "x",
        "created_at": "now",
        "row_count": 1,
        "rows": [
            {
                "audio": "a.wav",
                "transcription_sha256": "a" * 64,
                "truth_client": "INTERDIT",
            }
        ],
    }
    with pytest.raises(ValueError, match="interdites"):
        validate_manifest(manifest)


def test_predicteur_refuse_un_dossier_verite_lisible(tmp_path: Path) -> None:
    (tmp_path / "truth.json").write_text("{}")
    with pytest.raises(PermissionError, match="source de verite"):
        assert_forbidden_paths_inaccessible([str(tmp_path)])


def test_metrique_stricte_et_diagnostic_quantite() -> None:
    truth = {
        "audio": "a.wav",
        "split": "final_holdout",
        "truth_client": "CLIENT1",
        "truth_delivery_date": "2026-08-13",
        "truth_lines": [
            {"code": "0001", "quantity": "2", "unit": "CAR"},
        ],
    }
    prediction = {
        "audio": "a.wav",
        "client_code": "client1",
        "delivery_date": "2026-08-13",
        "status": "VALIDEE",
        "lines": [{"code": "0001", "quantity": "1", "unit": "carton"}],
        "diagnostics": {"products": []},
    }
    result = compare_order(truth, prediction)
    assert result["code_matches"] == 1
    assert result["exact_matches"] == 0
    assert result["automation_exact"] is False
    assert "quantite" in result["causes"]


def test_metrique_production_exige_client_lignes_date_et_validation() -> None:
    truth = {
        "audio": "a.wav",
        "truth_client": "C1",
        "truth_delivery_date": "2026-08-13",
        "truth_lines": [{"code": "01", "quantity": 1, "unit": "PI"}],
    }
    prediction = {
        "audio": "a.wav",
        "client_code": "C1",
        "delivery_date": "2026-08-13",
        "status": "VALIDEE",
        "lines": [{"code": "01", "quantity": 1, "unit": "PCE"}],
    }
    result = compare_order(truth, prediction)
    metrics = aggregate([result])
    assert result["automation_exact"] is True
    assert metrics["automation_order_accuracy"] == 1.0


def test_lot_transcription_reste_local_et_filtre_les_dates(tmp_path: Path) -> None:
    (tmp_path / "2026-08-12_01-00-00_De-01.wav").write_bytes(b"audio")
    (tmp_path / "2026-08-11_01-00-00_De-01.wav").write_bytes(b"audio")
    selected = select_audio_files(
        tmp_path,
        __import__("datetime").date(2026, 8, 12),
        __import__("datetime").date(2026, 8, 13),
    )
    assert [path.name for path in selected] == ["2026-08-12_01-00-00_De-01.wav"]
    assert_loopback_endpoint("http://127.0.0.1:8787/transcribe")
    with pytest.raises(ValueError, match="boucle locale"):
        assert_loopback_endpoint("http://51.210.2.253:8787/transcribe")
