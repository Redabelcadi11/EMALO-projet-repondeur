from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.runtime_paths import bootstrap_runtime_environment
from prod_audio_state import audio_key, is_audio_handled, unmark_handled_audio_names


bootstrap_runtime_environment()


FILENAME_DATE_RE = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})[_ -](?P<hour>\d{2})[-h](?P<minute>\d{2})(?:[-m](?P<second>\d{2}))?"
)


def audio_datetime(path: Path) -> datetime:
    match = FILENAME_DATE_RE.search(path.name)
    if match:
        second = match.group("second") or "00"
        raw = f"{match.group('date')} {match.group('hour')}:{match.group('minute')}:{second}"
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def recent_nextcloud_audios(days: int = 10, today: date | None = None) -> list[Path]:
    from lancer_pipeline import DOSSIER_AUDIOS_NEXTCLOUD, EXTENSIONS_AUDIO

    current = today or date.today()
    cutoff = current - timedelta(days=max(0, days))
    audios: list[Path] = []
    if not DOSSIER_AUDIOS_NEXTCLOUD.exists():
        return audios

    for path in DOSSIER_AUDIOS_NEXTCLOUD.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS_AUDIO:
            continue
        audio_date = audio_datetime(path).date()
        if cutoff <= audio_date <= current and not is_audio_handled(path):
            audios.append(path)
    return sorted(audios, key=lambda item: (audio_datetime(item), item.name))


def all_nextcloud_audios() -> list[Path]:
    from lancer_pipeline import DOSSIER_AUDIOS_NEXTCLOUD, EXTENSIONS_AUDIO

    if not DOSSIER_AUDIOS_NEXTCLOUD.exists():
        return []
    audios = [
        path
        for path in DOSSIER_AUDIOS_NEXTCLOUD.rglob("*")
        if path.is_file() and path.suffix.lower() in EXTENSIONS_AUDIO
    ]
    return sorted(audios, key=lambda item: (audio_datetime(item), item.name), reverse=True)


def select_nextcloud_audios(keys: list[str]) -> list[Path]:
    wanted = {audio_key(key) for key in keys if audio_key(key)}
    if not wanted:
        return []
    selected = [
        path
        for path in all_nextcloud_audios()
        if audio_key(path.name) in wanted or audio_key(path) in wanted
    ]
    return sorted(selected, key=lambda item: (audio_datetime(item), item.name))


def transcription_path_for(audio: Path) -> Path:
    from lancer_pipeline import DOSSIER_TRANSCRIPTIONS

    return DOSSIER_TRANSCRIPTIONS / f"{audio.stem}__transcription.json"


def read_transcription_text(transcription_path: Path) -> str:
    import json

    if not transcription_path.exists():
        return ""
    try:
        payload = json.loads(transcription_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("texte") or payload.get("transcription") or "").strip()


def ensure_transcriptions_for_audios(audios: list[Path]) -> dict[str, Any]:
    missing = [audio for audio in audios if not transcription_path_for(audio).exists()]
    if not missing:
        return {"requested": 0, "remote": 0, "local": 0}

    try:
        import worker_client
    except Exception:
        worker_client = None  # type: ignore[assignment]

    if worker_client and worker_client.is_worker_enabled():
        errors: list[str] = []
        remote_count = 0
        for audio in missing:
            result = worker_client.remote_transcribe_audio(audio)
            if not result.get("ok"):
                errors.append(f"{audio.name}: {result.get('message', 'erreur worker')}")
                continue
            worker_client.write_remote_transcription(audio, result)
            remote_count += 1
        if errors:
            raise RuntimeError("Worker VM transcription en erreur: " + " | ".join(errors[:3]))
        return {"requested": len(missing), "remote": remote_count, "local": 0}

    from lancer_pipeline import transcrire_liste_audios

    transcrire_liste_audios(missing)
    return {"requested": len(missing), "remote": 0, "local": len(missing)}


def analyze_audios_with_worker(audios: list[Path]) -> dict[str, Any] | None:
    if not audios:
        return {"commandes": [], "remote": 0, "local": 0}

    try:
        import worker_client
    except Exception:
        return None

    if not worker_client.is_worker_enabled() or not worker_client.is_remote_analysis_enabled():
        return None

    commandes: list[dict[str, Any]] = []
    errors: list[str] = []
    for audio in audios:
        result = worker_client.remote_analyze_audio(audio)
        if not result.get("ok"):
            message = str(result.get("message") or "erreur worker")
            if result.get("_http_status") == 404 or "Endpoint inconnu" in message:
                return None
            errors.append(f"{audio.name}: {message}")
            continue
        worker_client.write_remote_transcription(audio, result)
        audio_commandes = result.get("commandes")
        if not isinstance(audio_commandes, list):
            errors.append(f"{audio.name}: reponse worker sans commandes")
            continue
        commandes.extend(audio_commandes)

    if errors:
        raise RuntimeError("Worker VM analyse en erreur: " + " | ".join(errors[:3]))

    return {"commandes": commandes, "remote": len(audios), "local": 0}


