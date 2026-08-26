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
# The scheduler runs as SYSTEM while the desktop UI runs as an ordinary user.
# A per-user temporary directory would therefore make automated results
# invisible to the UI.  Keep the authoritative payload in the shared project
# cache and write the old per-user location as a compatibility copy.
OUTPUT_JSON = PROJECT_ROOT / "cache" / "ui" / "repondeur-data-prod.json"
LEGACY_OUTPUT_JSON = (
    Path(tempfile.gettempdir()) / "projet-repondeur" / "repondeur-data-prod.json"
)
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


def extraction_metadata_by_order() -> dict[str, dict[str, str]]:
    """Read durable per-audio analyses so polling never hides past details."""
    metadata: dict[str, dict[str, str]] = {}
    if not EXTRACTIONS_DIR.exists():
        return metadata
    today = date.today()
    for path in EXTRACTIONS_DIR.glob("*__extraction.json"):
        try:
            extraction = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(extraction, dict):
            continue
        source = Path(str(extraction.get("fichier_audio") or "")).name
        if not source:
            source = path.name.replace("__extraction.json", ".wav")
        if not in_recent_window(source, today=today, days=RECENT_DAYS):
            continue
        order_ref = safe_order_ref(source, "")
        if not order_ref:
            continue
        parsed = parse_source_datetime(source)
        delivery = extraction.get("date_livraison") or {}
        reasons = extraction.get("raisons_problematiques") or []
        metadata[order_ref] = {
            "source_audio": source,
            "audio_date": parsed.strftime("%Y-%m-%d") if parsed else "",
            "audio_time": parsed.strftime("%H:%M") if parsed else "",
            "run_id": str(extraction.get("genere_le") or ""),
            "client_code": str(extraction.get("client_retenu") or ""),
            "client_nom": str(extraction.get("client_nom_retenu") or ""),
            "date_livraison": str(delivery.get("date_iso") or "")
            if isinstance(delivery, dict)
            else "",
            "statut": str(extraction.get("statut") or ""),
            "raisons_problematiques": " | ".join(
                str(reason) for reason in reasons if str(reason).strip()
            ),
            "transcription": str(extraction.get("transcription") or ""),
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


def build_orders(
    copilote_rows: list[dict[str, str]],
    validated_rows: list[dict[str, str]],
    extraction_metadata: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    meta = validated_metadata(validated_rows)
    for order_ref, extraction in (extraction_metadata or {}).items():
        meta.setdefault(order_ref, extraction)
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
        recognition_details = problem_recognition_details(source)
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
                "product_recognition": recognition_details.get(
                    "product_recognition", []
                ),
                "warnings": recognition_details.get("warnings", []),
                "transcription": recognition_details.get("transcription", ""),
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


def build_problematic(
    rows: list[dict[str, str]],
    extraction_metadata: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    today = date.today()
    result: list[dict[str, str]] = []
    known_sources: set[str] = set()
    for row in rows:
        source = row.get("audio_source", "")
        if is_audio_handled(source):
            continue
        if in_recent_window(source, today=today, days=RECENT_DAYS):
            enriched = dict(row)
            enriched.update(problem_recognition_details(source))
            result.append(enriched)
            known_sources.add(Path(source).name)
    for extraction in (extraction_metadata or {}).values():
        source = str(extraction.get("source_audio") or "")
        if (
            not source
            or Path(source).name in known_sources
            or extraction.get("statut") == "VALIDEE"
            or is_audio_handled(source)
        ):
            continue
        enriched = {
            "audio_source": source,
            "client_code": extraction.get("client_code", ""),
            "client_nom": extraction.get("client_nom", ""),
            "date_livraison": extraction.get("date_livraison", ""),
            "statut": "PROBLEMATIQUE",
            "raisons_problematiques": extraction.get("raisons_problematiques", ""),
            "transcription": extraction.get("transcription", ""),
        }
        enriched.update(problem_recognition_details(source))
        result.append(enriched)
    return result


def extraction_path_for_source(source: str) -> Path:
    stem = Path(source or "").stem
    if not stem:
        return EXTRACTIONS_DIR / "__missing__"
    return EXTRACTIONS_DIR / f"{stem}__extraction.json"


def problem_recognition_details(source: str) -> dict:
    from src.segment_association import (
        indexer_lignes_par_segment,
        ligne_associee_au_segment,
    )
    from src.ui_product_details import (
        avertissements_commande,
        projection_produit_reconnu,
    )

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
    lignes_par_segment, lignes_legacy_par_texte = indexer_lignes_par_segment(
        extraction.get("lignes_commande") or []
    )

    product_recognition = []
    for index, produit in enumerate(extraction.get("produits") or [], start=1):
        if not isinstance(produit, dict):
            continue
        ligne = ligne_associee_au_segment(
            produit,
            lignes_par_segment,
            lignes_legacy_par_texte,
        )
        projection = projection_produit_reconnu(produit, ligne, index)
        if projection is not None:
            product_recognition.append(projection)

    return {
        "client_recognized": bool(client_code),
        "client_code": client_code,
        "client_display": client_name if client_code else "Non reconnu",
        "product_recognition": product_recognition,
        "transcription": str(extraction.get("transcription") or ""),
        "warnings": avertissements_commande(
            extraction.get("raisons_problematiques", [])
        ),
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
        transcription = ""
        if transcription_path.exists():
            try:
                transcription_payload = json.loads(
                    transcription_path.read_text(encoding="utf-8")
                )
                if isinstance(transcription_payload, dict):
                    transcription = str(
                        transcription_payload.get("texte")
                        or transcription_payload.get("transcription")
                        or ""
                    ).strip()
            except (OSError, json.JSONDecodeError):
                pass
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
                "transcription": transcription,
                "status": "DEJA_TRANSMIS" if handled else "NOUVEAU",
                "night_window": is_night_audio(parsed),
                "tournee_key": tournee_key(parsed),
                "tournee_label": tournee_label_from_key(tournee_key(parsed)),
            }
        )
    return result


def write_payload(payload: dict) -> None:
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = OUTPUT_JSON.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(OUTPUT_JSON)
    # Legacy Electron packages still read this path.  Its content is only a
    # cache: failure to update it must never invalidate the shared payload.
    try:
        LEGACY_OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        LEGACY_OUTPUT_JSON.write_text(content, encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    validated_rows = read_csv(VALIDATED_CSV, delimiter=";")
    copilote_rows = read_csv(COPILOTE_CSV)
    extraction_metadata = extraction_metadata_by_order()
    problematic = build_problematic(
        read_csv(PROBLEM_CSV, delimiter=";"),
        extraction_metadata,
    )
    orders = build_orders(copilote_rows, validated_rows, extraction_metadata)
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
