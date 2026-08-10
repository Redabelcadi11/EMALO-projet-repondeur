from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from src.runtime_paths import get_project_root


PROJECT_ROOT = get_project_root()
CONFIG_PATH = PROJECT_ROOT / "config" / "worker.json"
_TUNNEL_PROCESS: subprocess.Popen[bytes] | None = None


def load_worker_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {}

    env_url = os.environ.get("REPONDEUR_WORKER_URL", "").strip()
    if env_url:
        config["enabled"] = True
        config["url"] = env_url
        config["ssh"] = {"enabled": False}
    return config


def is_remote_required() -> bool:
    return bool(load_worker_config().get("require_remote", False))


def worker_url() -> str:
    config = load_worker_config()
    enabled = bool(config.get("enabled"))
    url = str(config.get("url") or "").rstrip("/")
    if is_remote_required() and (not enabled or not url):
        raise RuntimeError(
            "Traitement VM obligatoire mais nouvelle instance non configuree."
        )
    return url if enabled else ""


def is_worker_enabled() -> bool:
    return bool(worker_url())


def is_remote_analysis_enabled() -> bool:
    config = load_worker_config()
    enabled = bool(config.get("analysis_enabled", False))
    if is_remote_required() and not enabled:
        raise RuntimeError(
            "Traitement VM obligatoire mais creation de commande distante desactivee."
        )
    return enabled


def timeout_seconds() -> int:
    config = load_worker_config()
    try:
        return int(config.get("timeout_seconds") or 3600)
    except (TypeError, ValueError):
        return 3600


def _tcp_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def ensure_worker_connection() -> None:
    global _TUNNEL_PROCESS
    config = load_worker_config()
    ssh_config = config.get("ssh")
    if not isinstance(ssh_config, dict) or not bool(ssh_config.get("enabled")):
        return

    local_host = str(ssh_config.get("local_host") or "127.0.0.1")
    local_port = int(ssh_config.get("local_port") or 18787)
    if _tcp_port_open(local_host, local_port):
        return

    if _TUNNEL_PROCESS is not None and _TUNNEL_PROCESS.poll() is None:
        raise RuntimeError("Tunnel SSH demarre mais port worker indisponible")

    host = str(ssh_config.get("host") or "").strip()
    user = str(ssh_config.get("user") or "").strip()
    identity_file = str(ssh_config.get("identity_file") or "").strip()
    if not host or not user or not identity_file:
        raise RuntimeError("Configuration tunnel SSH incomplete")
    if not Path(identity_file).exists():
        raise RuntimeError(f"Cle SSH worker introuvable: {identity_file}")

    ssh_port = int(ssh_config.get("port") or 22)
    remote_host = str(ssh_config.get("remote_host") or "127.0.0.1")
    remote_port = int(ssh_config.get("remote_port") or 8787)
    connect_timeout = int(ssh_config.get("connect_timeout_seconds") or 20)
    forward = f"{local_host}:{local_port}:{remote_host}:{remote_port}"
    command = [
        "ssh",
        "-i",
        identity_file,
        "-p",
        str(ssh_port),
        "-o",
        "BatchMode=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-N",
        "-L",
        forward,
        f"{user}@{host}",
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | 0x00000008  # DETACHED_PROCESS
        )
    _TUNNEL_PROCESS = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )

    deadline = time.monotonic() + connect_timeout
    while time.monotonic() < deadline:
        if _tcp_port_open(local_host, local_port):
            return
        if _TUNNEL_PROCESS.poll() is not None:
            raise RuntimeError(
                "Impossible d'etablir le tunnel SSH vers la nouvelle instance."
            )
        time.sleep(0.25)
    raise RuntimeError("Delai depasse pour le tunnel SSH worker")


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    ensure_worker_connection()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            response_payload = json.loads(raw)
        except json.JSONDecodeError:
            response_payload = {"ok": False, "message": raw or str(exc)}
        response_payload.setdefault("ok", False)
        response_payload.setdefault("_http_status", exc.code)
        return response_payload
    return json.loads(raw)


def remote_health() -> dict[str, Any]:
    url = worker_url()
    if not url:
        raise RuntimeError("Worker VM non configure")
    ensure_worker_connection()
    request = urllib.request.Request(f"{url}/health", method="GET")
    with urllib.request.urlopen(request, timeout=min(timeout_seconds(), 15)) as response:
        return json.loads(response.read().decode("utf-8"))


def _audio_payload(audio_path: Path, force: bool) -> dict[str, Any]:
    return {
        "audio_name": audio_path.name,
        "audio_base64": base64.b64encode(audio_path.read_bytes()).decode("ascii"),
        "force": force,
    }


def remote_transcribe_audio(audio_path: Path, force: bool = False) -> dict[str, Any]:
    url = worker_url()
    if not url:
        raise RuntimeError("Worker VM non configure")
    return post_json(
        f"{url}/transcribe",
        _audio_payload(audio_path, force),
        timeout=timeout_seconds(),
    )


def remote_analyze_audio(audio_path: Path, force: bool = False) -> dict[str, Any]:
    url = worker_url()
    if not url:
        raise RuntimeError("Worker VM non configure")
    return post_json(
        f"{url}/analyze",
        _audio_payload(audio_path, force),
        timeout=timeout_seconds(),
    )


def write_remote_transcription(audio_path: Path, result: dict[str, Any]) -> Path:
    transcription_json = result.get("transcription_json")
    if not isinstance(transcription_json, dict):
        raise RuntimeError("Reponse worker sans transcription_json")

    output_dir = PROJECT_ROOT / "resultats" / "transcriptions"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{audio_path.stem}__transcription.json"
    txt_path = output_dir / f"{audio_path.stem}__transcription.txt"

    transcription_json["fichier_audio"] = audio_path.name
    json_path.write_text(
        json.dumps(transcription_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        from transcrire_audios import creer_resume_txt

        txt_path.write_text(
            creer_resume_txt(audio_path.name, transcription_json),
            encoding="utf-8",
        )
    except Exception:
        text = str(transcription_json.get("texte") or result.get("transcription_text") or "")
        txt_path.write_text(text, encoding="utf-8")
    return json_path