def transcribe_selected_audio(audio_key_value: str) -> dict[str, Any]:
    audios = select_nextcloud_audios([audio_key_value])
    if not audios:
        return {"found": False, "message": "Audio introuvable."}

    audio = audios[0]
    transcription_path = transcription_path_for(audio)
    transcribed = False
    if not transcription_path.exists():
        stats = ensure_transcriptions_for_audios([audio])
        transcribed = bool(stats.get("requested"))

    text = read_transcription_text(transcription_path)
    if not text:
        return {
            "found": True,
            "audio_key": audio_key(audio.name),
            "audio_name": audio.name,
            "transcribed": transcribed,
            "message": "Transcription non disponible apres traitement.",
        }

    return {
        "found": True,
        "audio_key": audio_key(audio.name),
        "audio_name": audio.name,
        "transcribed": transcribed,
        "transcription": text,
        "transcription_path": str(transcription_path),
        "message": "Transcription terminee.",
    }


def order_ref_for_audio_name(audio_name: str) -> str:
    stem = Path(audio_name or "").stem
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-_.")
    return f"NC-{stem[:64]}" if stem else "NC-AUDIO"


def summarize_command(commande: dict[str, Any], audio: Path) -> dict[str, Any]:
    from src.segment_association import (
        indexer_lignes_par_segment,
        ligne_associee_au_segment,
    )
    from src.ui_product_details import (
        avertissements_commande,
        projection_produit_reconnu,
    )

    client_code = str(commande.get("client_retenu") or "")
    clients = commande.get("clients_candidats") or []
    client = next(
        (item for item in clients if item.get("code_client") == client_code),
        {},
    )
    date_livraison = commande.get("date_livraison") or {}
    lignes_par_segment, lignes_legacy_par_texte = indexer_lignes_par_segment(
        commande.get("lignes_commande", [])
    )
    products = [
        {
            "order": line.get("ordre_ligne", ""),
            "product_code": line.get("code_article", ""),
            "product_label": line.get("libelle_article", ""),
            "quantity": line.get("quantite", ""),
            "unit": line.get("unite", ""),
            "score": line.get("score_article", ""),
            "source_text": line.get("texte_source", ""),
        }
        for line in commande.get("lignes_commande", [])
    ]
    product_recognition = []
    for index, produit in enumerate(commande.get("produits", []) or [], start=1):
        if not isinstance(produit, dict):
            continue
        ligne = ligne_associee_au_segment(
            produit,
            lignes_par_segment,
            lignes_legacy_par_texte,
        )
        projection = projection_produit_reconnu(produit, ligne, index)
        if projection is not None:
            product_recognition.append(projection)
    return {
        "audio_key": audio_key(audio.name),
        "audio_name": audio.name,
        "order_ref": order_ref_for_audio_name(str(commande.get("fichier_audio") or audio.name)),
        "transcription": commande.get("transcription", ""),
        "status": commande.get("statut", ""),
        "can_send": commande.get("statut") == "VALIDEE",
        "reasons": commande.get("raisons_problematiques", []),
        "warnings": avertissements_commande(
            commande.get("raisons_problematiques", [])
        ),
        "client_code": client_code,
        "client_name": client.get("nom_client", ""),
        "client_city": client.get("ville", ""),
        "client_recognized": bool(client_code),
        "client_display": client.get("nom_client", "") if client_code else "Non reconnu",
        "date_livraison": date_livraison.get("date_iso", "") if isinstance(date_livraison, dict) else "",
        "date_expression": date_livraison.get("expression", "") if isinstance(date_livraison, dict) else "",
        "products": products,
        "product_recognition": product_recognition,
        "candidates": [
            {
                "client_code": item.get("code_client", ""),
                "client_name": item.get("nom_client", ""),
                "city": item.get("ville", ""),
                "score": item.get("score_global", item.get("score", "")),
            }
            for item in clients[:5]
        ],
    }


