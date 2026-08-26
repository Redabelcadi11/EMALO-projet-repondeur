from __future__ import annotations

import argparse
import json
import mimetypes
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from prod_audio_state import audio_key
from src.runtime_paths import bootstrap_runtime_environment, get_project_root


PROJECT_ROOT = bootstrap_runtime_environment()
RENDERER_DIR = PROJECT_ROOT / "app-desktop" / "renderer"
UI_DATA_PATH = PROJECT_ROOT / "cache" / "ui" / "repondeur-data-prod.json"


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def send_bytes(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: bytes,
    content_type: str,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    # The operator UI is a live view of a shared cache written by the
    # unattended worker.  Never let a browser keep an obsolete HTML/JSON
    # response after a new batch has completed.
    handler.send_header("Cache-Control", "no-store, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    send_bytes(
        handler,
        status,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "application/json; charset=utf-8",
    )


def generate_ui_data_if_missing() -> None:
    if UI_DATA_PATH.exists():
        return
    from generer_ui_data_prod import main as generate_prod_ui_data

    generate_prod_ui_data()


def read_ui_data() -> dict[str, Any]:
    generate_ui_data_if_missing()
    if not UI_DATA_PATH.exists():
        return {}
    return json.loads(UI_DATA_PATH.read_text(encoding="utf-8"))


def run_bridge(args: list[str]) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        str(PROJECT_ROOT / "electron_bridge.py"),
        *args,
    ]
    completed = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
        timeout=7200,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    last = lines[-1] if lines else "{}"
    try:
        payload = json.loads(last)
    except json.JSONDecodeError:
        payload = {
            "ok": completed.returncode == 0,
            "message": completed.stdout.strip() or completed.stderr.strip(),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    payload.setdefault("code", completed.returncode)
    if completed.stderr and "stderr" not in payload:
        payload["stderr"] = completed.stderr
    return payload


def audio_path_for_key(key: str) -> Path | None:
    from prod_pipeline import all_nextcloud_audios

    wanted = audio_key(key)
    for path in all_nextcloud_audios():
        if audio_key(path.name) == wanted or audio_key(path) == wanted:
            return path
    return None


class RepondeurHandler(BaseHTTPRequestHandler):
    server_version = "ProjetRepondeurWeb/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in {"", "/"}:
            path = "/prod.html"

        if path == "/api/ui-data":
            try:
                send_json(self, 200, read_ui_data())
            except Exception as exc:
                send_json(self, 500, {"ok": False, "message": str(exc)})
            return

        if path.startswith("/api/audio/"):
            key = path.rsplit("/", 1)[-1]
            audio_path = audio_path_for_key(key)
            if audio_path is None or not audio_path.exists():
                send_json(self, 404, {"ok": False, "message": "Audio introuvable"})
                return
            content_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
            send_bytes(self, 200, audio_path.read_bytes(), content_type)
            return

        relative = path.lstrip("/")
        file_path = (RENDERER_DIR / relative).resolve()
        renderer_root = RENDERER_DIR.resolve()
        if renderer_root not in file_path.parents and file_path != renderer_root:
            send_json(self, 403, {"ok": False, "message": "Chemin interdit"})
            return
        if not file_path.exists() or not file_path.is_file():
            send_json(self, 404, {"ok": False, "message": "Fichier introuvable"})
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        send_bytes(self, 200, file_path.read_bytes(), content_type)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            send_json(self, 404, {"ok": False, "message": "Endpoint inconnu"})
            return
        try:
            payload = read_json_body(self)
            args = payload.get("args")
            if not isinstance(args, list):
                raise ValueError("args doit etre une liste")
            result = run_bridge([str(item) for item in args])
            send_json(self, 200, result)
        except Exception as exc:
            send_json(self, 500, {"ok": False, "message": str(exc)})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()
    generate_ui_data_if_missing()
    server = ThreadingHTTPServer((args.host, args.port), RepondeurHandler)
    print(f"Repondeur web ecoute sur http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
