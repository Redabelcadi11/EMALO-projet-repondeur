from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from extraire_informations import charger_clients
from prod_pipeline import persist_analysis_details
from src.clients import (
    charger_telephones_clients,
    enrichir_clients_avec_telephones,
    normaliser_telephone,
)
import worker_client


AUDIO_ROOT = PROJECT_ROOT / "ressources-originales" / "audio-nextcloud"
PHONE_CONFIG = PROJECT_ROOT / "config" / "telephones-clients.json"
AUDIO_DATE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})"
)
PHONE_RE = re.compile(r"_De-([^_.]+)", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare en lecture seule les commandes produites avec un export "
            "Copilote ES. Aucun envoi Copilote n'est possible dans ce script."
        )
    )
    parser.add_argument("--truth-csv", required=True)
    parser.add_argument("--audio-from", required=True, help="ISO YYYY-MM-DDTHH:MM:SS")
    parser.add_argument("--audio-to", required=True, help="ISO YYYY-MM-DDTHH:MM:SS")
    parser.add_argument("--run-remote", action="store_true")
    parser.add_argument("--force-transcription", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--holdout-percent", type=int, default=30)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--output-dir", default="")
    return parser.parse_args()


def audio_datetime(path: Path) -> datetime | None:
    match = AUDIO_DATE_RE.match(path.name)
    if not match:
        return None
    return datetime.strptime(
        f"{match.group('date')} {match.group('hour')}:{match.group('minute')}:{match.group('second')}",
        "%Y-%m-%d %H:%M:%S",
    )


def caller_phone(path: Path) -> str:
    match = PHONE_RE.search(path.name)
    return normaliser_telephone(match.group(1)) if match else ""


def unique_phone_clients() -> dict[str, str]:
    clients = charger_clients()
    enrichir_clients_avec_telephones(
        clients,
        charger_telephones_clients(PHONE_CONFIG),
    )
    codes_by_phone: dict[str, set[str]] = defaultdict(set)
    for client in clients:
        code = str(client.get("code_client") or "").strip()
        for value in client.get("telephones") or []:
            phone = normaliser_telephone(value)
            if phone and code:
                codes_by_phone[phone].add(code)
    return {
        phone: next(iter(codes))
        for phone, codes in codes_by_phone.items()
        if len(codes) == 1
    }


def read_truth(path: Path) -> dict[str, dict[str, Any]]:
    orders: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            number = str(row.get("order_number") or "").strip()
            if not number:
                continue
            order = orders.setdefault(
                number,
                {
                    "order_number": number,
                    "client_code": str(row.get("client_code") or "").strip(),
                    "delivery_date": date_iso(row.get("delivery_date")),
                    "order_date": date_iso(row.get("order_date")),
                    "departure_date": date_iso(row.get("departure_date")),
                    "lines": [],
                    "errors": [],
                },
            )
            error = str(row.get("error") or "").strip()
            if error:
                order["errors"].append(error)
            article = normalize_code(row.get("article_code"))
            if article:
                order["lines"].append(
                    {
                        "code": article,
                        "quantity": normalize_quantity(row.get("quantity")),
                        "unit": normalize_unit(row.get("unit")),
                    }
                )
    return {
        number: order
        for number, order in orders.items()
        if not order["errors"] and order["lines"]
    }


