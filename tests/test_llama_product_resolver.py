from __future__ import annotations

import io
import json

import pytest

from src.llama_product_resolver import (
    LlamaResolverError,
    _call_ollama_json,
    _limited_response_schema,
    assert_no_target_data,
    build_authorized_catalogue,
    select_authorized_catalogue,
    validate_llama_lines,
)
from scripts.arbitrer_predictions_llama_local import (
    _focused_transcription_for_queries,
    _normalise_cadencier_par_client,
    _products_for_queries,
)


def _catalogue():
    return {
        "A1": {
            "code": "A1",
            "label": "CREME UHT 35% 6X1L",
            "unit": "PACK",
            "capacity_per_order_unit": 6.0,
            "capacity_unit": "L",
            "variable_weight": False,
        }
    }


@pytest.mark.parametrize(
    "key",
    ["truth_lines", "truth_order_number", "commande_reelle", "ground_truth"],
)
def test_target_keys_are_rejected_before_prompt(key):
    with pytest.raises(LlamaResolverError, match="cible interdite"):
        assert_no_target_data({"safe": {key: []}})


def test_authorized_catalogue_marks_only_existing_client_history():
    global_catalogue = [
        {"code_article": "A1", "libelle_article": "CREME UHT", "unite_vente": ""},
        {"code_article": "A2", "libelle_article": "PIQUILLOS", "unite_vente": "BOITE"},
    ]
    client_products = [
        {
            "code_article": "A1",
            "libelle_article": "CREME UHT",
            "nb_ventes_article_total": 3,
            "nb_ventes_article_recentes": 2,
            "quantite_habituelle_commande": 1,
        }
    ]
    references = {
        "A1": {"label": "CREME UHT", "order_unit": "PACK", "pack_size": 6},
        "A3": {"label": "CHIPIRON PATAGONIE", "order_unit": "COL"},
    }
    result = build_authorized_catalogue(global_catalogue, client_products, references)
    assert result["A1"]["unit"] == "PACK"
    assert result["A1"]["in_client_history"] is True
    assert result["A1"]["history_sales"] == 3
    assert result["A2"]["in_client_history"] is False
    assert result["A3"]["label"] == "CHIPIRON PATAGONIE"


def test_authorized_catalogue_uses_explicit_outer_pack_capacity():
    references = {
        "CREME": {
            "label": "CREME UHT 35% HELIOR 6X1L",
            "order_unit": "PACK",
            "pack_size": 6.0,
            "average_weight": 1.03,
            "base_unit_source": "LIT",
            "order_unit_source": "PAC",
            "billing_unit_source": "LIT",
        },
        "GLACE": {
            "label": "GLACON 2K X5P",
            "order_unit": "COL",
            "pack_size": 5.0,
            "average_weight": 2.0,
            "base_unit_source": "POC",
            "order_unit_source": "COL",
        },
    }
    result = build_authorized_catalogue([], [], references)
    assert result["CREME"]["capacity_per_order_unit"] == 6.0
    assert result["CREME"]["capacity_unit"] == "L"
    assert result["GLACE"]["capacity_per_order_unit"] == 10.0
    assert result["GLACE"]["capacity_unit"] == "KG"


def test_retrieval_can_find_reference_absent_from_initial_candidates():
    catalogue = {
        f"X{index:03d}": {
            "code": f"X{index:03d}",
            "label": f"PRODUIT GENERIQUE {index}",
            "unit": "PI",
            "in_client_history": False,
            "history_sales": 0,
        }
        for index in range(80)
    }
    catalogue["CIBLE"] = {
        "code": "CIBLE",
        "label": "CHIPIRON PATAGONIE NETTOYE",
        "unit": "COL",
        "in_client_history": False,
        "history_sales": 0,
    }
    selected = select_authorized_catalogue(
        catalogue,
        transcription="Il me faudrait deux cartons de chipiron de Patagonie.",
        deterministic_products=[
            {
                "texte_source": "deux cartons de chipiron de Patagonie",
                "produit_normalise": "chipiron patagonie",
                "candidats": [],
            }
        ],
        maximum_items=50,
        fuzzy_per_query=10,
    )
    assert "CIBLE" in selected


def test_additional_llama_query_can_recover_phonetically_unrelated_reference():
    catalogue = {
        f"X{index:03d}": {
            "code": f"X{index:03d}",
            "label": f"PRODUIT GENERIQUE {index}",
            "unit": "PI",
            "in_client_history": False,
            "history_sales": 0,
        }
        for index in range(80)
    }
    catalogue["CIBLE"] = {
        "code": "CIBLE",
        "label": "FARINE BLEUE W330 CINQ STAGIONI",
        "unit": "SAC",
        "in_client_history": False,
        "history_sales": 0,
    }
    selected = select_authorized_catalogue(
        catalogue,
        transcription="Je prendrai six tas de jaunis bleus.",
        deterministic_products=[],
        additional_queries=["farine bleue w330 cinq stagioni"],
        maximum_items=50,
        fuzzy_per_query=10,
    )
    assert "CIBLE" in selected


