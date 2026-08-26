#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llama_product_resolver import (
    LLAMA_MODEL,
    LlamaSafetyError,
    build_authorized_catalogue,
    expand_product_queries,
    llama_model_info,
    resolve_order_products,
    select_authorized_catalogue,
    consolidate_validated_lines,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def assert_forbidden_paths_inaccessible(paths: list[str]) -> None:
    for raw in paths:
        path = Path(raw)
        try:
            if path.is_dir():
                next(path.iterdir(), None)
            else:
                with path.open("rb") as handle:
                    handle.read(1)
        except (FileNotFoundError, PermissionError, OSError):
            continue
        raise PermissionError(
            f"Le processus Llama peut lire une verite cible interdite: {path}"
        )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Objet JSON attendu: {path}")
    return value


def _resolver_fingerprint(base_fingerprint: str) -> str:
    digest = hashlib.sha256(base_fingerprint.encode("utf-8"))
    for relative in (
        "src/llama_product_resolver.py",
        "scripts/arbitrer_predictions_llama_local.py",
        "config/evaluation-safety.json",
        "config/erp-safety.json",
    ):
        path = PROJECT_ROOT / relative
        digest.update(relative.encode("utf-8"))
        digest.update(_sha256(path).encode("ascii"))
    return digest.hexdigest()


def _load_references() -> dict[str, dict[str, Any]]:
    payload = _load_json(PROJECT_ROOT / "config" / "references-articles-controle.json")
    references = payload.get("references")
    if not isinstance(references, dict):
        raise ValueError("Referentiel de conditionnement invalide.")
    return {
        str(code): value
        for code, value in references.items()
        if isinstance(value, dict)
    }