def date_iso(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def normalize_code(value: Any) -> str:
    text = str(value or "").strip()
    if "|" in text:
        text = text.split("|", 1)[0].strip()
    return text.upper()


def normalize_quantity(value: Any) -> str:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return ""
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text.upper()
    normalized = format(number.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def normalize_unit(value: Any) -> str:
    return str(value or "").strip().upper()


def prediction_lines(command: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "code": normalize_code(line.get("code_article")),
            "quantity": normalize_quantity(line.get("quantite")),
            "unit": normalize_unit(line.get("unite")),
        }
        for line in command.get("lignes_commande") or []
        if normalize_code(line.get("code_article"))
    ]


def select_pairs(
    truth: dict[str, dict[str, Any]],
    start: datetime,
    end: datetime,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    phone_clients = unique_phone_clients()
    audios_by_client: dict[str, list[Path]] = defaultdict(list)
    scanned = 0
    mapped = 0
    for path in sorted(AUDIO_ROOT.glob("*")):
        when = audio_datetime(path)
        if when is None or when < start or when > end:
            continue
        scanned += 1
        code = phone_clients.get(caller_phone(path), "")
        if code:
            mapped += 1
            audios_by_client[code].append(path)

    orders_by_client: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in truth.values():
        code = str(order.get("client_code") or "").strip()
        if code:
            orders_by_client[code].append(order)

    pairs = []
    for code in sorted(set(audios_by_client) & set(orders_by_client)):
        audios = audios_by_client[code]
        orders = orders_by_client[code]
        if len(audios) != 1 or len(orders) != 1:
            continue
        pairs.append(
            {
                "audio": audios[0],
                "truth": orders[0],
                "phone_client_code": code,
            }
        )
    return pairs, {
        "audios_scanned": scanned,
        "audios_with_unambiguous_phone": mapped,
        "truth_orders": len(truth),
        "strict_one_to_one_pairs": len(pairs),
    }


def split_for(name: str, holdout_percent: int) -> str:
    bucket = int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16) % 100
    return "holdout" if bucket < holdout_percent else "calibration"


def counter_intersection_size(left: Counter[Any], right: Counter[Any]) -> int:
    return sum((left & right).values())


def evaluate_pair(
    audio: Path,
    truth: dict[str, Any],
    command: dict[str, Any],
    split: str,
    elapsed: float,
) -> dict[str, Any]:
    truth_lines = list(truth.get("lines") or [])
    predicted_lines = prediction_lines(command)
    truth_codes = Counter(line["code"] for line in truth_lines)
    predicted_codes = Counter(line["code"] for line in predicted_lines)
    truth_exact = Counter(
        (line["code"], line["quantity"], line["unit"])
        for line in truth_lines
    )
    predicted_exact = Counter(
        (line["code"], line["quantity"], line["unit"])
        for line in predicted_lines
    )
    code_matches = counter_intersection_size(truth_codes, predicted_codes)
    exact_matches = counter_intersection_size(truth_exact, predicted_exact)
    predicted_client = str(command.get("client_retenu") or "").strip()
    delivery = command.get("date_livraison")
    predicted_date = date_iso(
        delivery.get("date_iso") if isinstance(delivery, dict) else delivery
    )
    client_ok = predicted_client == truth["client_code"]
    date_ok = predicted_date == truth["delivery_date"]
    codes_ok = truth_codes == predicted_codes
    lines_ok = truth_exact == predicted_exact
    perfect = client_ok and date_ok and lines_ok
    return {
        "audio": audio.name,
        "split": split,
        "truth_order_number": truth["order_number"],
        "truth_client": truth["client_code"],
        "predicted_client": predicted_client,
        "client_ok": client_ok,
        "truth_delivery_date": truth["delivery_date"],
        "predicted_delivery_date": predicted_date,
        "date_ok": date_ok,
        "truth_lines": truth_lines,
        "predicted_lines": predicted_lines,
        "truth_line_count": len(truth_lines),
        "predicted_line_count": len(predicted_lines),
        "code_matches": code_matches,
        "exact_line_matches": exact_matches,
        "product_codes_ok": codes_ok,
        "lines_ok": lines_ok,
        "perfect_order": perfect,
        "program_status": command.get("statut", ""),
        "problem_reasons": command.get("raisons_problematiques", []),
        "remote_elapsed_seconds": round(elapsed, 3),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"orders": 0}
    truth_lines = sum(row["truth_line_count"] for row in rows)
    predicted_lines = sum(row["predicted_line_count"] for row in rows)
    code_matches = sum(row["code_matches"] for row in rows)
    exact_matches = sum(row["exact_line_matches"] for row in rows)
    code_precision = code_matches / predicted_lines if predicted_lines else 0.0
    code_recall = code_matches / truth_lines if truth_lines else 0.0
    exact_precision = exact_matches / predicted_lines if predicted_lines else 0.0
    exact_recall = exact_matches / truth_lines if truth_lines else 0.0
    return {
        "orders": len(rows),
        "truth_lines": truth_lines,
        "predicted_lines": predicted_lines,
        "client_accuracy": round(statistics.fmean(row["client_ok"] for row in rows), 4),
        "delivery_date_accuracy": round(statistics.fmean(row["date_ok"] for row in rows), 4),
        "product_code_precision": round(code_precision, 4),
        "product_code_recall": round(code_recall, 4),
        "exact_line_precision": round(exact_precision, 4),
        "exact_line_recall": round(exact_recall, 4),
        "product_set_accuracy": round(statistics.fmean(row["product_codes_ok"] for row in rows), 4),
        "exact_lines_order_accuracy": round(statistics.fmean(row["lines_ok"] for row in rows), 4),
        "strict_order_accuracy": round(statistics.fmean(row["perfect_order"] for row in rows), 4),
        "average_remote_elapsed_seconds": round(
            statistics.fmean(row["remote_elapsed_seconds"] for row in rows), 3
        ),
    }


def main() -> int:
    args = parse_args()
    truth_path = Path(args.truth_csv).expanduser().resolve()
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else PROJECT_ROOT / "resultats" / "evaluation-copilote"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    truth = read_truth(truth_path)
    pairs, coverage = select_pairs(
        truth,
        datetime.fromisoformat(args.audio_from),
        datetime.fromisoformat(args.audio_to),
    )
    if args.limit > 0:
        pairs = pairs[: args.limit]
    if not pairs:
        raise RuntimeError("Aucune paire audio/commande stricte disponible.")
    if not args.run_remote:
        raise RuntimeError("Utiliser --run-remote pour produire une evaluation fraiche.")

    rows = []
    started_total = time.perf_counter()
    for index, pair in enumerate(pairs, start=1):
        audio = pair["audio"]
        started = time.perf_counter()
        result = worker_client.remote_analyze_audio(
            audio,
            force=bool(args.force_transcription),
        )
        elapsed = time.perf_counter() - started
        if not result.get("ok"):
            raise RuntimeError(f"{audio.name}: {result.get('message', 'erreur worker')}")
        worker_client.write_remote_transcription(audio, result)
        commands = result.get("commandes")
        if not isinstance(commands, list) or len(commands) != 1:
            command = {
                "client_retenu": "",
                "date_livraison": {},
                "lignes_commande": [],
                "statut": "PROBLEMATIQUE",
                "raisons_problematiques": [
                    f"nombre_commandes_retournees={len(commands) if isinstance(commands, list) else 0}"
                ],
            }
        else:
            command = commands[0]
            persist_analysis_details(commands)
        row = evaluate_pair(
            audio,
            pair["truth"],
            command,
            split_for(audio.name, args.holdout_percent),
            elapsed,
        )
        rows.append(row)
        print(
            f"[{index}/{len(pairs)}] {audio.name}: "
            f"client={int(row['client_ok'])} date={int(row['date_ok'])} "
            f"articles={row['code_matches']}/{row['truth_line_count']} "
            f"parfaite={int(row['perfect_order'])}",
            flush=True,
        )

    metrics = {
        "all": aggregate(rows),
        "calibration": aggregate([row for row in rows if row["split"] == "calibration"]),
        "holdout": aggregate([row for row in rows if row["split"] == "holdout"]),
    }
    report = {
        "generated_at": datetime.now().isoformat(),
        "label": args.label,
        "truth_csv": str(truth_path),
        "audio_from": args.audio_from,
        "audio_to": args.audio_to,
        "force_transcription": bool(args.force_transcription),
        "copilote_mode": "read_only_export",
        "copilote_send_attempted": False,
        "coverage": coverage,
        "metrics": metrics,
        "elapsed_seconds": round(time.perf_counter() - started_total, 3),
        "orders": rows,
    }
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"evaluation_{args.label}_{timestamp}.json"
    csv_path = output_dir / f"evaluation_{args.label}_{timestamp}.csv"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        columns = [
            "audio",
            "split",
            "truth_order_number",
            "client_ok",
            "date_ok",
            "truth_line_count",
            "predicted_line_count",
            "code_matches",
            "exact_line_matches",
            "product_codes_ok",
            "lines_ok",
            "perfect_order",
            "program_status",
            "remote_elapsed_seconds",
        ]
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
    print("METRICS=" + json.dumps(metrics, ensure_ascii=False), flush=True)
    print(f"JSON={json_path}", flush=True)
    print(f"CSV={csv_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