def test_validated_line_must_use_catalogue_code_unit_quantity_and_evidence():
    response = {
        "lines": [
            {
                "source_text": "douze litres de creme trente cinq pour cent",
                "code": "A1",
                "quantity": 2,
                "unit": "PACK",
                "confidence": 0.94,
                "reason": "12 L = 2 packs de 6 L",
            }
        ],
        "rejected_fragments": [],
    }
    lines, rejected = validate_llama_lines(
        response,
        transcription="Il me faudrait douze litres de creme trente cinq pour cent.",
        catalogue=_catalogue(),
    )
    assert not rejected
    assert lines == [
        {
            "code": "A1",
            "quantity": 2.0,
            "unit": "PACK",
            "label": "CREME UHT 35% 6X1L",
            "source_text": "douze litres de creme trente cinq pour cent",
            "confidence": 0.94,
            "reason": "12 L = 2 packs de 6 L",
            "quantity_resolution": "mesure_l_divisee_par_capacite_officielle",
            "unit_resolution": "llama_unit",
        }
    ]


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"code": "INVENTE"}, "code_hors_catalogue_autorise"),
        ({"quantity": 0}, "quantite_invalide"),
        ({"source_text": "produit jamais prononce"}, "preuve_absente_transcription"),
    ],
)
def test_invalid_llama_line_is_rejected(changes, reason):
    line = {
        "source_text": "deux packs de creme",
        "code": "A1",
        "quantity": 2,
        "unit": "PACK",
        "confidence": 0.9,
        "reason": "",
    }
    line.update(changes)
    accepted, rejected = validate_llama_lines(
        {"lines": [line], "rejected_fragments": []},
        transcription="Je voudrais deux packs de creme.",
        catalogue=_catalogue(),
    )
    assert not accepted
    assert reason in rejected[0]["reason"]


def test_catalogue_unit_overrides_llama_unit_instead_of_rejecting_line():
    line = {
        "source_text": "deux packs de creme",
        "code": "A1",
        "quantity": 2,
        "unit": "PI",
        "confidence": 0.9,
    }
    accepted, rejected = validate_llama_lines(
        {"lines": [line], "rejected_fragments": []},
        transcription="Je voudrais deux packs de creme.",
        catalogue=_catalogue(),
    )
    assert not rejected
    assert accepted[0]["unit"] == "PACK"
    assert accepted[0]["unit_resolution"] == "catalogue_officiel"


def test_explicit_outer_container_count_has_priority_over_inner_capacity():
    catalogue = {
        "HUILE": {
            "code": "HUILE",
            "label": "HUILE DE SOJA BIDON 10L",
            "unit": "BID",
            "capacity_per_order_unit": 10.0,
            "capacity_unit": "L",
            "variable_weight": False,
        }
    }
    response = {
        "lines": [
            {
                "source_text": "deux bidons d huile de soja de 10 litres",
                "code": "HUILE",
                "quantity": 1,
                "unit": "PCE",
                "confidence": 0.9,
            }
        ],
        "rejected_fragments": [],
    }
    lines, rejected = validate_llama_lines(
        response,
        transcription="Il me faut deux bidons d huile de soja de 10 litres.",
        catalogue=catalogue,
    )
    assert not rejected
    assert lines[0]["quantity"] == 2
    assert lines[0]["unit"] == "BID"
    assert lines[0]["quantity_resolution"] == "nombre_bidons_explicite"


def test_llama_cannot_invent_quantity_from_client_history():
    response = {
        "lines": [
            {
                "source_text": "jaune d oeuf",
                "code": "A1",
                "quantity": 3,
                "unit": "PACK",
                "confidence": 0.9,
            }
        ],
        "rejected_fragments": [],
    }
    accepted, rejected = validate_llama_lines(
        response,
        transcription="Je voudrais aussi du jaune d oeuf.",
        catalogue=_catalogue(),
    )
    assert not accepted
    assert "quantite_non_prouvee_transcription" in rejected[0]["reason"]


def test_line_outside_batch_queries_is_rejected():
    response = {
        "lines": [
            {
                "source_text": "deux packs de creme",
                "code": "A1",
                "quantity": 2,
                "unit": "PACK",
                "confidence": 0.9,
            }
        ],
        "rejected_fragments": [],
    }
    accepted, rejected = validate_llama_lines(
        response,
        transcription="Deux packs de creme.",
        catalogue=_catalogue(),
        allowed_queries=[{"normalized_query": "tomates concassees"}],
    )
    assert not accepted
    assert "produit_hors_perimetre_du_lot" in rejected[0]["reason"]


def test_batch_schema_is_bounded_by_query_count():
    schema = _limited_response_schema(4)
    assert schema["properties"]["lines"]["maxItems"] == 4
    assert schema["properties"]["rejected_fragments"]["maxItems"] == 4


