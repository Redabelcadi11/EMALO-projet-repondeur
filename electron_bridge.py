from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

from src.runtime_paths import bootstrap_runtime_environment
from src.erp_safety import ERPWriteBlocked, assert_erp_write_allowed


def _json_result(ok: bool, **payload) -> int:
    print(json.dumps({"ok": ok, **payload}, ensure_ascii=False))
    return 0 if ok else 1


def _refresh_ui_data(mode: str = "poc") -> None:
    if mode == "prod":
        from generer_ui_data_prod import main as generate_ui_data
    else:
        from generer_ui_data import main as generate_ui_data

    generate_ui_data()


def _send_orders(order_refs: list[str], send_all: bool = False, mode: str = "poc") -> int:
    import copilote_integration as ci

    lock_fd = None
    logs: list[str] = []
    try:
        assert_erp_write_allowed("pont UI: envoi de commandes Copilote")
    except ERPWriteBlocked as exc:
        return _json_result(False, message=str(exc), logs=logs, blocked=True)
    try:
        lock_fd = ci.acquire_send_lock()
        rows = ci.load_csv()
        groups = ci.group_orders(rows)
        requested = {ref.strip() for ref in order_refs if ref.strip()}
        pending: list[tuple[str, list[tuple[int, dict[str, str]]]]] = []

        for order_ref, indexed_rows in groups.items():
            if mode == "prod" and not ci.is_nextcloud_order_ref(order_ref):
                continue
            if not send_all and order_ref not in requested:
                continue
            statuses = [ci.normalize_status(row) for _, row in indexed_rows]
            if statuses and all(status in ci.TERMINAL_STATUSES for status in statuses):
                continue
            if any(status in ci.TERMINAL_STATUSES for status in statuses):
                msg = "Commande deja partiellement traitee: corriger le CSV avant renvoi"
                for index, row in indexed_rows:
                    if ci.normalize_status(row) not in ci.TERMINAL_STATUSES:
                        rows[index]["statut"] = "ERREUR"
                        rows[index]["message"] = msg
                logs.append(f"{order_ref}: {msg}")
                continue
            if statuses and all(status in ci.PENDING_STATUSES for status in statuses):
                pending.append((order_ref, indexed_rows))

        if not pending:
            ci.save_csv(rows)
            _refresh_ui_data()
            return _json_result(True, message="Aucune commande a envoyer.", logs=logs)

        for order_ref, indexed_rows in pending:
            order_rows = [row for _, row in indexed_rows]
            errors = ci.validate_template(order_rows)
            if errors:
                msg = "Commande CSV invalide: " + " | ".join(errors[:3])
                for index, _ in indexed_rows:
                    rows[index]["statut"] = "ERREUR"
                    rows[index]["message"] = msg
                ci.save_csv(rows)
                logs.append(f"{order_ref}: {msg}")
                continue

            duplicate = ci.find_duplicate_sent_order(order_ref, order_rows, rows)
            if duplicate:
                duplicate_ref = duplicate.get("order_ref", "")
                duplicate_number = duplicate.get("copilote_numero", "")
                duplicate_sent_at = duplicate.get("sent_at", "")
                verify_note = ""
                if duplicate_number:
                    try:
                        verified, verify_message, verify_dir = ci.verify_order_in_search(duplicate_number)
                        if verified:
                            verify_note = f" Recherche Copilote confirmee; verify={verify_dir}"
                        else:
                            verify_note = f" Recherche Copilote non confirmee: {verify_message}; verify={verify_dir}"
                    except Exception as verify_exc:
                        verify_note = f" Recherche Copilote impossible: {verify_exc}"
                msg = (
                    "Doublon probable: meme client/date/produits qu'une commande deja envoyee "
                    f"({duplicate_ref}"
                    f"{', Copilote ' + duplicate_number if duplicate_number else ''}"
                    f"{', envoyee le ' + duplicate_sent_at if duplicate_sent_at else ''})."
                    f"{verify_note}"
                )
                for index, _ in indexed_rows:
                    rows[index]["statut"] = "ERREUR"
                    rows[index]["http_status"] = ""
                    rows[index]["copilote_numero"] = duplicate_number
                    rows[index]["sent_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    rows[index]["message"] = msg
                ci.save_csv(rows)
                logs.append(f"{order_ref}: {msg}")
                continue

            status = None
            try:
                status, reason, candidates, out_dir, error = ci.send_service_request(order_ref, order_rows)
                number = candidates[-1] if candidates else ""
                sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                message = f"HTTP {status} {reason}; logs={out_dir}"
                if error:
                    message = f"{error}; {message}"
                final_status = "ENVOYE" if 200 <= status < 300 and not error else "ERREUR"
                if final_status == "ENVOYE" and number:
                    try:
                        verified, verify_message, verify_dir = ci.verify_order_in_search(number)
                        if verified:
                            message = f"{message}; verification recherche Copilote OK; verify={verify_dir}"
                        else:
                            message = f"{message}; verification non confirmee: {verify_message}; verify={verify_dir}"
                    except Exception as verify_exc:
                        message = f"{message}; verification non confirmee: {verify_exc}"
            except Exception as exc:
                number = ""
                sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                message = str(exc)
                final_status = "ERREUR"

            for index, _ in indexed_rows:
                rows[index]["statut"] = final_status
                rows[index]["http_status"] = str(status) if status is not None else ""
                rows[index]["copilote_numero"] = number
                rows[index]["sent_at"] = sent_at
                rows[index]["message"] = message
            ci.save_csv(rows)
            logs.append(f"{order_ref}: {final_status} {number} {message}")
            time.sleep(0.3)

        _refresh_ui_data(mode)
        return _json_result(True, message="Traitement termine.", logs=logs)
    except Exception as exc:
        try:
            _refresh_ui_data(mode)
        except Exception:
            pass
        return _json_result(False, message=str(exc), logs=logs)
    finally:
        if lock_fd is not None:
            ci.release_send_lock(lock_fd)


def _prod_refresh(days: int = 10, max_new: int | None = 0) -> int:
    logs: list[str] = []
    try:
        from recuperer_nextcloud import main as nextcloud_main
        from prod_pipeline import run_nextcloud_recent_pipeline

        sync_code = int(nextcloud_main(["--insecure"]) or 0)
        logs.append(f"Nextcloud: code {sync_code}")
        if sync_code != 0:
            _refresh_ui_data("prod")
            return _json_result(False, message=f"Synchronisation Nextcloud en erreur: {sync_code}", logs=logs)

        result = run_nextcloud_recent_pipeline(
            days=days,
            date_reference=date.today(),
            max_new_transcriptions=max_new,
        )
        logs.append(result.get("message", "Traitement vocal termine."))
        _refresh_ui_data("prod")
        changed = any(
            int(result.get(name) or 0) > 0
            for name in ("audios", "transcrits", "validees", "problematiques")
        )
        return _json_result(
            True,
            message=result.get("message", "Commandes rechargees."),
            logs=logs,
            result=result,
            changed=changed,
        )
    except Exception as exc:
        try:
            _refresh_ui_data("prod")
        except Exception:
            pass
        logs.append(str(exc))
        return _json_result(False, message=str(exc), logs=logs, changed=False)


def _prod_sync() -> int:
    logs: list[str] = []
    try:
        from recuperer_nextcloud import main as nextcloud_main

        sync_code = int(nextcloud_main(["--insecure"]) or 0)
        logs.append(f"Nextcloud: code {sync_code}")
        _refresh_ui_data("prod")
        if sync_code != 0:
            return _json_result(
                False,
                message=f"Synchronisation Nextcloud en erreur: {sync_code}",
                logs=logs,
                changed=False,
            )
        return _json_result(
            True,
            message="Synchronisation Nextcloud terminee.",
            logs=logs,
            changed=True,
        )
    except Exception as exc:
        try:
            _refresh_ui_data("prod")
        except Exception:
            pass
        logs.append(str(exc))
        return _json_result(False, message=str(exc), logs=logs, changed=False)


def _process_audios(encoded_payload: str, mode: str = "prod") -> int:
    logs: list[str] = []
    try:
        payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        return _json_result(False, message=f"Payload audios invalide: {exc}", logs=logs)

    keys = payload.get("keys") if isinstance(payload.get("keys"), list) else []
    audio_keys = [str(key).strip() for key in keys if str(key).strip()]
    if not audio_keys:
        return _json_result(False, message="Aucun audio selectionne.", logs=logs)

    try:
        from prod_pipeline import run_selected_audios_pipeline

        result = run_selected_audios_pipeline(audio_keys, max_new_transcriptions=None)
        logs.append(result.get("message", "Traitement audio termine."))
        _refresh_ui_data(mode)
        return _json_result(
            True,
            message=result.get("message", "Commande(s) creee(s) depuis les audios."),
            logs=logs,
            result=result,
            changed=True,
        )
    except Exception as exc:
        try:
            _refresh_ui_data(mode)
        except Exception:
            pass
        logs.append(str(exc))
        return _json_result(False, message=str(exc), logs=logs, changed=False)


def _transcribe_audio(encoded_payload: str) -> int:
    logs: list[str] = []
    try:
        payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        return _json_result(False, message=f"Payload transcription invalide: {exc}", logs=logs)

    key = str(payload.get("key") or "").strip()
    if not key:
        return _json_result(False, message="Aucun audio selectionne.", logs=logs)

    try:
        from prod_pipeline import transcribe_selected_audio

        result = transcribe_selected_audio(key)
        _refresh_ui_data("prod")
        return _json_result(
            bool(result.get("found")),
            message=result.get("message", "Transcription terminee."),
            logs=logs,
            result=result,
            changed=True,
        )
    except Exception as exc:
        try:
            _refresh_ui_data("prod")
        except Exception:
            pass
        logs.append(str(exc))
        return _json_result(False, message=str(exc), logs=logs, changed=False)


def _analyze_audio(encoded_payload: str) -> int:
    logs: list[str] = []
    try:
        payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        return _json_result(False, message=f"Payload analyse invalide: {exc}", logs=logs)

    key = str(payload.get("key") or "").strip()
    if not key:
        return _json_result(False, message="Aucun audio selectionne.", logs=logs)

    try:
        from prod_pipeline import analyze_selected_audio

        result = analyze_selected_audio(key)
        _refresh_ui_data("prod")
        return _json_result(
            bool(result.get("found")),
            message=result.get("message", "Analyse terminee."),
            logs=logs,
            result=result,
            changed=True,
        )
    except Exception as exc:
        try:
            _refresh_ui_data("prod")
        except Exception:
            pass
        logs.append(str(exc))
        return _json_result(False, message=str(exc), logs=logs, changed=False)


def _send_audio_order(encoded_payload: str) -> int:
    logs: list[str] = []
    try:
        assert_erp_write_allowed("pont UI: analyse puis envoi d'une commande audio")
    except ERPWriteBlocked as exc:
        return _json_result(False, message=str(exc), logs=logs, blocked=True)
    try:
        payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        return _json_result(False, message=f"Payload envoi audio invalide: {exc}", logs=logs)

    key = str(payload.get("key") or "").strip()
    if not key:
        return _json_result(False, message="Aucun audio selectionne.", logs=logs)

    try:
        from prod_pipeline import run_selected_audios_pipeline

        result = run_selected_audios_pipeline([key], max_new_transcriptions=None)
        logs.append(result.get("message", "Traitement audio termine."))
        refs = [str(ref).strip() for ref in result.get("order_refs", []) if str(ref).strip()]
        if not refs:
            _refresh_ui_data("prod")
            return _json_result(
                False,
                message="Aucune commande sure a envoyer pour cet audio. Corriger le cas avant envoi.",
                logs=logs,
                result=result,
                changed=True,
            )
        return _send_orders(refs, send_all=False, mode="prod")
    except Exception as exc:
        try:
            _refresh_ui_data("prod")
        except Exception:
            pass
        logs.append(str(exc))
        return _json_result(False, message=str(exc), logs=logs, changed=False)


def _mark_existing_nextcloud_transmitted() -> int:
    try:
        from prod_audio_state import mark_existing_nextcloud_audios_as_handled

        count = mark_existing_nextcloud_audios_as_handled()
        _refresh_ui_data("prod")
        return _json_result(
            True,
            message=f"{count} audio(s) Nextcloud marque(s) comme deja transmis.",
        )
    except Exception as exc:
        return _json_result(False, message=str(exc))


def _update_order(encoded_payload: str, mode: str = "prod") -> int:
    import copilote_integration as ci

    try:
        payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        return _json_result(False, message=f"Payload correction invalide: {exc}")

    order_ref = str(payload.get("order_ref") or "").strip()
    if not order_ref:
        return _json_result(False, message="order_ref manquant.")

    rows = ci.load_csv()
    groups = ci.group_orders(rows)
    indexed_rows = groups.get(order_ref)
    if not indexed_rows:
        return _json_result(False, message=f"Commande introuvable: {order_ref}")

    if any(ci.normalize_status(row) in ci.TERMINAL_STATUSES for _, row in indexed_rows):
        return _json_result(False, message="Commande deja envoyee ou ignoree: correction refusee.")

    common_fields = {
        "client": str(payload.get("client") or "").strip(),
        "client_code": str(payload.get("client_code") or "").strip().upper(),
        "date_livraison": str(payload.get("date_livraison") or "").strip(),
    }
    products = payload.get("products") if isinstance(payload.get("products"), list) else []

    for offset, (index, row) in enumerate(indexed_rows):
        for key, value in common_fields.items():
            if value:
                rows[index][key] = value
        if offset < len(products) and isinstance(products[offset], dict):
            product = products[offset]
            for key in ("product_code", "product_label", "quantity", "unit"):
                value = str(product.get(key) or "").strip()
                if value:
                    rows[index][key] = value.upper() if key in {"product_code", "unit"} else value
        rows[index]["statut"] = "A_ENVOYER"
        rows[index]["http_status"] = ""
        rows[index]["copilote_numero"] = ""
        rows[index]["sent_at"] = ""
        rows[index]["message"] = "Corrige depuis l'interface prod"

    errors = ci.validate_template([rows[index] for index, _ in indexed_rows])
    if errors:
        for index, _ in indexed_rows:
            rows[index]["statut"] = "ERREUR"
            rows[index]["message"] = "Correction invalide: " + " | ".join(errors[:3])
        ci.save_csv(rows)
        _refresh_ui_data(mode)
        return _json_result(False, message="Correction enregistree mais commande invalide.", logs=errors)

    ci.save_csv(rows)
    _refresh_ui_data(mode)
    return _json_result(True, message=f"Commande {order_ref} corrigee et remise a envoyer.")


def _safe_ref(value: str, fallback: str = "NC-MANUAL") -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "")).strip("-_.")
    return f"NC-{stem[:64]}" if stem else fallback


