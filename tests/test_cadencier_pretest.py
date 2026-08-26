from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import pytest

from extraire_informations import _fusionner_historique_cadencier_pretest


def _write_fixture(
    tmp_path: Path,
    *,
    cutoff: str = "2026-06-22",
    audio_from: str = "2026-06-23",
) -> Path:
    csv_path = tmp_path / "historique.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "client_code",
                "client_label",
                "article_code",
                "designation",
                "quantity",
                "unit",
                "order_date",
                "departure_date",
            ],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerow(
            {
                "client_code": "CLIENT1",
                "client_label": "Client test",
                "article_code": "ARTICLE1",
                "designation": "Produit test 1K",
                "quantity": "3",
                "unit": "COL",
                "order_date": "2026-06-20",
                "departure_date": "2026-06-22",
            }
        )
    csv_path.with_suffix(".manifest.json").write_text(
        json.dumps(
            {
                "cutoff_inclusive": cutoff,
                "evaluation_audio_from": audio_from,
                "truth_from_evaluation_included": False,
            }
        ),
        encoding="utf-8",
    )
    return csv_path


def test_historique_pretest_enrichit_cadencier(tmp_path: Path) -> None:
    csv_path = _write_fixture(tmp_path)
    cadencier: defaultdict[str, dict] = defaultdict(dict)

    _fusionner_historique_cadencier_pretest(cadencier, csv_path)

    produit = cadencier["CLIENT1"]["ARTICLE1"]
    assert produit["source_article"] == "historique_client_pretest"
    assert produit["nb_ventes_article_total"] == 1
    assert produit["nb_ventes_article_recentes"] == 1
    assert produit["quantite_habituelle_commande"] == 3.0
    assert produit["unite_vente"] == "COL"


def test_historique_pretest_refuse_fuite_evaluation(tmp_path: Path) -> None:
    csv_path = _write_fixture(
        tmp_path,
        cutoff="2026-06-23",
        audio_from="2026-06-23",
    )

    with pytest.raises(RuntimeError, match="coupure"):
        _fusionner_historique_cadencier_pretest(defaultdict(dict), csv_path)
