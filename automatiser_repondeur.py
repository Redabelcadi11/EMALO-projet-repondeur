"""Unattended Nextcloud -> local proposal pipeline.

This entry point is deliberately limited to safe, local work:

* copy new audio files from Nextcloud;
* transcribe/analyse them on the configured remote GPU worker;
* create/update the local ``A_ENVOYER`` proposal queue and UI cache.

It deliberately contains no Copilote/ERP send or import operation.  It also
refuses to start unless the central ERP evaluation lock is still enabled.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from prod_audio_state import AUDIO_EXTENSIONS, audio_key
from src.erp_safety import erp_safety_status
from src.runtime_paths import bootstrap_runtime_environment, get_project_root


PROJECT_ROOT = bootstrap_runtime_environment()
STATE_PATH = PROJECT_ROOT / "cache" / "automatic-audio-pipeline-state.json"
STATUS_PATH = PROJECT_ROOT / "cache" / "automatic-audio-pipeline-status.json"
LOCK_PATH = PROJECT_ROOT / "cache" / "automatic-audio-pipeline.lock"
MANIFEST_PATH = PROJECT_ROOT / "cache" / "nextcloud-sync-manifest.json"
AUDIO_DIR = PROJECT_ROOT / "ressources-originales" / "audio-nextcloud"
BATCH_SIZE = 10


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronise et analyse les nouveaux audios Nextcloud sans ecriture ERP."
    )
    parser.add_argument(
        "--date",
        help="Rattrapage explicite YYYY-MM-DD, analyse tous les audios de cette date.",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Ne lance pas la copie Nextcloud (utile pour un rattrapage local).",
    )
    parser.add_argument(
        "--max-audios",
        type=int,
        default=0,
        help="Limite de securite optionnelle; 0 traite tout le lot.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les audios cibles sans lancer de transcription/analyse.",
    )
    return parser.parse_args(argv)


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _manifest_signature(item: dict[str, Any]) -> str:
    return json.dumps(
        {
            "etag": item.get("etag", ""),
            "size": item.get("size", 0),
            "last_modified": item.get("last_modified", ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _load_state() -> dict[str, Any]:
    raw = _read_json(STATE_PATH, {})
    if not isinstance(raw, dict):
        raw = {}
    processed = raw.get("processed")
    if not isinstance(processed, dict):
        processed = {}
    failed = raw.get("failed")
    if not isinstance(failed, dict):
        failed = {}
    return {"schema_version": 1, "processed": processed, "failed": failed}


def _assert_safe_local_proposals_only() -> None:
    status = erp_safety_status()
    if (
        status.writes_allowed
        or not status.evaluation_lock
        or status.mode != "evaluation"
    ):
        raise RuntimeError(
            "Automatisme refuse : le verrou ERP doit rester actif en mode "
            f"evaluation (etat actuel: {status.reason})."
        )


def _acquire_lock() -> int | None:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            LOCK_PATH,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError:
        return None
    os.write(
        descriptor,
        (
            f"pid={os.getpid()} started_at="
            f"{datetime.now().isoformat(timespec='seconds')}\n"
        ).encode("utf-8"),
    )
    return descriptor


def _release_lock(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    finally:
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass


def _audio_paths_for_date(value: str) -> list[Path]:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("--date doit etre au format YYYY-MM-DD") from exc
    if not AUDIO_DIR.exists():
        return []
    return sorted(
        (
            path
            for path in AUDIO_DIR.rglob("*")
            if path.is_file()
            and path.suffix.lower() in AUDIO_EXTENSIONS
            and path.name.startswith(value + "_")
        ),
        key=lambda path: path.name,
    )


def _changed_audios_from_sync(before: dict[str, Any], after: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    for remote_path, entry in after.items():
        if not isinstance(entry, dict):
            continue
        previous = before.get(remote_path)
        if isinstance(previous, dict) and _manifest_signature(previous) == _manifest_signature(entry):
            continue
        local_value = str(entry.get("local_path") or "").strip()
        local_path = Path(local_value) if local_value else AUDIO_DIR / remote_path
        if local_path.is_file() and local_path.suffix.lower() in AUDIO_EXTENSIONS:
            candidates.append(local_path)
    return sorted({path.resolve() for path in candidates}, key=lambda path: path.name)


def _failed_audio_retries(state: dict[str, Any]) -> list[Path]:
    retries: list[Path] = []
    for value in (state.get("failed") or {}).values():
        if not isinstance(value, dict):
            continue
        name = str(value.get("audio_name") or "").strip()
        if not name:
            continue
        path = AUDIO_DIR / name
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            retries.append(path.resolve())
    return retries


def _sync_nextcloud() -> list[Path]:
    from recuperer_nextcloud import main as nextcloud_main

    before = _read_json(MANIFEST_PATH, {})
    if not isinstance(before, dict):
        before = {}
    code = int(nextcloud_main(["--insecure"]) or 0)
    if code != 0:
        raise RuntimeError(f"Synchronisation Nextcloud en erreur: code {code}")
    after = _read_json(MANIFEST_PATH, {})
    if not isinstance(after, dict):
        raise RuntimeError("Manifeste Nextcloud illisible apres synchronisation")
    return _changed_audios_from_sync(before, after)


def _process_audios(audios: list[Path]) -> dict[str, Any]:
    """Create only a local proposal; `send` is intentionally unreachable."""
    from prod_pipeline import run_selected_audios_pipeline

    return run_selected_audios_pipeline(
        [audio_key(audio.name) for audio in audios],
        max_new_transcriptions=None,
        preserve_existing_queue=True,
    )


def _refresh_shared_ui() -> None:
    from generer_ui_data_prod import main as generate_prod_ui_data

    generate_prod_ui_data()


def run(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    _assert_safe_local_proposals_only()

    descriptor = _acquire_lock()
    if descriptor is None:
        return {
            "ok": True,
            "skipped": "already_running",
            "message": "Un cycle automatique est deja en cours; aucun chevauchement lance.",
        }

    started_at = datetime.now().isoformat(timespec="seconds")
    state = _load_state()
    try:
        if args.date:
            candidates = _audio_paths_for_date(args.date)
            selection_reason = f"rattrapage date {args.date}"
        elif args.no_sync:
            candidates = _failed_audio_retries(state)
            selection_reason = "reprise locale des audios en echec"
        else:
            candidates = _sync_nextcloud()
            candidates = sorted(
                {*(path.resolve() for path in candidates), *_failed_audio_retries(state)},
                key=lambda path: path.name,
            )
            selection_reason = "nouveaux/modifies depuis Nextcloud"

        if args.max_audios and args.max_audios > 0:
            candidates = candidates[: args.max_audios]

        result: dict[str, Any] = {
            "ok": True,
            "started_at": started_at,
            "finished_at": "",
            "selection": selection_reason,
            "candidates": len(candidates),
            "processed": 0,
            "ready": 0,
            "problematic": 0,
            "errors": [],
            "audio_names": [path.name for path in candidates],
            "erp_writes": False,
        }
        if args.dry_run:
            result["dry_run"] = True
            result["finished_at"] = datetime.now().isoformat(timespec="seconds")
            return result

        def enregistrer_succes(
            lot: list[Path],
            traitement: dict[str, Any],
        ) -> None:
            result["processed"] += len(lot)
            result["ready"] += int(traitement.get("validees") or 0)
            result["problematic"] += int(
                traitement.get("problematiques") or 0
            )
            for audio in lot:
                state["processed"][audio_key(audio.name)] = {
                    "audio_name": audio.name,
                    "processed_at": datetime.now().isoformat(
                        timespec="seconds"
                    ),
                    "status": "ok",
                }
                state["failed"].pop(audio_key(audio.name), None)

        def enregistrer_echec(audio: Path, exc: Exception) -> None:
            result["errors"].append({
                "audio": audio.name,
                "message": str(exc),
            })
            state["failed"][audio_key(audio.name)] = {
                "audio_name": audio.name,
                "failed_at": datetime.now().isoformat(timespec="seconds"),
                "message": str(exc),
            }

        for start in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[start : start + BATCH_SIZE]
            try:
                processed = _process_audios(batch)
                if int(processed.get("audios") or 0) != len(batch):
                    raise RuntimeError(processed.get("message") or "lot audio non traite")
                enregistrer_succes(batch, processed)
            except Exception:
                # Un seul audio en erreur (notamment une pointe de mémoire
                # GPU) ne doit jamais condamner les neuf autres du lot. Les
                # transcriptions déjà produites sont réutilisées lors de ce
                # repli unitaire.
                for audio in batch:
                    try:
                        traitement_unitaire = _process_audios([audio])
                        if int(traitement_unitaire.get("audios") or 0) != 1:
                            raise RuntimeError(
                                traitement_unitaire.get("message")
                                or "audio non traite"
                            )
                        enregistrer_succes([audio], traitement_unitaire)
                    except Exception as exc_unitaire:
                        enregistrer_echec(audio, exc_unitaire)

            _write_json_atomic(STATE_PATH, state)
            # Make completed blocks immediately visible to a running UI;
            # the final refresh below remains a last consistency check.
            _refresh_shared_ui()

        # One shared refresh after all audio work: the UI can open Details
        # directly, with both the persisted transcription and local proposal.
        _refresh_shared_ui()
        result["finished_at"] = datetime.now().isoformat(timespec="seconds")
        result["ok"] = not result["errors"]
        return result
    finally:
        _release_lock(descriptor)


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(argv)
    except Exception as exc:
        result = {
            "ok": False,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "message": str(exc),
            "erp_writes": False,
        }
    _write_json_atomic(STATUS_PATH, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
