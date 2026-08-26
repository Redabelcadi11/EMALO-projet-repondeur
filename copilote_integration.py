#!/usr/bin/env python3
import csv
import ctypes
import gzip
import hashlib
import http.client
import os
import re
import subprocess
import threading
import time
try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:
    tk = None
    messagebox = None
    ttk = None
import xml.etree.ElementTree as ET
from collections import defaultdict
from zipfile import ZipFile
from datetime import date, datetime
from pathlib import Path

from src.erp_safety import assert_erp_write_allowed


PROJECT_DIR = Path(__file__).resolve().parent
BASE_DIR = Path(r"C:\Users\adminemalo")
APP_DIR = PROJECT_DIR / "copilote"
CSV_PATH = APP_DIR / "commandes-copilote.csv"
VALIDATED_CSV = PROJECT_DIR / "resultats" / "commandes-validees" / "commandes_validees.csv"
RUNS_DIR = APP_DIR / "runs"
DOWNLOADS_DIR = BASE_DIR / "Downloads"
CLIENTS_XLSX = DOWNLOADS_DIR / "clients_la-zarpai.xlsx"
PRODUCTS_XLSX = DOWNLOADS_DIR / "produits_basco.xlsx"
CAPTURE_DIR = BASE_DIR / "erp-captures" / "saicom-20260618-131850"
RECONSTRUCTED_DIR = CAPTURE_DIR / "reconstructed-fixed2"
CAPTURE_XML = CAPTURE_DIR / "capture.xml"
SERVER = "172.16.213.101"
PORT = 8080
JAVA_EXE = Path(r"C:\agro\prg\jre21.0.4\bin\java.exe")
COPILOTE_LIB = Path(r"C:\Program Files\Infologic\Copilote\Copilote PROD\install\lib")
SERVICE_SCRIPT = APP_DIR / "send_order_service.groovy"
REQUEST_NUMBER = 89
COOKIE_SCAN_SCRIPT = BASE_DIR / "find-jsessionid-fast.ps1"
REQUEST_BODY_TEMPLATE = APP_DIR / "request_body_template.bin"
BASCO_PID_CACHE = APP_DIR / "basco-pid.txt"
SEARCH_CAPTURE_DIR = BASE_DIR / "erp-captures" / "recherche-commandes-20260625-104338" / "reconstructed"
SEARCH_TEMPLATE_NUMBER = "943637"

REQUIRED_COLUMNS = [
    "order_ref",
    "dossier",
    "client",
    "client_code",
    "date_livraison",
    "transport",
    "transport_code",
    "product_code",
    "product_label",
    "quantity",
    "unit",
]
STATUS_COLUMNS = ["statut", "http_status", "copilote_numero", "sent_at", "message"]
ALL_COLUMNS = REQUIRED_COLUMNS + STATUS_COLUMNS
PENDING_STATUSES = {"A_ENVOYE", "A_ENVOYER"}
TERMINAL_STATUSES = {"ENVOYE", "IGNORE"}
SEND_LOCK_PATH = APP_DIR / "send.lock"
UNSUPPORTED_UNITS = {"BID"}

# UI refresh validates many local proposals in one process.  Loading the same
# client/cadencier workbooks for every row made the read-only UI cache rebuild
# needlessly slow; the catalog remains immutable for the lifetime of a run.
_CATALOGS_CACHE = None

SUPPORTED_DOSSIER = "BASCO"
MIN_DELIVERY_DATE = date.today()


def read_xlsx_rows(path):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    if not path.exists():
        return []
    rows = []
    with ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in item.iter() if t.tag.endswith("}t")))
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        for row in root.findall("m:sheetData/m:row", ns):
            values = []
            expected_col = 1
            for cell in row.findall("m:c", ns):
                ref = cell.attrib.get("r", "")
                col_letters = "".join(ch for ch in ref if ch.isalpha())
                col_num = 0
                for ch in col_letters:
                    col_num = col_num * 26 + ord(ch.upper()) - ord("A") + 1
                while expected_col < col_num:
                    values.append("")
                    expected_col += 1
                raw = cell.find("m:v", ns)
                value = "" if raw is None else raw.text or ""
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                values.append(value.replace("_x000D_", "").strip())
                expected_col += 1
            rows.append(values)
    return rows


def load_catalogs():
    # La validation Copilote doit utiliser exactement le meme code canonique
    # actif que le predicteur (intersection info-clients / cadencier BASCO),
    # et non un ancien export telecharge independamment.
    global _CATALOGS_CACHE
    if _CATALOGS_CACHE is not None:
        return _CATALOGS_CACHE

    from extraire_informations import charger_cadencier, charger_clients

    clients_info = charger_clients()
    codes_cadencier = set(charger_cadencier())
    clients = {
        str(client.get("code_client") or "").strip().upper(): str(
            client.get("nom_client") or ""
        ).strip()
        for client in clients_info
        if str(client.get("code_client") or "").strip() in codes_cadencier
    }
    products = {}
    for row in read_xlsx_rows(PRODUCTS_XLSX)[1:]:
        if len(row) >= 4 and row[0] and row[3].strip().upper() == "ACTIF":
            products[row[0].strip().upper()] = row[1].strip()
    _CATALOGS_CACHE = (clients, products)
    return _CATALOGS_CACHE


