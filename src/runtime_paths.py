from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "ProjetRepondeur"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_project_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def get_cache_root() -> Path:
    return get_project_root() / "cache"


def ensure_runtime_directories() -> None:
    project_root = get_project_root()
    for relative in (
        "resultats",
        "resultats/transcriptions",
        "resultats/extractions",
        "resultats/commandes-validees",
        "resultats/commandes-problematiques",
        "resultats/copilote-debug",
        "cache",
        "cache/hf",
        "ms-playwright",
    ):
        (project_root / relative).mkdir(parents=True, exist_ok=True)


def bootstrap_runtime_environment() -> Path:
    project_root = get_project_root()
    ensure_runtime_directories()
    cache_root = get_cache_root()
    ffmpeg_bin = project_root / "ffmpeg" / "bin"

    os.environ.setdefault("HF_HOME", str(cache_root / "hf"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH",
        str(project_root / "ms-playwright"),
    )
    if ffmpeg_bin.exists():
        current_path = os.environ.get("PATH", "")
        ffmpeg_str = str(ffmpeg_bin)
        if ffmpeg_str not in current_path.split(os.pathsep):
            os.environ["PATH"] = ffmpeg_str + os.pathsep + current_path
    return project_root