def _normalise_cadencier_par_client(
    cadencier: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Aligne les clés client sur les codes normalisés des prédictions.

    Les fichiers historiques utilisent des codes en majuscules alors que le
    pipeline d'évaluation expose des codes en minuscules. Sans cette étape,
    le Llama recevait un catalogue global mais aucun historique client.
    """
    normalise: dict[str, list[dict[str, Any]]] = {}
    codes_vus: dict[str, set[str]] = {}
    for client_brut, produits in cadencier.items():
        client = str(client_brut or "").strip().casefold()
        if not client:
            continue
        destination = normalise.setdefault(client, [])
        vus = codes_vus.setdefault(client, set())
        for produit in produits:
            code = str(produit.get("code_article") or "").strip()
            if code and code in vus:
                continue
            destination.append(produit)
            if code:
                vus.add(code)
    return normalise


def _load_resources() -> tuple[
    dict[str, list[dict[str, Any]]], list[dict[str, Any]], dict[str, dict[str, Any]]
]:
    import extraire_informations as extraction

    cadencier = _normalise_cadencier_par_client(
        extraction.charger_cadencier()
    )
    units = extraction.charger_unites_articles()
    for products in cadencier.values():
        for product in products:
            product["unite_vente"] = units.get(
                str(product.get("code_article") or ""), ""
            )
    articles = extraction.charger_catalogue_articles_reference()
    for article in articles:
        article["unite_vente"] = units.get(
            str(article.get("code_article") or ""), ""
        )
    global_catalogue = extraction.construire_catalogue_global(
        cadencier, articles_reference=articles
    )
    return cadencier, global_catalogue, _load_references()


def _checkpoint_payload(
    *,
    base_sha256: str,
    resolver_fingerprint: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "emalo-llama-evaluation-checkpoint/v1",
        "base_predictions_sha256": base_sha256,
        "resolver_fingerprint": resolver_fingerprint,
        "truth_received_by_predictor": False,
        "erp_write_attempted": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "rows": rows,
    }


def _normalise_for_match(value: Any) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _products_for_queries(
    products: list[dict[str, Any]], queries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    selected_indices: set[int] = set()
    searchable = [
        _normalise_for_match(
            product.get("produit_normalise")
            or product.get("texte_produit")
            or product.get("texte_source")
        )
        for product in products
    ]
    for query_item in queries:
        query = _normalise_for_match(query_item.get("normalized_query"))
        ranked = sorted(
            (
                (index, float(fuzz.WRatio(query, searchable[index])))
                for index in range(len(products))
                if query and searchable[index]
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        selected_indices.update(
            index for index, score in ranked[:2] if score >= 42.0
        )
    return [products[index] for index in sorted(selected_indices)]


def _transcription_chunks(
    transcription: str,
    *,
    window_words: int = 42,
    overlap_words: int = 14,
) -> list[str]:
    """Build faithful, bounded clauses without asking a model to rewrite evidence."""
    import re

    text = str(transcription or "").strip()
    if not text:
        return []
    clauses = [
        clause.strip()
        for clause in re.split(r"(?<=[.!?;:])\s+|[,;\n]+", text)
        if clause.strip()
    ]
    chunks: list[str] = []
    for clause in clauses:
        words = list(re.finditer(r"\S+", clause))
        if len(words) <= window_words:
            chunks.append(clause)
            continue
        step = max(1, window_words - overlap_words)
        for start in range(0, len(words), step):
            end = min(len(words), start + window_words)
            chunks.append(clause[words[start].start() : words[end - 1].end()])
            if end == len(words):
                break
    return chunks or [text]


def _focused_transcription_for_queries(
    transcription: str,
    queries: list[dict[str, Any]],
    related_products: list[dict[str, Any]],
    *,
    maximum_characters: int = 2_400,
) -> str:
    """Keep only original clauses that can prove the current product batch."""
    chunks = _transcription_chunks(transcription)
    if not chunks:
        return ""
    normalised_chunks = [_normalise_for_match(chunk) for chunk in chunks]
    selected_scores: dict[int, float] = {}

    def retain_best(needle: str) -> None:
        query = _normalise_for_match(needle)
        if not query:
            return
        ranked = sorted(
            (
                (
                    index,
                    max(
                        float(fuzz.WRatio(query, chunk)),
                        float(fuzz.partial_ratio(query, chunk)),
                        float(fuzz.token_set_ratio(query, chunk)),
                    ),
                )
                for index, chunk in enumerate(normalised_chunks)
                if chunk
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        if not ranked:
            return
        index, score = ranked[0]
        selected_scores[index] = max(selected_scores.get(index, 0.0), score)

    for item in queries:
        retain_best(str(item.get("normalized_query") or ""))
    for product in related_products:
        retain_best(
            str(
                product.get("texte_source")
                or product.get("texte_produit")
                or product.get("produit_normalise")
                or ""
            )
        )

    # Limit prompt size by relevance, then restore the original spoken order.
    retained = sorted(
        sorted(selected_scores, key=selected_scores.get, reverse=True)[:12]
    )
    focused: list[str] = []
    current_size = 0
    for index in retained:
        chunk = chunks[index]
        added = len(chunk) + (3 if focused else 0)
        if focused and current_size + added > maximum_characters:
            continue
        focused.append(chunk)
        current_size += added
    return " ; ".join(focused) if focused else chunks[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Arbitre les produits avec le Llama local et un catalogue autorise, "
            "sans jamais recevoir la verite ERP cible."
        )
    )
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--forbidden-path", action="append", default=[])
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--minimum-line-confidence", type=float, default=0.35)
    parser.add_argument("--validation-confidence", type=float, default=0.80)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--maximum-catalogue-items", type=int, default=512)
    parser.add_argument("--expansion-only", action="store_true")
    parser.add_argument("--reuse-expansions", type=Path)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--batch-catalogue-items", type=int, default=64)
    parser.add_argument("--audio", action="append", default=[])
    args = parser.parse_args()

    assert_forbidden_paths_inaccessible(args.forbidden_path)
    base_sha256 = _sha256(args.predictions)
    base = _load_json(args.predictions)
    if base.get("schema") != "emalo-evaluation-predictions/v1":
        raise ValueError("Schema de predictions de base invalide.")
    if base.get("truth_received_by_predictor") is not False:
        raise RuntimeError("La prediction de base ne certifie pas l'absence de cible.")
    if base.get("erp_write_attempted") is not False:
        raise RuntimeError("Une tentative d'ecriture ERP est signalee dans la base.")

    fingerprint = _resolver_fingerprint(str(base.get("application_fingerprint") or ""))
    model_info = llama_model_info()
    cadencier, global_catalogue, references = _load_resources()
    reusable_expansions: dict[str, dict[str, Any]] = {}
    if args.reuse_expansions:
        reusable = _load_json(args.reuse_expansions)
        if reusable.get("schema") != "emalo-evaluation-predictions/v1":
            raise ValueError("Schema du fichier de normalisations invalide.")
        if (
            reusable.get("truth_received_by_predictor") is not False
            or reusable.get("erp_write_attempted") is not False
            or reusable.get("base_predictions_sha256") != base_sha256
        ):
            raise RuntimeError("Normalisations reutilisables non certifiees.")
        for reusable_row in reusable.get("rows") or []:
            expansion = (
                reusable_row.get("diagnostics", {}).get("llama_query_expansion")
            )
            if isinstance(expansion, dict) and isinstance(expansion.get("items"), list):
                reusable_expansions[str(reusable_row.get("audio") or "")] = expansion
    checkpoint_path = args.checkpoint or args.output.with_suffix(
        args.output.suffix + ".checkpoint.json"
    )
    completed_rows: list[dict[str, Any]] = []
    if checkpoint_path.is_file():
        checkpoint = _load_json(checkpoint_path)
        if (
            checkpoint.get("schema") == "emalo-llama-evaluation-checkpoint/v1"
            and checkpoint.get("base_predictions_sha256") == base_sha256
            and checkpoint.get("resolver_fingerprint") == fingerprint
            and checkpoint.get("truth_received_by_predictor") is False
            and checkpoint.get("erp_write_attempted") is False
        ):
            completed_rows = list(checkpoint.get("rows") or [])
    completed_audio = {str(row.get("audio") or "") for row in completed_rows}

    selected_rows = list(base.get("rows") or [])
    selected_audio = {str(value) for value in args.audio if str(value)}
    if selected_audio:
        selected_rows = [
            row
            for row in selected_rows
            if str(row.get("audio") or "") in selected_audio
        ]
        missing_audio = selected_audio - {
            str(row.get("audio") or "") for row in selected_rows
        }
        if missing_audio:
            raise ValueError(f"Audios absents des predictions: {sorted(missing_audio)}")
    if args.max_rows > 0:
        selected_rows = selected_rows[: args.max_rows]
    started = time.perf_counter()
    for base_row in selected_rows:
        audio = str(base_row.get("audio") or "")
        if audio in completed_audio:
            continue
        row = json.loads(json.dumps(base_row, ensure_ascii=False))
        diagnostics = row.setdefault("diagnostics", {})
        try:
            client_code = str(row.get("client_code") or "")
            client_lookup_code = client_code.strip().casefold()
            full_catalogue = build_authorized_catalogue(
                global_catalogue,
                cadencier.get(client_lookup_code, []),
                references,
            )
            client_catalogue = {
                code: item
                for code, item in full_catalogue.items()
                if item.get("in_client_history")
            }
            expansion = reusable_expansions.get(audio)
            if expansion is None:
                expansion = expand_product_queries(
                    transcription=str(row.get("transcription") or ""),
                    client_code=client_code,
                    client_name=str(row.get("client_name") or ""),
                    client_catalogue=client_catalogue,
                    deterministic_products=list(diagnostics.get("products") or []),
                    timeout_seconds=args.timeout_seconds,
                )
            if args.expansion_only:
                catalogue = select_authorized_catalogue(
                    full_catalogue,
                    transcription=str(row.get("transcription") or ""),
                    deterministic_products=list(diagnostics.get("products") or []),
                    additional_queries=[
                        str(item.get("normalized_query") or "")
                        for item in expansion["items"]
                    ],
                    maximum_items=args.maximum_catalogue_items,
                )
                resolution = {
                    "lines": [],
                    "validation_rejections": [],
                    "model_rejected_fragments": [],
                    "telemetry": {},
                }
            else:
                all_lines: list[dict[str, Any]] = []
                all_validation_rejections: list[dict[str, Any]] = []
                all_model_rejections: list[Any] = []
                batch_diagnostics: list[dict[str, Any]] = []
                batch_errors: list[dict[str, Any]] = []
                retrieval_codes: set[str] = set()
                batch_size = max(1, int(args.batch_size))
                expansion_items = list(expansion["items"])
                full_transcription = str(row.get("transcription") or "")
                for batch_index, offset in enumerate(
                    range(0, len(expansion_items), batch_size), 1
                ):
                    batch_queries = expansion_items[offset : offset + batch_size]
                    related_products = _products_for_queries(
                        list(diagnostics.get("products") or []), batch_queries
                    )
                    focused_transcription = _focused_transcription_for_queries(
                        full_transcription,
                        batch_queries,
                        related_products,
                    )
                    batch_catalogue = select_authorized_catalogue(
                        full_catalogue,
                        transcription="",
                        deterministic_products=related_products,
                        additional_queries=[
                            str(item.get("normalized_query") or "")
                            for item in batch_queries
                        ],
                        maximum_items=args.batch_catalogue_items,
                        prefer_query_candidates=True,
                    )
                    retrieval_codes.update(batch_catalogue)
                    try:
                        batch_resolution = resolve_order_products(
                            transcription=focused_transcription,
                            client_code=client_code,
                            client_name=str(row.get("client_name") or ""),
                            catalogue=batch_catalogue,
                            deterministic_products=related_products,
                            query_expansions=batch_queries,
                            scope_queries_only=True,
                            minimum_line_confidence=args.minimum_line_confidence,
                            timeout_seconds=args.timeout_seconds,
                        )
                    except LlamaSafetyError:
                        raise
                    except Exception as exc:
                        batch_errors.append(
                            {
                                "batch": batch_index,
                                "queries": batch_queries,
                                "error": f"{type(exc).__name__}:{exc}",
                            }
                        )
                        print(
                            json.dumps(
                                {
                                    "audio": audio,
                                    "batch": batch_index,
                                    "error": f"{type(exc).__name__}:{exc}",
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                        continue
                    all_lines.extend(batch_resolution["lines"])
                    all_validation_rejections.extend(
                        batch_resolution["validation_rejections"]
                    )
                    all_model_rejections.extend(
                        batch_resolution["model_rejected_fragments"]
                    )
                    batch_diagnostics.append(
                        {
                            "batch": batch_index,
                            "queries": batch_queries,
                            "focused_transcription": focused_transcription,
                            "catalogue_count": len(batch_catalogue),
                            "line_count": len(batch_resolution["lines"]),
                            "telemetry": batch_resolution["telemetry"],
                        }
                    )
                    print(
                        json.dumps(
                            {
                                "audio": audio,
                                "batch": batch_index,
                                "batches": (
                                    len(expansion_items) + batch_size - 1
                                ) // batch_size,
                                "lines": len(batch_resolution["lines"]),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                catalogue = {
                    code: full_catalogue[code]
                    for code in retrieval_codes
                    if code in full_catalogue
                }
                resolution = {
                    "lines": consolidate_validated_lines(all_lines),
                    "validation_rejections": all_validation_rejections,
                    "model_rejected_fragments": all_model_rejections,
                    "telemetry": {"batches": batch_diagnostics},
                    "batch_errors": batch_errors,
                }
            lines = resolution["lines"]
            if not args.expansion_only:
                row["lines"] = [
                    {
                        "code": line["code"],
                        "quantity": line["quantity"],
                        "unit": line["unit"],
                        "label": line["label"],
                        "source_text": line["source_text"],
                    }
                    for line in lines
                ]
            reliable = bool(lines) and all(
                float(line.get("confidence") or 0.0) >= args.validation_confidence
                for line in lines
            )
            row["status"] = row.get("status") if args.expansion_only else (
                "VALIDEE"
                if reliable
                and bool(row.get("client_code"))
                and bool(row.get("delivery_date"))
                and not resolution["validation_rejections"]
                and not resolution.get("batch_errors")
                else "PROBLEMATIQUE"
            )
            diagnostics["llama_resolution"] = resolution
            diagnostics["llama_query_expansion"] = expansion
            diagnostics["llama_retrieval_codes"] = list(catalogue)
            diagnostics["llama_resolution"]["catalogue_count"] = len(catalogue)
            diagnostics["llama_resolution"]["full_catalogue_count"] = len(
                full_catalogue
            )
            diagnostics["llama_resolution"]["fallback_used"] = False
        except LlamaSafetyError:
            raise
        except Exception as exc:
            diagnostics["llama_resolution"] = {
                "model": LLAMA_MODEL,
                "error": f"{type(exc).__name__}:{exc}",
                "fallback_used": True,
            }
        completed_rows.append(row)
        completed_audio.add(audio)
        _atomic_json(
            checkpoint_path,
            _checkpoint_payload(
                base_sha256=base_sha256,
                resolver_fingerprint=fingerprint,
                rows=completed_rows,
            ),
        )
        print(
            json.dumps(
                {
                    "progress": f"{len(completed_rows)}/{len(selected_rows)}",
                    "audio": audio,
                    "lines": len(row.get("lines") or []),
                    "status": row.get("status"),
                    "llama_error": diagnostics["llama_resolution"].get("error", ""),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    completed_by_audio = {
        str(row.get("audio") or ""): row for row in completed_rows
    }
    ordered_rows = [
        completed_by_audio[str(row.get("audio") or "")]
        for row in selected_rows
        if str(row.get("audio") or "") in completed_by_audio
    ]
    output = {
        "schema": "emalo-evaluation-predictions/v1",
        "dataset_id": base.get("dataset_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_manifest_sha256": base.get("input_manifest_sha256"),
        "base_predictions_sha256": base_sha256,
        "application_fingerprint": fingerprint,
        "prediction_mode": (
            "local_llama70b_query_expansion_only_no_target"
            if args.expansion_only
            else "local_llama70b_two_stage_authorized_catalogue_no_target"
        ),
        "local_model": model_info,
        "truth_received_by_predictor": False,
        "erp_write_attempted": False,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "row_count": len(ordered_rows),
        "rows": ordered_rows,
    }
    _atomic_json(args.output, output)
    print(json.dumps({key: value for key, value in output.items() if key != "rows"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