def read_csv_file(path, delimiter=","):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delimiter))


def _safe_order_ref(audio_source, fallback):
    stem = Path(audio_source).stem if audio_source else ""
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-_.")
    return f"NC-{stem[:64]}" if stem else fallback


def is_nextcloud_order_ref(order_ref):
    return (order_ref or "").strip().upper().startswith("NC-")


def build_queue_rows_from_validated(validated_rows, existing_rows=None):
    existing_map = {}
    for row in existing_rows or []:
        key = (
            (row.get("order_ref") or "").strip(),
            (row.get("product_code") or "").strip().upper(),
            (row.get("quantity") or "").strip().replace(",", "."),
            (row.get("unit") or "").strip().upper(),
        )
        existing_map[key] = row

    grouped = defaultdict(list)
    for row in validated_rows:
        source = (row.get("audio_source") or "").strip()
        if source:
            grouped[source].append(row)

    queue_rows = []
    for index, (source, lines) in enumerate(
        sorted(grouped.items(), key=lambda item: ((item[1][0].get("run_id") or ""), item[0]))
    , start=1):
        order_ref = _safe_order_ref(source, f"NC-{index:03d}")
        for line in sorted(lines, key=lambda item: int(item.get("ordre_ligne") or 0)):
            product_code = (line.get("code_article") or "").strip().upper()
            quantity = (line.get("quantite") or "").strip().replace(",", ".")
            unit = (line.get("unite") or "").strip().upper()
            key = (order_ref, product_code, quantity, unit)
            existing = existing_map.get(key, {})
            full = {name: "" for name in ALL_COLUMNS}
            full.update(
                {
                    "order_ref": order_ref,
                    "dossier": SUPPORTED_DOSSIER,
                    "client": line.get("client_nom", ""),
                    "client_code": line.get("client_code", ""),
                    "date_livraison": line.get("date_livraison", ""),
                    "transport": "",
                    "transport_code": "",
                    "product_code": product_code,
                    "product_label": line.get("libelle_article", ""),
                    "quantity": quantity,
                    "unit": unit,
                    "statut": existing.get("statut") or "A_ENVOYER",
                    "http_status": existing.get("http_status", ""),
                    "copilote_numero": existing.get("copilote_numero", ""),
                    "sent_at": existing.get("sent_at", ""),
                    "message": existing.get("message", "") or "Extrait des audios Nextcloud",
                }
            )
            queue_rows.append(full)
    return queue_rows


def refresh_queue_from_validated(*, preserve_pending_nextcloud: bool = False):
    """Refresh the local, *unsent* Nextcloud proposal queue.

    This function never contacts Copilote.  ``preserve_pending_nextcloud`` is
    used by the unattended audio worker: that worker receives only the new
    audio(s) of one polling cycle, so it must retain earlier local proposals
    that have not been manually corrected or sent.
    """
    APP_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    validated_rows = read_csv_file(VALIDATED_CSV, delimiter=";")
    existing_rows = load_csv_raw(CSV_PATH) if CSV_PATH.exists() else []
    preserved_rows = [
        row
        for row in existing_rows
        if not is_nextcloud_order_ref(row.get("order_ref", ""))
    ]
    existing_nextcloud_groups = defaultdict(list)
    for row in existing_rows:
        order_ref = (row.get("order_ref") or "").strip()
        if is_nextcloud_order_ref(order_ref):
            existing_nextcloud_groups[order_ref].append(row)
    protected_refs = set()
    protected_nextcloud_rows = []
    for order_ref, grouped_rows in existing_nextcloud_groups.items():
        statuses = {(row.get("statut") or "").strip().upper() for row in grouped_rows}
        messages = " ".join(row.get("message", "") for row in grouped_rows)
        if statuses.intersection(TERMINAL_STATUSES) or "Corrige" in messages or "Correction" in messages:
            protected_refs.add(order_ref)
            protected_nextcloud_rows.extend(grouped_rows)
    queue_rows = build_queue_rows_from_validated(validated_rows, existing_rows=existing_rows)
    refreshed_refs = {
        (row.get("order_ref") or "").strip()
        for row in queue_rows
        if (row.get("order_ref") or "").strip()
    }
    if preserve_pending_nextcloud:
        for order_ref, grouped_rows in existing_nextcloud_groups.items():
            if order_ref in refreshed_refs or order_ref in protected_refs:
                continue
            protected_nextcloud_rows.extend(grouped_rows)
    queue_rows = [
        row
        for row in queue_rows
        if (row.get("order_ref") or "").strip() not in protected_refs
    ]
    merged_rows = preserved_rows + protected_nextcloud_rows + queue_rows
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ALL_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        if merged_rows:
            writer.writerows(merged_rows)
    return merged_rows


