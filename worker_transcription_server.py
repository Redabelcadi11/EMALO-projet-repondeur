from __future__ import annotations

import argparse
import base64
import json
import os
import re
import threading
import time
import traceback
import gc
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from src.runtime_paths import bootstrap_runtime_environment


os.environ["REPONDEUR_WORKER_SERVER"] = "1"
PROJECT_ROOT = bootstrap_runtime_environment()
AUDIO_DIR = PROJECT_ROOT / "ressources-originales" / "audio-nextcloud"
TRANSCRIPTIONS_DIR = PROJECT_ROOT / "resultats" / "transcriptions"
MAX_BODY_BYTES = 256 * 1024 * 1024

_MODEL: Any = None
_MODEL_LOCK = threading.RLock()
_MODEL_LOAD_SECONDS = 0.0
_HOTWORDS_BY_PHONE: dict[str, str] | None = None
_HOTWORDS_LOCK = threading.RLock()
OLLAMA_UNLOAD_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "llama3.1:70b"


def get_hotwords_by_phone() -> dict[str, str]:
    global _HOTWORDS_BY_PHONE
    with _HOTWORDS_LOCK:
        if _HOTWORDS_BY_PHONE is not None:
            return _HOTWORDS_BY_PHONE
        from extraire_informations import (
            CHEMIN_ALIASES_TELEPHONIQUES_CONFIRMES,
            CHEMIN_TELEPHONES_CLIENTS,
            CHEMIN_VARIANTES_CLIENTS,
            CHEMIN_SYNONYMES_PRODUITS,
            charger_cadencier,
            charger_clients,
        )
        from src.clients import (
            charger_aliases_telephoniques_confirmes,
            charger_telephones_clients,
            charger_variantes_clients,
            enrichir_alias_avec_variantes,
            enrichir_clients_avec_aliases_telephoniques_confirmes,
            enrichir_clients_avec_telephones,
        )
        from src.contexte_asr import construire_hotwords_par_telephone
        from src.produits import charger_synonymes_produits

        clients = charger_clients()
        cadencier = charger_cadencier()
        enrichir_alias_avec_variantes(
            clients,
            charger_variantes_clients(CHEMIN_VARIANTES_CLIENTS),
        )
        enrichir_clients_avec_telephones(
            clients,
            charger_telephones_clients(CHEMIN_TELEPHONES_CLIENTS),
        )
        enrichir_clients_avec_aliases_telephoniques_confirmes(
            clients,
            charger_aliases_telephoniques_confirmes(
                CHEMIN_ALIASES_TELEPHONIQUES_CONFIRMES
            ),
        )
        _HOTWORDS_BY_PHONE = construire_hotwords_par_telephone(
            clients,
            cadencier,
            synonymes_produits=charger_synonymes_produits(
                CHEMIN_SYNONYMES_PRODUITS
            ),
        )
        return _HOTWORDS_BY_PHONE


def safe_audio_name(raw_name: str) -> str:
    name = Path(raw_name or "").name.strip()
    if not name:
        name = "audio-repondeur.mp3"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", name).strip(" .-")
    return name or "audio-repondeur.mp3"


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def get_model() -> tuple[Any, float]:
    global _MODEL, _MODEL_LOAD_SECONDS
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL, 0.0

        from faster_whisper import WhisperModel
        from transcrire_audios import APPAREIL, CPU_THREADS, MODELE, NUM_WORKERS, TYPE_CALCUL

        started = time.perf_counter()
        _MODEL = WhisperModel(
            MODELE,
            device=APPAREIL,
            compute_type=TYPE_CALCUL,
            cpu_threads=CPU_THREADS,
            num_workers=NUM_WORKERS,
        )
        _MODEL_LOAD_SECONDS = round(time.perf_counter() - started, 3)
        return _MODEL, _MODEL_LOAD_SECONDS


