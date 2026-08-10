from __future__ import annotations

import csv
import json
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from src.runtime_paths import get_project_root
from prod_audio_state import AUDIO_EXTENSIONS, audio_key, is_audio_handled
from prod_tournee import (
    is_night_audio,
    last_operational_tournee,
    tournee_key,
    tournee_label_from_key,
)


PROJECT_ROOT = get_project_root()
VALIDATED_CSV = PROJECT_ROOT / "resultats" / "commandes-validees" / "commandes_validees.csv"
COPILOTE_CSV = PROJECT_ROOT / "copilote" / "commandes-copilote.csv"
PROBLEM_CSV = PROJECT_ROOT / "resultats" / "commandes-problematiques" / "commandes_problematiques.csv"
NEXTCLOUD_AUDIO_DIR = PROJECT_ROOT / "ressources-originales" / "audio-nextcloud"
TRANSCRIPTIONS_DIR = PROJECT_ROOT / "resultats" / "transcriptions"
EXTRACTIONS_DIR = PROJECT_ROOT / "resultats" / "extractions"
OUTPUT_JSON = Path(tempfile.gettempdir()) / "projet-repondeur" / "repondeur-data-prod.json"
RECENT_DAYS = 10
PENDING_STATUSES = {"A_ENVOYE", "A_ENVOYER"}
SENT_STATUSES = {"ENVOYE", "ENVOYE_VERIFIE"}
FILENAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[_ -](\d{2})[-h](\d{2})(?:[-m](\d{2}))?")
DATE_ONLY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
PHONE_RE = re.compile(r"(?:^|[_ -])De[-_ ]?(\+?\d{6,15})", re.IGNORECASE)


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delimiter))


def normalize(value: str) -> str:
    return (value or "").strip().upper()


def is_nextcloud_ref(order_ref: str) -> bool:
    return normalize(order_ref).startswith("NC-")


def parse_source_datetime(value: str) -> datetime | None:
    match = FILENAME_DATE_RE.search(value or "")
    if match:
        second = match.group(4) or "00"
        try:
            return datetime.strptime(
                f"{match.group(1)} {match.group(2)}:{match.group(3)}:{second}",
                "%Y-%m-%d %H:%M:%S",
            )
        except ValueError:
            return None
    date_match = DATE_ONLY_RE.search(value or "")
    if date_match:
        try:
            return datetime.strptime(date_match.group(1), "%Y-%m-%d")
        except ValueError:
            return None
    return None


def parse_phone(value: str) -> str:
    match = PHONE_RE.search(value or "")
    if not match:
        return ""
    phone = match.group(1).strip()
    if phone.startswith("+"):
        return "+" + re.sub(r"\D+", "", phone[1:])
    return re.sub(r"\D+", "", phone)


def in_recent_window(value: str, today: date, days: int) -> bool:
    parsed = parse_source_datetime(value)
    if parsed is None:
        return True
    cutoff = today - timedelta(days=max(0, days))
    return cutoff <= parsed.date() <= today


def safe_order_ref(audio_source: str, fallback: str) -> str:
    stem = Path(audio_source).stem if audio_source else ""
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-_.")
    return f"NC-{stem[:64]}" if stem else fallback