def load_csv_raw(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def ipv4(addr_bytes):
    return ".".join(str(b) for b in addr_bytes)


def parse_tcp_payload(frame):
    if len(frame) < 54 or frame[12:14] != b"\x08\x00":
        return None
    ip_start = 14
    version_ihl = frame[ip_start]
    if version_ihl >> 4 != 4:
        return None
    ihl = (version_ihl & 0x0F) * 4
    if ihl < 20 or len(frame) < ip_start + ihl + 20:
        return None
    total_len = int.from_bytes(frame[ip_start + 2 : ip_start + 4], "big")
    if frame[ip_start + 9] != 6:
        return None
    src_ip = ipv4(frame[ip_start + 12 : ip_start + 16])
    dst_ip = ipv4(frame[ip_start + 16 : ip_start + 20])
    tcp_start = ip_start + ihl
    src_port = int.from_bytes(frame[tcp_start : tcp_start + 2], "big")
    dst_port = int.from_bytes(frame[tcp_start + 2 : tcp_start + 4], "big")
    seq = int.from_bytes(frame[tcp_start + 4 : tcp_start + 8], "big")
    tcp_header_len = ((frame[tcp_start + 12] >> 4) & 0x0F) * 4
    if tcp_header_len < 20:
        return None
    payload_start = tcp_start + tcp_header_len
    ip_end = ip_start + total_len if total_len > 0 else len(frame)
    packet_end = min(len(frame), ip_end) if ip_end <= len(frame) else len(frame)
    if payload_start >= packet_end:
        return None
    payload = frame[payload_start:packet_end]
    if not payload:
        return None
    return src_ip, src_port, dst_ip, dst_port, seq, payload


def iter_fragments(capture_xml):
    rx = re.compile(r'<Data Name="Fragment">0x([0-9A-Fa-f]+)</Data>')
    with capture_xml.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            match = rx.search(line)
            if match:
                try:
                    yield bytes.fromhex(match.group(1))
                except ValueError:
                    pass


def build_client_streams(capture_xml, server, port):
    flows = {}
    for frame in iter_fragments(capture_xml):
        parsed = parse_tcp_payload(frame)
        if parsed is None:
            continue
        src_ip, src_port, dst_ip, dst_port, seq, payload = parsed
        if dst_ip != server or dst_port != port:
            continue
        key = (src_ip, src_port, dst_ip, dst_port)
        flows.setdefault(key, {})[seq] = payload
    return {key: b"".join(chunks[seq] for seq in sorted(chunks)) for key, chunks in flows.items()}


def parse_headers(header_bytes):
    text = header_bytes.decode("iso-8859-1", errors="replace")
    lines = text.split("\r\n")
    headers = {}
    for line in lines[1:]:
        if line and ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip()] = value.strip()
    return lines[0], headers, text


def iter_http_requests(stream):
    marker = b"POST /ventes/ProxyServlet HTTP/1.1"
    pos = 0
    while True:
        start = stream.find(marker, pos)
        if start < 0:
            return
        header_end = stream.find(b"\r\n\r\n", start)
        if header_end < 0:
            return
        header_bytes = stream[start : header_end + 4]
        _, headers, header_text = parse_headers(header_bytes)
        try:
            content_length = int(headers.get("Content-Length", "0"))
        except ValueError:
            pos = header_end + 4
            continue
        body_start = header_end + 4
        body_end = body_start + content_length
        if body_end > len(stream):
            return
        yield header_text, headers, stream[body_start:body_end]
        pos = body_end


def locate_captured_headers(body):
    body_hash = hashlib.sha256(body).hexdigest()
    for flow_key, stream in build_client_streams(CAPTURE_XML, SERVER, PORT).items():
        for _, headers, candidate_body in iter_http_requests(stream):
            if hashlib.sha256(candidate_body).hexdigest() == body_hash:
                return flow_key, headers
    raise RuntimeError("Impossible de retrouver les headers/cookie dans la capture SAICOM.")


def current_basco_session_cookie():
    pid_text = ""
    try:
        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        found = []

        def callback(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
            if title.upper().startswith("VENTES - BASCO"):
                proc_id = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
                found.append(str(proc_id.value))
                return False
            return True

        user32.EnumWindows(EnumWindowsProc(callback), 0)
        if found:
            pid_text = found[0]
    except Exception:
        pid_text = ""

    if not pid_text:
        pid_text = current_basco_session_cookie_powershell_pid()

    if pid_text:
        try:
            BASCO_PID_CACHE.write_text(pid_text + "\n", encoding="ascii")
        except OSError:
            pass
    elif BASCO_PID_CACHE.exists():
        cached_pid = BASCO_PID_CACHE.read_text(encoding="ascii", errors="ignore").strip()
        if cached_pid:
            alive = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Get-Process -Id {cached_pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            if alive == cached_pid:
                pid_text = cached_pid

    if not pid_text:
        raise RuntimeError("Aucune fenetre Copilote BASCO active trouvee.")

    scan_cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(COOKIE_SCAN_SCRIPT),
        "-TargetPid",
        pid_text,
        "-MaxMatches",
        "5",
    ]
    scan_result = subprocess.run(scan_cmd, capture_output=True, text=True, timeout=30)
    match = re.search(r"JSESSIONID=([A-Za-z0-9]+)", scan_result.stdout)
    if not match:
        raise RuntimeError("JSESSIONID introuvable dans la session Copilote BASCO.")
    return f"JSESSIONID={match.group(1)}"


def current_basco_session_cookie_powershell_pid():
    pid_cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Process javaw -ErrorAction SilentlyContinue | "
        "ForEach-Object { \"$($_.Id)|$($_.MainWindowTitle)\" }",
    ]
    pid_text = ""
    last_titles = ""
    for _ in range(5):
        pid_result = subprocess.run(pid_cmd, capture_output=True, text=True, timeout=20)
        last_titles = pid_result.stdout
        for line in pid_result.stdout.splitlines():
            if "|" not in line:
                continue
            pid, title = line.split("|", 1)
            if title.upper().startswith("VENTES - BASCO"):
                pid_text = pid.strip()
                break
        if pid_text:
            break
        time.sleep(0.2)
    return pid_text