def unload_llama_before_transcription() -> None:
    """Release the local Llama GPU allocation before loading Whisper.

    The L4 has 23 GB.  Llama 70B occupies almost all of it while loaded,
    whereas long messages need additional temporary VRAM for Whisper large-v3.
    This only manages GPU residency; it never changes the Llama model or the
    product-resolution rules.  Llama is allowed to load again for analysis.
    """
    payload = json.dumps(
        {"model": OLLAMA_MODEL, "keep_alive": 0, "stream": False}
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_UNLOAD_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
    except Exception:
        # Ollama is an optional arbiter.  Whisper will still expose a precise
        # CUDA error if the memory cannot be recovered.
        pass


def release_whisper_before_analysis() -> None:
    """Free Whisper before an optional Llama arbitration phase."""
    global _MODEL
    with _MODEL_LOCK:
        _MODEL = None
        gc.collect()


def _decode_audio(payload: dict[str, Any]) -> tuple[str, bytes]:
    audio_name = safe_audio_name(str(payload.get("audio_name") or ""))
    encoded = str(payload.get("audio_base64") or "")
    if not encoded:
        raise ValueError("audio_base64 manquant")
    try:
        audio_bytes = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("audio_base64 invalide") from exc
    if not audio_bytes:
        raise ValueError("audio vide")
    return audio_name, audio_bytes


def transcribe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request_started = time.perf_counter()
    audio_name, audio_bytes = _decode_audio(payload)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = AUDIO_DIR / audio_name
    transcription_path = TRANSCRIPTIONS_DIR / f"{audio_path.stem}__transcription.json"
    txt_path = TRANSCRIPTIONS_DIR / f"{audio_path.stem}__transcription.txt"
    audio_path.write_bytes(audio_bytes)

    force = bool(payload.get("force"))
    reused = transcription_path.exists() and not force
    model_load_seconds = 0.0

    if not reused:
        unload_llama_before_transcription()
        from transcrire_audios import (
            APPAREIL,
            MODELE,
            TYPE_CALCUL,
            creer_resume_txt,
            transcrire_audio,
        )

        from src.contexte_asr import telephone_depuis_nom_audio

        telephone = telephone_depuis_nom_audio(audio_name)
        hotwords = get_hotwords_by_phone().get(telephone, "")
        with _MODEL_LOCK:
            model, model_load_seconds = get_model()
            transcription_json = {
                "fichier_audio": audio_name,
                "genere_le": datetime.now().isoformat(),
                "modele": MODELE,
                "appareil": APPAREIL,
                "type_calcul": TYPE_CALCUL,
                **transcrire_audio(model, audio_path, hotwords=hotwords),
            }
        transcription_path.write_text(
            json.dumps(transcription_json, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        txt_path.write_text(
            creer_resume_txt(audio_name, transcription_json),
            encoding="utf-8",
        )
    else:
        transcription_json = json.loads(transcription_path.read_text(encoding="utf-8"))

    transcription_seconds = float(
        transcription_json.get("duree_traitement_secondes") or 0.0
    )
    return {
        "ok": True,
        "audio_name": audio_name,
        "transcription_path": str(transcription_path),
        "transcription_text": str(transcription_json.get("texte") or "").strip(),
        "transcription_json": transcription_json,
        "transcription_reused": reused,
        "transcription_seconds": transcription_seconds,
        "model_load_seconds": model_load_seconds,
        "worker_total_seconds": round(time.perf_counter() - request_started, 3),
    }


def analyze_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request_started = time.perf_counter()
    result = transcribe_payload(payload)
    transcription_path = Path(str(result.get("transcription_path") or ""))
    if not transcription_path.exists():
        raise RuntimeError("Transcription introuvable pour analyse worker")

    # Keep the two large GPU models mutually exclusive.  This is especially
    # important for a just-transcribed long audio; no accuracy setting changes.
    release_whisper_before_analysis()

    from extraire_informations import traiter_transcriptions

    analysis_started = time.perf_counter()
    commandes = traiter_transcriptions(
        chemins_transcriptions=[transcription_path],
        date_reference=None,
    )
    result["commandes"] = commandes
    result["analysis_count"] = len(commandes)
    result["analysis_seconds"] = round(time.perf_counter() - analysis_started, 3)
    result["worker_total_seconds"] = round(time.perf_counter() - request_started, 3)
    return result


class WorkerHandler(BaseHTTPRequestHandler):
    server_version = "ProjetRepondeurWorker/2.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            from transcrire_audios import APPAREIL, MODELE, TYPE_CALCUL

            json_response(
                self,
                200,
                {
                    "ok": True,
                    "service": "repondeur-worker",
                    "version": "2.0",
                    "project_root": str(PROJECT_ROOT),
                    "endpoints": ["/transcribe", "/analyze"],
                    "model": MODELE,
                    "device": APPAREIL,
                    "compute_type": TYPE_CALCUL,
                    "model_loaded": _MODEL is not None,
                    "model_load_seconds": _MODEL_LOAD_SECONDS,
                },
            )
            return
        json_response(self, 404, {"ok": False, "message": "Endpoint inconnu"})

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        if path not in {"/transcribe", "/analyze"}:
            json_response(self, 404, {"ok": False, "message": "Endpoint inconnu"})
            return

        try:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                raise ValueError("Corps HTTP vide")
            if length > MAX_BODY_BYTES:
                raise ValueError("Audio trop volumineux pour le worker")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            result = analyze_payload(payload) if path == "/analyze" else transcribe_payload(payload)
            json_response(self, 200, result)
        except Exception as exc:
            json_response(
                self,
                500,
                {
                    "ok": False,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=8),
                },
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker VM Repondeur")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), WorkerHandler)
    print(f"Worker Repondeur ecoute sur http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