def test_invalid_json_is_retried_with_more_generation_budget(monkeypatch):
    responses = [
        {"response": '{"lines":[', "done_reason": "length"},
        {"response": '{"lines":[],"rejected_fragments":[]}'},
    ]
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data.decode("utf-8")))
        return io.BytesIO(json.dumps(responses.pop(0)).encode("utf-8"))

    monkeypatch.setattr(
        "src.llama_product_resolver.llama_model_info",
        lambda: {"context_length": 8192, "digest": "test"},
    )
    monkeypatch.setattr(
        "src.llama_product_resolver.urllib.request.urlopen",
        fake_urlopen,
    )
    result, telemetry = _call_ollama_json("prompt", num_predict=32)

    assert result == {"lines": [], "rejected_fragments": []}
    assert [item["options"]["num_predict"] for item in requests] == [32, 64]
    assert [item["status"] for item in telemetry["attempts"]] == [
        "invalid_json",
        "ok",
    ]


def test_focused_transcription_excludes_unrelated_order_clauses():
    transcription = (
        "Bonjour pour le restaurant. "
        "Il me faut deux bidons d huile de soja. "
        "Ajoutez aussi trois cartons de fraises. Merci."
    )
    focused = _focused_transcription_for_queries(
        transcription,
        [{"normalized_query": "huile de soja"}],
        [{"texte_source": "deux bidons d huile de soja"}],
    )
    assert "huile de soja" in focused
    assert "cartons de fraises" not in focused
    assert "Bonjour pour le restaurant" not in focused


def test_unrelated_deterministic_products_do_not_pollute_batch():
    products = [
        {"produit_normalise": "creme liquide"},
        {"produit_normalise": "fraises surgelees"},
    ]
    assert _products_for_queries(
        products,
        [{"normalized_query": "huile de soja"}],
    ) == []


def test_identical_duplicate_is_not_summed():
    line = {
        "source_text": "deux packs de creme",
        "code": "A1",
        "quantity": 2,
        "unit": "PACK",
        "confidence": 0.9,
        "reason": "repetition",
    }
    accepted, rejected = validate_llama_lines(
        {"lines": [line, dict(line)], "rejected_fragments": []},
        transcription="Deux packs de creme, deux packs de creme.",
        catalogue=_catalogue(),
    )
    assert not rejected
    assert accepted[0]["quantity"] == 2


def test_weight_is_recomputed_from_official_outer_pack_capacity():
    catalogue = {
        "ICE": {
            "code": "ICE",
            "label": "GLACON 2K X5P",
            "unit": "COL",
            "pack_size": 5.0,
            "average_weight": 2.0,
            "capacity_per_order_unit": 10.0,
            "capacity_unit": "KG",
            "variable_weight": False,
        }
    }
    response = {
        "lines": [
            {
                "source_text": "20 kilos de glacons",
                "code": "ICE",
                "quantity": 10,
                "unit": "COL",
                "confidence": 0.8,
            }
        ],
        "rejected_fragments": [],
    }
    lines, rejected = validate_llama_lines(
        response,
        transcription="Il me faudrait 20 kilos de glacons.",
        catalogue=catalogue,
    )
    assert not rejected
    assert lines[0]["quantity"] == 2
    assert lines[0]["quantity_resolution"].startswith("mesure_kg_")


@pytest.mark.parametrize(
    "source,llama_quantity,expected",
    [
        ("6x1l de lait", 6, 1),
        ("deux packs de 6x1l de lait", 6, 2),
    ],
)
def test_spoken_packaging_equal_to_reference_is_an_order_unit(
    source, llama_quantity, expected
):
    response = {
        "lines": [
            {
                "source_text": source,
                "code": "A1",
                "quantity": llama_quantity,
                "unit": "PACK",
                "confidence": 0.9,
            }
        ],
        "rejected_fragments": [],
    }
    lines, rejected = validate_llama_lines(
        response,
        transcription=f"Je voudrais {source}.",
        catalogue=_catalogue(),
    )
    assert not rejected
    assert lines[0]["quantity"] == expected
    assert lines[0]["quantity_resolution"] in {
        "conditionnement_explicite_identique_au_referentiel",
        "nombre_packs_explicite",
    }


def test_cadencier_llama_aligne_les_codes_client_sans_casse() -> None:
    produit_a = {"code_article": "A", "libelle_article": "ARTICLE A"}
    produit_b = {"code_article": "B", "libelle_article": "ARTICLE B"}
    normalise = _normalise_cadencier_par_client(
        {
            "XIPIRONANGLET": [produit_a],
            "xipironanglet": [produit_a, produit_b],
        }
    )

    assert set(normalise) == {"xipironanglet"}
    assert [item["code_article"] for item in normalise["xipironanglet"]] == [
        "A",
        "B",
    ]