def response_decoded(raw, response_headers):
    encoding = response_headers.get("content-encoding", "").lower()
    if raw.startswith(b"\x1f\x8b") or "gzip" in encoding:
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    return raw


def extract_number_candidates(decoded):
    return sorted(set(x.decode("ascii") for x in re.findall(rb"(?<!\d)\d{5,9}(?!\d)", decoded)))


def response_error(decoded):
    text = decoded.decode("iso-8859-1", errors="ignore")
    if "Not logged in" in text:
        return "SecurityException: Not logged in"
    if "SecurityException" in text:
        return "SecurityException"
    if "Exception" in text and "fr.infologic" in text:
        match = re.search(r"(?:detailMessage|t\.\.)([^.\x00-\x1f]{3,120})", text)
        return match.group(1).strip() if match else "Exception Copilote"
    return ""


def extract_service_error(stderr_text, stdout_text=""):
    combined = "\n".join(part for part in [stderr_text or "", stdout_text or ""] if part).strip()
    if not combined:
        return ""
    lines = [line.strip() for line in combined.splitlines() if line.strip()]

    article_line = ""
    for line in lines:
        if "pour l'article" in line:
            article_line = line
            break

    for index, line in enumerate(lines):
        if "ControleValidationException:" in line:
            message = line.split("ControleValidationException:", 1)[1].strip()
            extras = []
            for next_line in lines[index + 1:]:
                if next_line.startswith("at ") or next_line.startswith("fr.infologic.") or next_line.startswith("Caught:"):
                    break
                if next_line == message:
                    continue
                extras.append(next_line)
            parts = [message] + extras
            if article_line and article_line not in parts:
                parts.append(article_line)
            return " | ".join(parts)

    for line in lines:
        if line.startswith("Caught: "):
            return line.replace("Caught: ", "", 1).strip()

    for line in reversed(lines):
        if not line.startswith("at "):
            return line
    return combined


def load_csv():
    refresh_queue_from_validated()
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    for row in rows:
        for name in ALL_COLUMNS:
            row.setdefault(name, "")
    return rows


def save_csv(rows):
    last_error = None
    for attempt in range(5):
        try:
            with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=ALL_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.25 * (attempt + 1))

    tmp = CSV_PATH.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=ALL_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    except PermissionError as exc:
        last_error = exc
        raise RuntimeError(
            "CSV verrouille. Ferme Excel ou tout autre editeur ouvert sur commandes-copilote.csv "
            f"puis relance l'envoi. Detail: {last_error}"
        )

    for attempt in range(5):
        try:
            os.replace(tmp, CSV_PATH)
            return
        except PermissionError as exc:
            last_error = exc
            try:
                with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=ALL_COLUMNS, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
                try:
                    tmp.unlink()
                except OSError:
                    pass
                return
            except PermissionError as inner_exc:
                last_error = inner_exc
                time.sleep(0.25 * (attempt + 1))

    raise RuntimeError(
        "CSV verrouille. Ferme Excel ou tout autre editeur ouvert sur commandes-copilote.csv "
        f"puis relance l'envoi. Detail: {last_error}"
    )


def group_orders(rows):
    grouped = {}
    for index, row in enumerate(rows):
        order_ref = (row.get("order_ref") or "").strip()
        if not order_ref:
            continue
        grouped.setdefault(order_ref, []).append((index, row))
    return grouped


def order_signature(rows):
    rows = list(rows or [])
    if not rows:
        return None
    first = rows[0]
    client_code = (first.get("client_code") or "").strip().upper()
    delivery_date = (first.get("date_livraison") or "").strip()
    dossier = (first.get("dossier") or "").strip().upper()
    products = []
    for row in rows:
        products.append(
            (
                (row.get("product_code") or "").strip().upper(),
                (row.get("quantity") or "").strip().replace(",", "."),
                (row.get("unit") or "").strip().upper(),
            )
        )
    return dossier, client_code, delivery_date, tuple(sorted(products))