def validated_metadata(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        source = (row.get("audio_source") or "").strip()
        if source:
            grouped[source].append(row)
    for index, (source, lines) in enumerate(sorted(grouped.items()), start=1):
        first = lines[0]
        order_ref = safe_order_ref(source, f"NC-{index:03d}")
        parsed = parse_source_datetime(source)
        metadata[order_ref] = {
            "source_audio": source,
            "audio_date": parsed.strftime("%Y-%m-%d") if parsed else "",
            "audio_time": parsed.strftime("%H:%M") if parsed else "",
            "run_id": first.get("run_id", ""),
            "generated_at": first.get("genere_le", ""),
        }
    return metadata


def status_for_lines(lines: list[dict[str, str]]) -> str:
    statuses = [normalize(row.get("statut", "")) for row in lines]
    if statuses and all(status in SENT_STATUSES for status in statuses):
        return "ENVOYE"
    if any(status == "ERREUR" for status in statuses):
        return "ERREUR"
    if statuses and all(status in PENDING_STATUSES for status in statuses):
        return "A_ENVOYER"
    if statuses and all(status == "IGNORE" for status in statuses):
        return "IGNORE"
    return statuses[0] if statuses else "A_ENVOYER"


def validation_errors(lines: list[dict[str, str]]) -> list[str]:
    try:
        import copilote_integration as ci

        return ci.validate_template(lines)
    except Exception as exc:
        return [str(exc)]


def build_orders(copilote_rows: list[dict[str, str]], validated_rows: list[dict[str, str]]) -> list[dict]:
    meta = validated_metadata(validated_rows)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in copilote_rows:
        order_ref = (row.get("order_ref") or "").strip()
        if order_ref and is_nextcloud_ref(order_ref):
            grouped[order_ref].append(row)

    today = date.today()
    orders: list[dict] = []
    for order_ref, lines in sorted(grouped.items()):
        first = lines[0]
        metadata = meta.get(order_ref, {})
        source = metadata.get("source_audio", "") or order_ref
        if is_audio_handled(source) or is_audio_handled(order_ref):
            continue
        if not in_recent_window(source, today=today, days=RECENT_DAYS):
            continue
        status = status_for_lines(lines)
        errors = validation_errors(lines) if status in PENDING_STATUSES else []
        products = [
            {
                "product_code": line.get("product_code", ""),
                "product_label": line.get("product_label", ""),
                "quantity": line.get("quantity", ""),
                "unit": line.get("unit", ""),
                "statut": line.get("statut", ""),
                "message": line.get("message", ""),
            }
            for line in lines
        ]
        orders.append(
            {
                "order_ref": order_ref,
                "client": first.get("client", ""),
                "client_code": first.get("client_code", ""),
                "date_livraison": first.get("date_livraison", ""),
                "statut": status,
                "copilote_numero": first.get("copilote_numero", ""),
                "sent_at": first.get("sent_at", ""),
                "message": first.get("message", ""),
                "source_audio": source,
                "audio_date": metadata.get("audio_date", ""),
                "audio_time": metadata.get("audio_time", ""),
                "run_id": metadata.get("run_id", ""),
                "products": products,
                "can_send": status in PENDING_STATUSES and not errors,
                "validation_errors": errors,
            }
        )
    return sorted(
        orders,
        key=lambda item: (
            item.get("audio_date") or "9999-99-99",
            item.get("audio_time") or "99:99",
            item.get("client") or "",
        ),
    )


def build_problematic(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    today = date.today()
    result = []
    for row in rows:
        source = row.get("audio_source", "")
        if is_audio_handled(source):
            continue
        if in_recent_window(source, today=today, days=RECENT_DAYS):
            enriched = dict(row)
            enriched.update(problem_recognition_details(source))
            result.append(enriched)
    return result


def extraction_path_for_source(source: str) -> Path:
    stem = Path(source or "").stem
    if not stem:
        return EXTRACTIONS_DIR / "__missing__"
    return EXTRACTIONS_DIR / f"{stem}__extraction.json"


def problem_recognition_details(source: str) -> dict:
    path = extraction_path_for_source(source)
    if not path.exists():
        return {
            "client_recognized": False,
            "client_display": "Non reconnu",
            "product_recognition": [],
        }

    try:
        extraction = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "client_recognized": False,
            "client_display": "Non reconnu",
            "product_recognition": [],
        }

    client_code = str(extraction.get("client_retenu") or "").strip()
    client_name = str(extraction.get("client_nom_retenu") or "").strip()
    lignes_par_ordre = {}
    for line in extraction.get("lignes_commande") or []:
        try:
            ordre = int(line.get("ordre_ligne") or 0)
        except (TypeError, ValueError):
            continue
        lignes_par_ordre[ordre] = line

    product_recognition = []
    for index, produit in enumerate(extraction.get("produits") or [], start=1):
        if not isinstance(produit, dict):
            continue
        ligne = lignes_par_ordre.get(index)
        selection = produit.get("selection") if isinstance(produit.get("selection"), dict) else {}
        recognized = bool(ligne and produit.get("produit_fiable"))
        product_recognition.append(
            {
                "order": index,
                "source_text": produit.get("texte_source", ""),
                "recognized": recognized,
                "product_code": line_value(ligne, "code_article") if recognized else "",
                "product_label": line_value(ligne, "libelle_article") if recognized else "",
                "quantity": line_value(ligne, "quantite") if recognized else produit.get("quantite_resolue", produit.get("quantite_principale", "")),
                "unit": line_value(ligne, "unite") if recognized else produit.get("unite_resolue", produit.get("unite_principale", "")),
                "candidate_code": selection.get("code_article", ""),
                "candidate_label": selection.get("libelle_article", ""),
                "score": selection.get("score_global", ""),
            }
        )

    if not product_recognition:
        for index, mention in enumerate(extraction.get("mentions_produits") or [], start=1):
            if not isinstance(mention, dict):
                continue
            product_recognition.append(
                {
                    "order": index,
                    "source_text": mention.get("texte_source") or mention.get("texte_produit") or "",
                    "recognized": False,
                    "product_code": "",
                    "product_label": "",
                    "quantity": mention.get("quantite", ""),
                    "unit": mention.get("unite_detectee", ""),
                    "candidate_code": "",
                    "candidate_label": "",
                    "score": "",
                }
            )

    return {
        "client_recognized": bool(client_code),
        "client_code": client_code,
        "client_display": client_name if client_code else "Non reconnu",
        "product_recognition": product_recognition,
    }


def line_value(line: dict | None, key: str) -> str:
    if not isinstance(line, dict):
        return ""
    return str(line.get(key) or "")


def build_audio_files() -> list[dict[str, str | bool | int]]:
    files: list[Path] = []
    if NEXTCLOUD_AUDIO_DIR.exists():
        files = sorted(
            (
                path
                for path in NEXTCLOUD_AUDIO_DIR.rglob("*")
                if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
            ),
            key=lambda item: (parse_source_datetime(item.name) or datetime.fromtimestamp(item.stat().st_mtime), item.name),
            reverse=True,
        )

    result: list[dict[str, str | bool | int]] = []
    for path in files:
        parsed = parse_source_datetime(path.name)
        handled = is_audio_handled(path.name)
        transcription_path = TRANSCRIPTIONS_DIR / f"{path.stem}__transcription.json"
        try:
            size = path.stat().st_size
            modified = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            size = 0
            modified = ""
        result.append(
            {
                "key": audio_key(path.name),
                "name": path.name,
                "path": str(path),
                "file_url": path.resolve().as_uri(),
                "phone": parse_phone(path.name),
                "date": parsed.strftime("%Y-%m-%d") if parsed else "",
                "time": parsed.strftime("%H:%M") if parsed else "",
                "size": size,
                "modified_at": modified,
                "handled": handled,
                "transcribed": transcription_path.exists(),
                "transcription_path": str(transcription_path),
                "status": "DEJA_TRANSMIS" if handled else "NOUVEAU",
                "night_window": is_night_audio(parsed),
                "tournee_key": tournee_key(parsed),
                "tournee_label": tournee_label_from_key(tournee_key(parsed)),
            }
        )
    return result


def write_payload(payload: dict) -> None:
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    validated_rows = read_csv(VALIDATED_CSV, delimiter=";")
    copilote_rows = read_csv(COPILOTE_CSV)
    problematic = build_problematic(read_csv(PROBLEM_CSV, delimiter=";"))
    orders = build_orders(copilote_rows, validated_rows)
    audio_files = build_audio_files()
    tournee = last_operational_tournee()
    tournee_audios = [
        item
        for item in audio_files
        if item.get("night_window") and tournee.contains(parse_source_datetime(str(item.get("name", ""))))
    ]
    tournee_new = [item for item in tournee_audios if not item.get("handled")]
    pending = [order for order in orders if order.get("can_send")]
    errors = [order for order in orders if order.get("statut") == "ERREUR" or order.get("validation_errors")]
    payload = {
        "mode": "prod",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window_days": RECENT_DAYS,
        "tournee": {
            "label": tournee.label,
            "start": tournee.start.isoformat(timespec="minutes"),
            "end": tournee.end.isoformat(timespec="minutes"),
            "business_window": "22:00 - 01:00",
        },
        "orders": orders,
        "problematic": problematic,
        "audio_files": audio_files,
        "summary": {
            "orders": len(orders),
            "pending": len(pending),
            "sent": len([order for order in orders if order.get("statut") == "ENVOYE"]),
            "errors": len(errors) + len(problematic),
            "audio_files": len(audio_files),
            "audio_handled": len([item for item in audio_files if item.get("handled")]),
            "audio_new": len([item for item in audio_files if not item.get("handled")]),
            "tournee_audio_files": len(tournee_audios),
            "tournee_audio_new": len(tournee_new),
            "tournee_audio_handled": len([item for item in tournee_audios if item.get("handled")]),
        },
        "paths": {
            "project": str(PROJECT_ROOT),
            "validated_csv": str(VALIDATED_CSV),
            "copilote_csv": str(COPILOTE_CSV),
            "problem_csv": str(PROBLEM_CSV),
        },
    }
    write_payload(payload)
    print(f"Prod UI data written: {OUTPUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
