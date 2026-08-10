from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from src.runtime_paths import get_project_root


PROJECT_ROOT = get_project_root()
HANDLED_AUDIO_PATH = PROJECT_ROOT / "cache" / "prod-audios-deja-transmis.json"
AUDIO_EXTENSIONS = {".ogg", ".mp3", ".wav", ".m4a", ".webm", ".flac", ".mp4", ".mpeg", ".mpga"}


def audio_key(value: str | Path) -> str:
    text = str(value or "").replace("\\", "/")
    name = Path(text).name
    name = name.replace("__transcription.json", "")
    stem = Path(name).stem
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-_.").lower()


def load_handled_audio_keys() -> set[str]:
    if not HANDLED_AUDIO_PATH.exists():
        return set()
    try:
        raw = json.loads(HANDLED_AUDIO_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    items = raw.get("audios", []) if isinstance(raw, dict) else []
    return {audio_key(item) for item in items if audio_key(item)}


def save_handled_audio_names(names: list[str]) -> int:
    unique = sorted({audio_key(name) for name in names if audio_key(name)})
    HANDLED_AUDIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    HANDLED_AUDIO_PATH.write_text(
        json.dumps(
            {
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "mode": "deja_transmis_sans_renvoi",
                "audios": unique,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return len(unique)


def unmark_handled_audio_names(names: list[str]) -> int:
    remove = {audio_key(name) for name in names if audio_key(name)}
    if not remove:
        return len(load_handled_audio_keys())
    remaining = sorted(load_handled_audio_keys() - remove)
    return save_handled_audio_names(remaining)


def mark_existing_nextcloud_audios_as_handled() -> int:
    audio_dir = PROJECT_ROOT / "ressources-originales" / "audio-nextcloud"
    names: list[str] = []
    if audio_dir.exists():
        for path in audio_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                names.append(path.name)
    return save_handled_audio_names(names)


def is_audio_handled(value: str | Path) -> bool:
    key = audio_key(value)
    return bool(key) and key in load_handled_audio_keys()