def find_duplicate_sent_order(order_ref, order_rows, all_rows):
    signature = order_signature(order_rows)
    if not signature:
        return None
    for existing_ref, indexed_rows in group_orders(all_rows).items():
        if existing_ref == order_ref:
            continue
        existing_rows = [row for _, row in indexed_rows]
        statuses = {normalize_status(row) for row in existing_rows}
        if "ENVOYE" not in statuses:
            continue
        if order_signature(existing_rows) != signature:
            continue
        first = existing_rows[0]
        return {
            "order_ref": existing_ref,
            "copilote_numero": (first.get("copilote_numero") or "").strip(),
            "sent_at": (first.get("sent_at") or "").strip(),
            "message": (first.get("message") or "").strip(),
        }
    return None


def normalize_status(row):
    return (row.get("statut") or "").strip().upper()


def is_supported_order_row(row):
    unit = (row.get("unit") or "").strip().upper()
    return unit not in UNSUPPORTED_UNITS


def parse_delivery_date(value):
    text = (value or "").strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"date_livraison invalide={text}; format attendu YYYY-MM-DD")


def acquire_send_lock():
    assert_erp_write_allowed("acquisition du verrou d'envoi")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(SEND_LOCK_PATH), flags)
    except FileExistsError:
        try:
            age_seconds = time.time() - SEND_LOCK_PATH.stat().st_mtime
        except OSError:
            age_seconds = 0
        if age_seconds > 3600:
            try:
                SEND_LOCK_PATH.unlink()
                fd = os.open(str(SEND_LOCK_PATH), flags)
            except OSError as exc:
                raise RuntimeError(f"Un autre envoi est deja en cours: {SEND_LOCK_PATH}") from exc
        else:
            raise RuntimeError(f"Un autre envoi est deja en cours: {SEND_LOCK_PATH}")
    os.write(fd, f"pid={os.getpid()} started_at={datetime.now().isoformat(timespec='seconds')}\n".encode("ascii"))
    return fd


def release_send_lock(fd):
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        SEND_LOCK_PATH.unlink()
    except OSError:
        pass


def validate_template(rows):
    clients, products = load_catalogs()
    errors = []
    for row in rows:
        dossier = (row.get("dossier") or "").strip().upper()
        if dossier != SUPPORTED_DOSSIER:
            errors.append(f"dossier attendu={SUPPORTED_DOSSIER} recu={dossier}")
        client_code = (row.get("client_code") or "").strip().upper()
        if client_code not in clients:
            errors.append(f"client_code inconnu={client_code}")
        product_code = (row.get("product_code") or "").strip().upper()
        if not product_code:
            errors.append("product_code manquant")
        elif product_code not in products:
            errors.append(f"product_code inactif ou inconnu={product_code}")
        date_livraison = (row.get("date_livraison") or "").strip()
        try:
            parsed_date = parse_delivery_date(date_livraison)
            if parsed_date < MIN_DELIVERY_DATE:
                errors.append("date_livraison dans le passe")
        except ValueError as exc:
            errors.append(str(exc))
        quantity = (row.get("quantity") or "").strip().replace(",", ".")
        try:
            if float(quantity) <= 0:
                errors.append(f"quantity doit etre positive: {quantity}")
        except ValueError:
            errors.append(f"quantity invalide: {quantity}")
    return errors


