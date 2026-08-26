from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from src.runtime_paths import get_project_root


SCHEMA_VERSION = 1
MAX_NOTE_LENGTH = 20_000
DEFAULT_NOTES_PATH = (
    get_project_root()
    / "resultats"
    / "remarques-audios"
    / "remarques_audios.json"
)


def _empty_document() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": "",
        "notes": {},
    }


def _validate_audio_key(value: object) -> str:
    key = str(value or "").strip()
    if not key:
        raise ValueError("Cle audio manquante.")
    if len(key) > 512 or any(ord(char) < 32 for char in key):
        raise ValueError("Cle audio invalide.")
    return key


def _read_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_document()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Le fichier de remarques est illisible et n'a pas ete modifie: {path}"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("notes"), dict):
        raise RuntimeError(
            f"Le fichier de remarques a un format invalide et n'a pas ete modifie: {path}"
        )
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("updated_at", "")
    return payload


@contextmanager
def _exclusive_file_lock(lock_path: Path, timeout: float = 8.0) -> Iterator[None]:
    """Serialize writers, including when the UI is used by several TSE processes."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()

    deadline = time.monotonic() + timeout
    locked = False
    try:
        while not locked:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Le fichier de remarques est utilise par un autre poste.")
                time.sleep(0.05)
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.stem}-",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            temporary_path = Path(temporary_name)
            if temporary_path.exists():
                temporary_path.unlink()


def load_audio_notes(path: Path | None = None) -> dict[str, Any]:
    notes_path = Path(path) if path is not None else DEFAULT_NOTES_PATH
    return _read_document(notes_path)


def save_audio_note(
    audio_key: object,
    note: object,
    *,
    audio: dict[str, Any] | None = None,
    path: Path | None = None,
) -> dict[str, Any] | None:
    notes_path = Path(path) if path is not None else DEFAULT_NOTES_PATH
    key = _validate_audio_key(audio_key)
    text = str(note or "").strip()
    if len(text) > MAX_NOTE_LENGTH:
        raise ValueError(f"La remarque depasse {MAX_NOTE_LENGTH} caracteres.")

    metadata = audio if isinstance(audio, dict) else {}
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    lock_path = notes_path.with_suffix(notes_path.suffix + ".lock")
    with _exclusive_file_lock(lock_path):
        document = _read_document(notes_path)
        notes = document["notes"]
        previous = notes.get(key) if isinstance(notes.get(key), dict) else {}
        if not text:
            notes.pop(key, None)
            saved: dict[str, Any] | None = None
        else:
            saved = {
                "audio_key": key,
                "audio_name": str(metadata.get("name") or previous.get("audio_name") or ""),
                "audio_path": str(metadata.get("path") or previous.get("audio_path") or ""),
                "phone": str(metadata.get("phone") or previous.get("phone") or ""),
                "audio_date": str(metadata.get("date") or previous.get("audio_date") or ""),
                "audio_time": str(metadata.get("time") or previous.get("audio_time") or ""),
                "note": text,
                "created_at": str(previous.get("created_at") or now),
                "updated_at": now,
            }
            notes[key] = saved
        document["schema_version"] = SCHEMA_VERSION
        document["updated_at"] = now
        _atomic_write(notes_path, document)
    return saved
