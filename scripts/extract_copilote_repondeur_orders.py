#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import copilote_integration as copilote


DEFAULT_CAPTURE_DIR = copilote.SEARCH_CAPTURE_DIR
DEFAULT_HEADER_TEMPLATE = DEFAULT_CAPTURE_DIR / "request_074_body_decoded.bin"
DEFAULT_LINE_TEMPLATE = DEFAULT_CAPTURE_DIR / "request_077_body_decoded.bin"
DEFAULT_PERIODIC_LINE_TEMPLATE = DEFAULT_CAPTURE_DIR / "request_078_body_decoded.bin"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "resultats" / "copilote-replay"
WORKER_SCRIPT = PROJECT_ROOT / "copilote" / "extract_repondeur_orders.groovy"


def today_fr() -> str:
    return date.today().strftime("%d/%m/%Y")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrait les commandes Copilote du repondeur par replay HTTP."
    )
    parser.add_argument("--date-from", default=today_fr(), help="Date depart debut, format JJ/MM/AAAA.")
    parser.add_argument("--date-to", default="", help="Date depart fin, format JJ/MM/AAAA. Defaut: date-from.")
    parser.add_argument("--operator", default="ES", help="Operateur Copilote a extraire. Utiliser ALL pour tout.")
    parser.add_argument("--output", default="", help="CSV de sortie. Defaut: resultats/copilote-replay/...")
    parser.add_argument("--header-template", default=str(DEFAULT_HEADER_TEMPLATE))
    parser.add_argument("--line-template", default=str(DEFAULT_LINE_TEMPLATE))
    parser.add_argument("--periodic-line-template", default=str(DEFAULT_PERIODIC_LINE_TEMPLATE))
    parser.add_argument("--java", default=str(copilote.JAVA_EXE))
    parser.add_argument("--copilote-lib", default=str(copilote.COPILOTE_LIB))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    date_to = args.date_to or args.date_from
    output = Path(args.output) if args.output else (
        DEFAULT_OUTPUT_DIR / f"commandes_repondeur_{datetime.now():%Y%m%d_%H%M%S}.csv"
    )

    required_paths = [
        Path(args.header_template),
        Path(args.line_template),
        Path(args.periodic_line_template),
        Path(args.java),
        Path(args.copilote_lib),
        WORKER_SCRIPT,
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        print("Fichiers requis introuvables:", file=sys.stderr)
        for path in missing:
            print(f"- {path}", file=sys.stderr)
        return 2

    cookie = copilote.current_basco_session_cookie()
    cmd = [
        str(args.java),
        "-cp",
        str(Path(args.copilote_lib) / "*"),
        "groovy.ui.GroovyMain",
        str(WORKER_SCRIPT),
        cookie,
        str(Path(args.header_template)),
        str(Path(args.line_template)),
        args.date_from,
        date_to,
        args.operator,
        str(output),
        str(Path(args.periodic_line_template)),
    ]
    safe_cmd = list(cmd)
    if len(safe_cmd) > 5:
        safe_cmd[5] = "JSESSIONID=<redacted>"

    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DEFAULT_OUTPUT_DIR / f"extract_repondeur_{datetime.now():%Y%m%d_%H%M%S}.log"
    log_path.write_text(" ".join(safe_cmd) + "\n", encoding="utf-8")

    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
        timeout=900,
    )
    with log_path.open("a", encoding="utf-8", errors="replace") as fh:
        fh.write("\n--- stdout ---\n")
        fh.write(proc.stdout)
        fh.write("\n--- stderr ---\n")
        fh.write(proc.stderr)

    if proc.stdout:
        print(proc.stdout, end="")
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr, file=sys.stderr, end="")
        print(f"LOG={log_path}", file=sys.stderr)
        return proc.returncode

    print(f"LOG={log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