def persist_analysis_details(commandes: list[dict[str, Any]]) -> None:
    if not commandes:
        return

    from extraire_informations import DOSSIER_RESULTATS, creer_resume_txt

    DOSSIER_RESULTATS.mkdir(parents=True, exist_ok=True)
    for commande in commandes:
        audio_name = str(commande.get("fichier_audio") or "").strip()
        if not audio_name:
            continue
        stem = Path(audio_name).stem
        if not stem:
            continue
        json_path = DOSSIER_RESULTATS / f"{stem}__extraction.json"
        txt_path = DOSSIER_RESULTATS / f"{stem}__extraction.txt"
        json_path.write_text(
            json.dumps(commande, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        txt_path.write_text(creer_resume_txt(commande), encoding="utf-8")


def analyze_selected_audio(audio_key_value: str) -> dict[str, Any]:
    audios = select_nextcloud_audios([audio_key_value])
    if not audios:
        return {"found": False, "message": "Audio introuvable."}

    audio = audios[0]
    transcription_path = transcription_path_for(audio)
    had_transcription = transcription_path.exists()
    remote_analysis = analyze_audios_with_worker([audio])
    if remote_analysis is not None:
        commandes = remote_analysis["commandes"]
        transcribed = not had_transcription and transcription_path.exists()
    else:
        from extraire_informations import traiter_transcriptions

        transcribed = False
        if not transcription_path.exists():
            stats = ensure_transcriptions_for_audios([audio])
            transcribed = bool(stats.get("requested"))
        if not transcription_path.exists():
            return {
                "found": True,
                "audio_key": audio_key(audio.name),
                "audio_name": audio.name,
                "message": "Transcription non disponible apres traitement.",
            }

        commandes = traiter_transcriptions(
            chemins_transcriptions=[transcription_path],
            date_reference=None,
        )
    persist_analysis_details(commandes)
    previews = [summarize_command(commande, audio) for commande in commandes]
    return {
        "found": True,
        "audio_key": audio_key(audio.name),
        "audio_name": audio.name,
        "transcribed": transcribed,
        "previews": previews,
        "message": "Analyse terminee.",
    }


def run_selected_audios_pipeline(
    audio_keys: list[str],
    max_new_transcriptions: int | None = None,
    preserve_existing_queue: bool = False,
) -> dict[str, Any]:
    from extraire_informations import exporter_csv_commandes
    import copilote_integration as ci

    audios = select_nextcloud_audios(audio_keys)
    if not audios:
        ci.refresh_queue_from_validated()
        return {
            "audios": 0,
            "transcrits": 0,
            "validees": 0,
            "problematiques": 0,
            "message": "Aucun audio selectionne trouve.",
        }

    missing = [audio for audio in audios if not transcription_path_for(audio).exists()]
    to_transcribe = missing
    if max_new_transcriptions is not None:
        to_transcribe = missing[: max(0, max_new_transcriptions)]
    transcription_stats = {"remote": 0, "local": 0}
    analysis_stats = {"remote": 0, "local": 0}
    # Two phases avoid GPU contention between Whisper large-v3 and the local
    # Llama arbiter.  First persist every missing transcript, then analyse the
    # completed set.  The remote worker releases Whisper before Llama can run.
    if to_transcribe:
        transcription_stats = ensure_transcriptions_for_audios(to_transcribe)
    remote_audios = [
        audio for audio in audios if transcription_path_for(audio).exists()
    ]
    remote_analysis = analyze_audios_with_worker(remote_audios)
    if remote_analysis is not None:
        available_audios = remote_audios
        commandes = remote_analysis["commandes"]
        analysis_stats = {"remote": len(remote_audios), "local": 0}
    else:
        from extraire_informations import traiter_transcriptions
        from lancer_pipeline import chemins_transcriptions_depuis_audios

        available_audios = [audio for audio in audios if transcription_path_for(audio).exists()]
        if available_audios:
            chemins_transcriptions = chemins_transcriptions_depuis_audios(available_audios)
            commandes = traiter_transcriptions(
                chemins_transcriptions=chemins_transcriptions,
                date_reference=None,
            )
            analysis_stats = {"remote": 0, "local": len(available_audios)}
        else:
            commandes = []

    if not available_audios:
        ci.refresh_queue_from_validated()
        return {
            "audios": len(audios),
            "transcrits": len(to_transcribe),
            "manquants": len(missing) - len(to_transcribe),
            "validees": 0,
            "problematiques": 0,
            "message": "Aucune transcription disponible pour les audios selectionnes.",
        }

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    persist_analysis_details(commandes)
    csv_validees, csv_problematiques = exporter_csv_commandes(
        commandes=commandes,
        run_id=run_id,
    )
    unmark_handled_audio_names([audio.name for audio in available_audios])
    ci.refresh_queue_from_validated(
        preserve_pending_nextcloud=preserve_existing_queue,
    )

    nb_validees = sum(1 for commande in commandes if commande.get("statut") == "VALIDEE")
    nb_problematiques = len(commandes) - nb_validees
    return {
        "audios": len(audios),
        "transcrits": len(to_transcribe),
        "manquants": max(0, len(missing) - len(to_transcribe)),
        "validees": nb_validees,
        "problematiques": nb_problematiques,
        "order_refs": [
            order_ref_for_audio_name(str(commande.get("fichier_audio") or audio.name))
            for commande, audio in zip(commandes, available_audios)
            if commande.get("statut") == "VALIDEE"
        ],
        "csv_validees": str(csv_validees),
        "csv_problematiques": str(csv_problematiques),
        "transcription_remote": transcription_stats.get("remote", 0),
        "transcription_local": transcription_stats.get("local", 0),
        "analysis_remote": analysis_stats.get("remote", 0),
        "analysis_local": analysis_stats.get("local", 0),
        "message": (
            f"{len(available_audios)} audio(s) analyses, "
            f"{len(to_transcribe)} nouvelle(s) transcription(s), "
            f"{nb_validees} commande(s) prete(s), "
            f"{nb_problematiques} cas a rappeler."
        ),
    }


def run_nextcloud_recent_pipeline(
    days: int = 10,
    date_reference: date | None = None,
    max_new_transcriptions: int | None = 20,
) -> dict[str, Any]:
    from extraire_informations import exporter_csv_commandes
    import copilote_integration as ci

    audios = recent_nextcloud_audios(days=days, today=date_reference)
    if not audios:
        ci.refresh_queue_from_validated()
        return {
            "audios": 0,
            "transcrits": 0,
            "validees": 0,
            "problematiques": 0,
            "message": "Aucun audio Nextcloud recent trouve.",
        }

    missing = [audio for audio in audios if not transcription_path_for(audio).exists()]
    to_transcribe = missing
    if max_new_transcriptions is not None:
        to_transcribe = missing[: max(0, max_new_transcriptions)]
    transcription_stats = {"remote": 0, "local": 0}
    analysis_stats = {"remote": 0, "local": 0}
    to_transcribe_set = set(to_transcribe)
    remote_audios = [
        audio for audio in audios if transcription_path_for(audio).exists() or audio in to_transcribe_set
    ]
    remote_analysis = analyze_audios_with_worker(remote_audios)
    if remote_analysis is not None:
        available_audios = remote_audios
        commandes = remote_analysis["commandes"]
        transcription_stats = {"remote": len(to_transcribe), "local": 0}
        analysis_stats = {"remote": len(remote_audios), "local": 0}
    else:
        from extraire_informations import traiter_transcriptions
        from lancer_pipeline import chemins_transcriptions_depuis_audios

        if to_transcribe:
            transcription_stats = ensure_transcriptions_for_audios(to_transcribe)

        available_audios = [audio for audio in audios if transcription_path_for(audio).exists()]
        if available_audios:
            chemins_transcriptions = chemins_transcriptions_depuis_audios(available_audios)
            commandes = traiter_transcriptions(
                chemins_transcriptions=chemins_transcriptions,
                date_reference=None,
            )
            analysis_stats = {"remote": 0, "local": len(available_audios)}
        else:
            commandes = []

    if not available_audios:
        ci.refresh_queue_from_validated()
        return {
            "audios": len(audios),
            "transcrits": len(to_transcribe),
            "manquants": len(missing) - len(to_transcribe),
            "validees": 0,
            "problematiques": 0,
            "message": "Audios Nextcloud recuperes, aucune transcription disponible pour extraction.",
        }

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    persist_analysis_details(commandes)
    csv_validees, csv_problematiques = exporter_csv_commandes(
        commandes=commandes,
        run_id=run_id,
    )
    ci.refresh_queue_from_validated()

    nb_validees = sum(1 for commande in commandes if commande.get("statut") == "VALIDEE")
    nb_problematiques = len(commandes) - nb_validees
    return {
        "audios": len(audios),
        "transcrits": len(to_transcribe),
        "manquants": max(0, len(missing) - len(to_transcribe)),
        "validees": nb_validees,
        "problematiques": nb_problematiques,
        "csv_validees": str(csv_validees),
        "csv_problematiques": str(csv_problematiques),
        "transcription_remote": transcription_stats.get("remote", 0),
        "transcription_local": transcription_stats.get("local", 0),
        "analysis_remote": analysis_stats.get("remote", 0),
        "analysis_local": analysis_stats.get("local", 0),
        "message": (
            f"{len(available_audios)} audio(s) analyses, "
            f"{len(to_transcribe)} nouvelle(s) transcription(s), "
            f"{max(0, len(missing) - len(to_transcribe))} restante(s), "
            f"{nb_validees} commande(s) validee(s), "
            f"{nb_problematiques} cas a corriger."
        ),
    }