def _create_order(encoded_payload: str, mode: str = "prod") -> int:
    import copilote_integration as ci

    try:
        payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        return _json_result(False, message=f"Payload creation invalide: {exc}")

    source_audio = str(payload.get("source_audio") or "").strip()
    order_ref = str(payload.get("order_ref") or "").strip() or _safe_ref(source_audio, "NC-MANUAL")
    client = str(payload.get("client") or "").strip()
    client_code = str(payload.get("client_code") or "").strip().upper()
    date_livraison = str(payload.get("date_livraison") or "").strip()
    products = payload.get("products") if isinstance(payload.get("products"), list) else []

    new_rows = []
    for product in products:
        if not isinstance(product, dict):
            continue
        product_code = str(product.get("product_code") or "").strip().upper()
        quantity = str(product.get("quantity") or "").strip().replace(",", ".")
        unit = str(product.get("unit") or "").strip().upper()
        if not product_code and not quantity and not unit:
            continue
        row = {name: "" for name in ci.ALL_COLUMNS}
        row.update(
            {
                "order_ref": order_ref,
                "dossier": ci.SUPPORTED_DOSSIER,
                "client": client,
                "client_code": client_code,
                "date_livraison": date_livraison,
                "transport": "",
                "transport_code": "",
                "product_code": product_code,
                "product_label": str(product.get("product_label") or "").strip(),
                "quantity": quantity,
                "unit": unit or "UB",
                "statut": "A_ENVOYER",
                "message": f"Commande creee depuis l'interface prod ({source_audio})",
            }
        )
        new_rows.append(row)

    if not new_rows:
        return _json_result(False, message="Aucune ligne produit valide.")

    errors = ci.validate_template(new_rows)
    if errors:
        return _json_result(False, message="Commande invalide.", logs=errors)

    rows = ci.load_csv()
    groups = ci.group_orders(rows)
    existing = groups.get(order_ref, [])
    if any(ci.normalize_status(row) in ci.TERMINAL_STATUSES for _, row in existing):
        return _json_result(False, message="Une commande envoyee existe deja avec cette reference.")

    remove_indexes = {index for index, _ in existing}
    rows = [row for index, row in enumerate(rows) if index not in remove_indexes]
    rows.extend(new_rows)
    ci.save_csv(rows)
    _refresh_ui_data(mode)
    return _json_result(True, message=f"Commande {order_ref} creee et prete a envoyer.")


