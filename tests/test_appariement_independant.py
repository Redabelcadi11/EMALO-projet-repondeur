from __future__ import annotations

from pathlib import Path

from scripts.apparier_audio_commandes_independant import (
    build_corpus,
    build_edges,
    classify_edges,
    rank_edges,
    select_assignments,
)


def test_appariement_metadata_exact_sans_prediction_programme() -> None:
    audios = [
        {
            "audio": "2026-08-13_01-00-00_De-0600000001.wav",
            "date": "2026-08-13",
            "phone": "0600000001",
            "transcription": "Restaurant Alpha, deux cartons de tomates concassees",
            "transcription_sha256": "a" * 64,
        }
    ]
    orders = [
        {
            "order_number": "100",
            "client_code": "ALPHA",
            "client_label": "RESTAURANT ALPHA",
            "order_date": "2026-08-13",
            "delivery_date": "2026-08-13",
            "lines": [
                {
                    "code": "0001",
                    "label": "TOMATE CONCASSEE 5/1",
                    "quantity": "2",
                    "unit": "BOITE",
                }
            ],
            "has_error": False,
        }
    ]
    clients = {
        "ALPHA": {
            "code": "ALPHA",
            "labels": {"RESTAURANT ALPHA"},
            "cities": set(),
            "aliases": set(),
        }
    }
    phones = {"0600000001": {"ALPHA"}}
    edges = build_edges(audios, orders, clients, phones)
    rank_edges(edges)
    classify_edges(edges, audios, orders, phones)
    assignments = select_assignments(edges)
    assert len(assignments) == 1
    assert assignments[0]["confidence_class"] == "metadata_exact"
    corpus = build_corpus(assignments, orders, audios, final_size=1)
    assert corpus["matching_uses_program_product_predictions"] is False
    assert corpus["rows"][0]["split"] == "final_holdout"


def test_apparieur_n_importe_ni_sorties_ni_moteur_principal() -> None:
    source = (
        Path(__file__).parents[1]
        / "scripts"
        / "apparier_audio_commandes_independant.py"
    ).read_text(encoding="utf-8")
    assert "extraire_informations" not in source
    assert "resultats/extractions" not in source
    assert "global-program-predictions" not in source