def send_service_request(order_ref, order_rows):
    assert_erp_write_allowed(
        "creation de commande par services Copilote",
        target=f"Copilote ERP order_ref={order_ref}",
    )
    if not JAVA_EXE.exists():
        raise RuntimeError(f"java.exe Copilote introuvable: {JAVA_EXE}")
    if not SERVICE_SCRIPT.exists():
        raise RuntimeError(f"Script service absent: {SERVICE_SCRIPT}")

    client_codes = {(row.get("client_code") or "").strip().upper() for row in order_rows}
    dates = {parse_delivery_date(row.get("date_livraison")).strftime("%Y-%m-%d") for row in order_rows}
    if len(client_codes) != 1:
        raise RuntimeError("Une commande CSV doit contenir un seul client_code")
    if len(dates) != 1:
        raise RuntimeError("Une commande CSV doit contenir une seule date_livraison")

    args = [
        str(JAVA_EXE),
        "-cp",
        str(COPILOTE_LIB / "*"),
        "groovy.ui.GroovyMain",
        str(SERVICE_SCRIPT),
        current_basco_session_cookie(),
        next(iter(client_codes)),
        next(iter(dates)),
        order_ref,
    ]
    for row in order_rows:
        product_code = (row.get("product_code") or "").strip().upper()
        quantity = (row.get("quantity") or "").strip().replace(",", ".")
        unit = (row.get("unit") or "").strip().upper() or "UB"
        if not product_code or not quantity:
            raise RuntimeError("product_code et quantity sont obligatoires")
        args.extend([product_code, quantity, unit])

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_ref = re.sub(r"[^A-Za-z0-9_.-]+", "_", order_ref)[:80] or "commande"
    out_dir = RUNS_DIR / f"{stamp}-{safe_ref}"
    logs_enabled = True
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_args = list(args)
        if len(safe_args) > 5:
            safe_args[5] = "JSESSIONID=<redacted>"
        (out_dir / "command.txt").write_text(" ".join(safe_args) + "\n", encoding="utf-8")
    except OSError:
        logs_enabled = False

    proc = subprocess.run(args, capture_output=True, text=True, timeout=180, cwd=str(APP_DIR))
    if logs_enabled:
        (out_dir / "stdout.txt").write_text(proc.stdout, encoding="utf-8", errors="replace")
        (out_dir / "stderr.txt").write_text(proc.stderr, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        detail = extract_service_error(proc.stderr, proc.stdout)
        raise RuntimeError(detail or f"Erreur service Copilote rc={proc.returncode}")

    match = re.search(r"ORDER_NUMBER=([0-9]+)", proc.stdout)
    if not match:
        raise RuntimeError("Commande creee sans numero retourne par le service")
    return 200, "SERVICE", [match.group(1)], out_dir, ""


def render_request_body(order_rows):
    if not REQUEST_BODY_TEMPLATE.exists():
        raise RuntimeError(f"Template HTTP absent: {REQUEST_BODY_TEMPLATE}")
    body = REQUEST_BODY_TEMPLATE.read_bytes()
    if not body.startswith(b"\x1f\x8b"):
        raise RuntimeError("Template HTTP invalide: compression gzip attendue")
    decoded = gzip.decompress(body).decode("latin1", errors="ignore")
    template_code = "00111903"
    if template_code not in decoded:
        raise RuntimeError(f"Code produit template introuvable: {template_code}")
    target_codes = [((row.get("product_code") or "").strip()) for row in order_rows if (row.get("product_code") or "").strip()]
    if not target_codes:
        raise RuntimeError("Aucun code produit fourni dans le CSV")
    target_code = target_codes[0]
    if len(target_codes) > 1:
        raise RuntimeError("Le POC direct ne gere encore qu'une seule ligne par commande")
    if len(target_code) != len(template_code):
        raise RuntimeError(
            f"product_code incompatible: template={template_code} cible={target_code}"
        )
    if template_code not in decoded:
        raise RuntimeError(f"Code produit template introuvable: {template_code}")
    decoded = decoded.replace(template_code, target_code)
    return gzip.compress(decoded.encode("latin1", errors="ignore"))


def send_direct_request(order_ref, order_rows):
    assert_erp_write_allowed(
        "rejeu HTTP direct de creation de commande",
        target=f"Copilote ERP order_ref={order_ref}",
    )
    template_body = REQUEST_BODY_TEMPLATE.read_bytes()
    flow_key, captured_headers = locate_captured_headers(template_body)
    body = render_request_body(order_rows)
    required = ["Content-Type", "Content-Encoding", "X-Prop-ServiceSource", "Cookie"]
    missing = [name for name in required if not captured_headers.get(name)]
    if missing:
        raise RuntimeError("Headers manquants: " + ", ".join(missing))

    headers = {
        "Content-Type": captured_headers.get("Content-Type", "application/octet-stream"),
        "Accept": captured_headers.get("Accept", "application/octet-stream, text/html, *; q=.2, */*; q=.2"),
        "Content-Encoding": captured_headers.get("Content-Encoding", "gzip"),
        "Accept-Encoding": captured_headers.get("Accept-Encoding", "gzip"),
        "X-Prop-LongServiceCall": captured_headers.get("X-Prop-LongServiceCall", "1"),
        "X-Prop-SaisieId": captured_headers.get("X-Prop-SaisieId", "6"),
        "X-Prop-ServiceSource": captured_headers.get("X-Prop-ServiceSource"),
        "Cookie": current_basco_session_cookie(),
        "Cache-Control": captured_headers.get("Cache-Control", "no-cache"),
        "Pragma": captured_headers.get("Pragma", "no-cache"),
        "User-Agent": captured_headers.get("User-Agent", "Java/21.0.4"),
    }

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_ref = re.sub(r"[^A-Za-z0-9_.-]+", "_", order_ref)[:80] or "commande"
    out_dir = RUNS_DIR / f"{stamp}-{safe_ref}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "request_body.bin").write_bytes(body)
    (out_dir / "request_headers_redacted.txt").write_text(
        "\n".join(f"{k}: {'<redacted>' if k.lower() == 'cookie' else v}" for k, v in headers.items()) + "\n",
        encoding="utf-8",
    )
    (out_dir / "flow.txt").write_text(f"{flow_key}\n", encoding="utf-8")

    connection = http.client.HTTPConnection(SERVER, PORT, timeout=90)
    try:
        connection.request("POST", "/ventes/ProxyServlet", body=body, headers=headers)
        response = connection.getresponse()
        raw_response = response.read()
        response_headers = {k.lower(): v for k, v in response.getheaders()}
    finally:
        connection.close()

    decoded = response_decoded(raw_response, response_headers)
    candidates = extract_number_candidates(decoded)
    error = response_error(decoded)
    (out_dir / "response_body.bin").write_bytes(raw_response)
    (out_dir / "response_body_decoded.bin").write_bytes(decoded)
    (out_dir / "response_headers.txt").write_text(
        "\n".join(f"{k}: {v}" for k, v in response_headers.items()) + "\n",
        encoding="utf-8",
    )
    (out_dir / "summary.txt").write_text(
        "\n".join(
            [
                f"order_ref={order_ref}",
                f"status={response.status} {response.reason}",
                f"copilote_candidates={','.join(candidates)}",
                f"error={error}",
                f"output_dir={out_dir}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return response.status, response.reason, candidates, out_dir, error


def read_reconstructed_headers(path):
    headers = {}
    if not path.exists():
        return headers
    for raw_line in path.read_text(encoding="iso-8859-1", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line or line.upper().startswith("POST "):
            continue
        name, value = line.split(":", 1)
        headers[name.strip()] = value.strip()
    return headers


def verify_order_in_search(order_number):
    order_number = str(order_number or "").strip()
    if not re.fullmatch(r"\d{6}", order_number):
        return False, "numero Copilote non compatible avec le template de recherche", ""

    template_decoded_path = SEARCH_CAPTURE_DIR / "request_074_body_decoded.bin"
    template_headers_path = SEARCH_CAPTURE_DIR / "request_074_headers.txt"
    if not template_decoded_path.exists() or not template_headers_path.exists():
        return False, "capture recherche Copilote absente", ""

    decoded = template_decoded_path.read_bytes()
    source = SEARCH_TEMPLATE_NUMBER.encode("ascii")
    target = order_number.encode("ascii")
    if source not in decoded:
        return False, "numero template introuvable dans la capture recherche", ""
    body = gzip.compress(decoded.replace(source, target))
    captured_headers = read_reconstructed_headers(template_headers_path)
    service_source = captured_headers.get(
        "X-Prop-ServiceSource",
        "fr.infologic.infoc.client.tableaubord.TableauBordPart$12$1.run (TableauBordPart.java:1645)",
    )
    headers = {
        "Content-Type": captured_headers.get("Content-Type", "application/octet-stream"),
        "Accept": captured_headers.get("Accept", "application/octet-stream, text/html, *; q=.2, */*; q=.2"),
        "Content-Encoding": captured_headers.get("Content-Encoding", "gzip"),
        "Accept-Encoding": captured_headers.get("Accept-Encoding", "gzip"),
        "X-Prop-LongServiceCall": captured_headers.get("X-Prop-LongServiceCall", "1"),
        "X-Prop-progressMonitorFrequency": captured_headers.get("X-Prop-progressMonitorFrequency", "-1"),
        "X-Prop-progressMonitorId": captured_headers.get("X-Prop-progressMonitorId", "1"),
        "X-Prop-SaisieId": captured_headers.get("X-Prop-SaisieId", ""),
        "X-Prop-ServiceSource": service_source,
        "Cookie": current_basco_session_cookie(),
        "Cache-Control": captured_headers.get("Cache-Control", "no-cache"),
        "Pragma": captured_headers.get("Pragma", "no-cache"),
        "User-Agent": captured_headers.get("User-Agent", "Java/21.0.4"),
    }

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = RUNS_DIR / f"{stamp}-verify-{order_number}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "request_body.bin").write_bytes(body)
    (out_dir / "request_headers_redacted.txt").write_text(
        "\n".join(f"{k}: {'<redacted>' if k.lower() == 'cookie' else v}" for k, v in headers.items()) + "\n",
        encoding="utf-8",
    )

    connection = http.client.HTTPConnection(SERVER, PORT, timeout=90)
    try:
        connection.request("POST", "/ventes/ProxyServlet", body=body, headers=headers)
        response = connection.getresponse()
        raw_response = response.read()
        response_headers = {k.lower(): v for k, v in response.getheaders()}
    finally:
        connection.close()

    decoded_response = response_decoded(raw_response, response_headers)
    error = response_error(decoded_response)
    found = target in decoded_response and not error and 200 <= response.status < 300
    (out_dir / "response_body.bin").write_bytes(raw_response)
    (out_dir / "response_body_decoded.bin").write_bytes(decoded_response)
    (out_dir / "response_headers.txt").write_text(
        "\n".join(f"{k}: {v}" for k, v in response_headers.items()) + "\n",
        encoding="utf-8",
    )
    (out_dir / "summary.txt").write_text(
        "\n".join(
            [
                f"order_number={order_number}",
                f"status={response.status} {response.reason}",
                f"found={found}",
                f"error={error}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    if found:
        return True, f"commande {order_number} trouvee en recherche Copilote", str(out_dir)
    return False, error or f"commande {order_number} non retrouvee dans la reponse recherche", str(out_dir)


_TkBase = tk.Tk if tk is not None else object


class App(_TkBase):
    def __init__(self):
        super().__init__()
        refresh_queue_from_validated()
        self.title("POC commandes Copilote - requetes directes")
        self.geometry("1180x680")
        self.rows = []
        self.last_mtime = None
        self.sending = False
        self._build_ui()
        self.refresh_from_csv()
        self.after(1000, self.watch_csv)

    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill=tk.X)
        ttk.Label(top, text=f"CSV surveille: {CSV_PATH}").pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.send_button = ttk.Button(
            top,
            text="envoyer les commandes a copilote",
            command=self.send_pending_orders,
        )
        self.send_button.pack(side=tk.RIGHT)

        columns = ["order_ref", "dossier", "client_code", "date_livraison", "product_code", "quantity", "statut", "copilote_numero", "message"]
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=18)
        for col in columns:
            self.tree.heading(col, text=col)
            width = 130
            if col == "message":
                width = 260
            if col == "product_code":
                width = 110
            self.tree.column(col, width=width, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        log_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        log_frame.pack(fill=tk.BOTH)
        ttk.Label(log_frame, text="Journal").pack(anchor=tk.W)
        self.log_text = tk.Text(log_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def log(self, text):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{stamp}] {text}\n")
        self.log_text.see(tk.END)

    def refresh_from_csv(self):
        try:
            self.rows = load_csv()
            self.last_mtime = CSV_PATH.stat().st_mtime
            self.tree.delete(*self.tree.get_children())
            for row in self.rows:
                self.tree.insert(
                    "",
                    tk.END,
                    values=[
                        row.get("order_ref", ""),
                        row.get("dossier", ""),
                        row.get("client_code", ""),
                        row.get("date_livraison", ""),
                        row.get("product_code", ""),
                        row.get("quantity", ""),
                        row.get("statut", ""),
                        row.get("copilote_numero", ""),
                        row.get("message", ""),
                    ],
                )
        except Exception as exc:
            self.log(f"Erreur lecture CSV: {exc}")

    def watch_csv(self):
        try:
            mtime = CSV_PATH.stat().st_mtime
            if self.last_mtime is None or mtime != self.last_mtime:
                self.refresh_from_csv()
                self.log("CSV recharge.")
        except Exception as exc:
            self.log(f"Erreur surveillance CSV: {exc}")
        self.after(1000, self.watch_csv)

    def send_pending_orders(self):
        if self.sending:
            return
        self.sending = True
        self.send_button.configure(state=tk.DISABLED)
        thread = threading.Thread(target=self._send_worker, daemon=True)
        thread.start()

    def _send_worker(self):
        lock_fd = None
        try:
            try:
                lock_fd = acquire_send_lock()
            except Exception as exc:
                self.after(0, lambda m=str(exc): self.log(m))
                return

            rows = load_csv()
            groups = group_orders(rows)
            pending = []
            for order_ref, indexed_rows in groups.items():
                statuses = [normalize_status(row) for _, row in indexed_rows]
                if statuses and all(status in TERMINAL_STATUSES for status in statuses):
                    continue
                if any(status in TERMINAL_STATUSES for status in statuses):
                    msg = "Commande deja partiellement traitee: corriger le CSV avant renvoi"
                    for index, row in indexed_rows:
                        if normalize_status(row) not in TERMINAL_STATUSES:
                            rows[index]["statut"] = "ERREUR"
                            rows[index]["message"] = msg
                    save_csv(rows)
                    self.after(0, lambda ref=order_ref, m=msg: self.log(f"{ref}: {m}"))
                    continue
                if all(status in PENDING_STATUSES for status in statuses):
                    pending.append((order_ref, indexed_rows))

            if not pending:
                self.after(0, lambda: self.log("Aucune commande a envoyer."))
                return

            for order_ref, indexed_rows in pending:
                status = None
                order_rows = [row for _, row in indexed_rows]
                errors = validate_template(order_rows)
                if errors:
                    msg = "Commande CSV invalide: " + " | ".join(errors[:3])
                    for index, _ in indexed_rows:
                        rows[index]["statut"] = "ERREUR"
                        rows[index]["message"] = msg
                    save_csv(rows)
                    self.after(0, lambda ref=order_ref, m=msg: self.log(f"{ref}: {m}"))
                    continue

                self.after(0, lambda ref=order_ref: self.log(f"{ref}: envoi services Copilote..."))
                try:
                    status, reason, candidates, out_dir, error = send_service_request(order_ref, order_rows)
                    number = candidates[-1] if candidates else ""
                    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    message = f"HTTP {status} {reason}; logs={out_dir}"
                    if error:
                        message = f"{error}; {message}"
                    final_status = "ENVOYE" if 200 <= status < 300 and not error else "ERREUR"
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
                try:
                    save_csv(rows)
                except Exception as exc:
                    final_status = "ERREUR"
                    message = f"CSV update failed: {exc}"
                    for index, _ in indexed_rows:
                        rows[index]["statut"] = final_status
                        rows[index]["message"] = message
                    self.after(0, lambda ref=order_ref, m=message: self.log(f"{ref}: {m}"))
                    continue
                self.after(0, lambda ref=order_ref, st=final_status, num=number, msg=message: self.log(f"{ref}: {st} {num} {msg}"))
                time.sleep(0.3)
        finally:
            if lock_fd is not None:
                release_send_lock(lock_fd)
            self.after(0, self.refresh_from_csv)
            self.after(0, lambda: self.send_button.configure(state=tk.NORMAL))
            self.sending = False


if __name__ == "__main__":
    App().mainloop()