def _save_test_corrections(encoded_payload: str) -> int:
    try:
        payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        return _json_result(False, message=f"Payload corrections test invalide: {exc}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    root = Path(__file__).resolve().parent
    out_dir = root / "resultats" / "tests-repondeur"
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "corrections_test_repondeur.jsonl"
    csv_path = out_dir / "corrections_test_repondeur.csv"

    audio = payload.get("audio") if isinstance(payload.get("audio"), dict) else {}
    client = payload.get("client") if isinstance(payload.get("client"), dict) else {}
    products = payload.get("products") if isinstance(payload.get("products"), list) else []
    reasons = payload.get("reasons") if isinstance(payload.get("reasons"), list) else []

    payload["saved_at"] = now
    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    fieldnames = [
        "saved_at",
        "audio_key",
        "audio_name",
        "audio_path",
        "phone",
        "audio_date",
        "audio_time",
        "source",
        "order_ref",
        "status",
        "line_type",
        "line_order",
        "detected_recognized",
        "detected_code",
        "detected_label",
        "detected_quantity",
        "detected_unit",
        "detected_source_text",
        "corrected_code",
        "reasons",
        "transcription",
    ]

    rows: list[dict[str, str]] = []
    common = {
        "saved_at": now,
        "audio_key": str(audio.get("key") or ""),
        "audio_name": str(audio.get("name") or ""),
        "audio_path": str(audio.get("path") or ""),
        "phone": str(audio.get("phone") or ""),
        "audio_date": str(audio.get("date") or ""),
        "audio_time": str(audio.get("time") or ""),
        "source": str(payload.get("source") or ""),
        "order_ref": str(payload.get("order_ref") or ""),
        "status": str(payload.get("status") or ""),
        "reasons": " | ".join(str(item) for item in reasons),
        "transcription": str(payload.get("transcription") or ""),
    }
    rows.append(
        {
            **common,
            "line_type": "client",
            "line_order": "",
            "detected_recognized": "1" if client.get("recognized") else "0",
            "detected_code": str(client.get("code") or ""),
            "detected_label": str(client.get("display") or ""),
            "detected_quantity": "",
            "detected_unit": "",
            "detected_source_text": "",
            "corrected_code": str(client.get("corrected_code") or "").strip(),
        }
    )
    for product in products:
        if not isinstance(product, dict):
            continue
        rows.append(
            {
                **common,
                "line_type": "product",
                "line_order": str(product.get("order") or ""),
                "detected_recognized": "1" if product.get("recognized") else "0",
                "detected_code": str(product.get("code") or ""),
                "detected_label": str(product.get("label") or ""),
                "detected_quantity": str(product.get("quantity") or ""),
                "detected_unit": str(product.get("unit") or ""),
                "detected_source_text": str(product.get("source_text") or ""),
                "corrected_code": str(product.get("corrected_code") or "").strip(),
            }
        )

    write_header = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    return _json_result(
        True,
        message=f"Corrections test enregistrees ({len(rows)} ligne(s)).",
        path=str(csv_path),
        jsonl_path=str(jsonl_path),
    )


def _load_audio_notes() -> int:
    try:
        from src.audio_notes import DEFAULT_NOTES_PATH, load_audio_notes

        document = load_audio_notes()
        return _json_result(
            True,
            message=f"{len(document['notes'])} remarque(s) chargee(s).",
            notes=document["notes"],
            updated_at=document.get("updated_at", ""),
            path=str(DEFAULT_NOTES_PATH),
        )
    except Exception as exc:
        return _json_result(False, message=str(exc), notes={})


def _save_audio_note(encoded_payload: str) -> int:
    try:
        payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        return _json_result(False, message=f"Payload remarque invalide: {exc}")

    audio = payload.get("audio") if isinstance(payload.get("audio"), dict) else {}
    key = payload.get("key") or audio.get("key")
    try:
        from src.audio_notes import DEFAULT_NOTES_PATH, save_audio_note

        saved = save_audio_note(
            key,
            payload.get("note", ""),
            audio=audio,
        )
        return _json_result(
            True,
            message="Remarque enregistree." if saved else "Remarque supprimee.",
            note=saved,
            key=str(key or ""),
            path=str(DEFAULT_NOTES_PATH),
        )
    except Exception as exc:
        return _json_result(False, message=str(exc))


def main(argv: list[str] | None = None) -> int:
    bootstrap_runtime_environment()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate-ui-data")
    sub.add_parser("generate-prod-ui-data")
    sub.add_parser("mark-existing-nextcloud-transmitted")
    sub.add_parser("prod-sync")
    prod_refresh = sub.add_parser("prod-refresh")
    prod_refresh.add_argument("--days", type=int, default=10)
    prod_refresh.add_argument("--max-new", type=int, default=0)
    process_audios = sub.add_parser("process-audios")
    process_audios.add_argument("payload")
    process_audios.add_argument("--mode", choices=["prod"], default="prod")
    transcribe_audio = sub.add_parser("transcribe-audio")
    transcribe_audio.add_argument("payload")
    create_audio = sub.add_parser("create-audio-order")
    create_audio.add_argument("payload")
    analyze_audio = sub.add_parser("analyze-audio")
    analyze_audio.add_argument("payload")
    send_audio = sub.add_parser("send-audio-order")
    send_audio.add_argument("payload")
    send = sub.add_parser("send")
    send.add_argument("--all", action="store_true")
    send.add_argument("--mode", choices=["poc", "prod"], default="poc")
    send.add_argument("refs", nargs="*")
    update = sub.add_parser("update-order")
    update.add_argument("payload")
    update.add_argument("--mode", choices=["poc", "prod"], default="prod")
    create = sub.add_parser("create-order")
    create.add_argument("payload")
    create.add_argument("--mode", choices=["poc", "prod"], default="prod")
    save_test = sub.add_parser("save-test-corrections")
    save_test.add_argument("payload")
    sub.add_parser("load-audio-notes")
    save_note = sub.add_parser("save-audio-note")
    save_note.add_argument("payload")
    sub.add_parser("pipeline")
    sync = sub.add_parser("nextcloud-sync")
    sync.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "generate-ui-data":
        _refresh_ui_data()
        return _json_result(True, message="Donnees UI rechargees.")
    if args.command == "generate-prod-ui-data":
        _refresh_ui_data("prod")
        return _json_result(True, message="Donnees UI prod rechargees.")
    if args.command == "mark-existing-nextcloud-transmitted":
        return _mark_existing_nextcloud_transmitted()
    if args.command == "prod-sync":
        return _prod_sync()
    if args.command == "prod-refresh":
        return _prod_refresh(days=args.days, max_new=args.max_new)
    if args.command == "process-audios":
        return _process_audios(args.payload, mode=args.mode)
    if args.command == "transcribe-audio":
        return _transcribe_audio(args.payload)
    if args.command == "create-audio-order":
        return _process_audios(args.payload, mode="prod")
    if args.command == "analyze-audio":
        return _analyze_audio(args.payload)
    if args.command == "send-audio-order":
        return _send_audio_order(args.payload)
    if args.command == "send":
        return _send_orders(args.refs, send_all=args.all, mode=args.mode)
    if args.command == "update-order":
        return _update_order(args.payload, mode=args.mode)
    if args.command == "create-order":
        return _create_order(args.payload, mode=args.mode)
    if args.command == "save-test-corrections":
        return _save_test_corrections(args.payload)
    if args.command == "load-audio-notes":
        return _load_audio_notes()
    if args.command == "save-audio-note":
        return _save_audio_note(args.payload)
    if args.command == "pipeline":
        from lancer_pipeline import main as pipeline_main

        code = int(pipeline_main([]) or 0)
        _refresh_ui_data()
        return _json_result(code == 0, message=f"Pipeline termine avec code {code}.")
    if args.command == "nextcloud-sync":
        from recuperer_nextcloud import main as nextcloud_main

        sync_args = ["--insecure"]
        if args.dry_run:
            sync_args.append("--dry-run")
        code = int(nextcloud_main(sync_args) or 0)
        _refresh_ui_data()
        return _json_result(code == 0, message=f"Synchronisation terminee avec code {code}.")
    return _json_result(False, message="Commande inconnue.")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
