from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime
from pathlib import Path

from src.runtime_paths import (
    bootstrap_runtime_environment,
    get_project_root,
)

bootstrap_runtime_environment()

EXTENSIONS_AUDIO = {
    ".ogg",
    ".mp3",
    ".wav",
    ".m4a",
    ".webm",
    ".flac",
    ".mp4",
    ".mpeg",
    ".mpga",
}


RACINE_PROJET = get_project_root()
DOSSIER_TRANSCRIPTIONS = (
    RACINE_PROJET
    / "resultats"
    / "transcriptions"
)
DOSSIER_VERROUS_TRANSCRIPTION = (
    DOSSIER_TRANSCRIPTIONS
    / ".locks"
)
DOSSIER_AUDIOS = (
    RACINE_PROJET
    / "ressources-originales"
    / "audio-exemples"
)
DOSSIER_AUDIOS_NEXTCLOUD = (
    RACINE_PROJET
    / "ressources-originales"
    / "audio-nextcloud"
)
DOSSIERS_AUDIOS = (
    DOSSIER_AUDIOS,
    DOSSIER_AUDIOS_NEXTCLOUD,
)


def chemin_transcription_audio(audio: Path) -> Path:
    return DOSSIER_TRANSCRIPTIONS / f"{audio.stem}__transcription.json"


def chemin_verrou_transcription(audio: Path) -> Path:
    return DOSSIER_VERROUS_TRANSCRIPTION / f"{audio.stem}.lock"


def transcription_en_cours(audio: Path, age_max_secondes: int = 900) -> bool:
    verrou = chemin_verrou_transcription(audio)

    if not verrou.exists():
        return False

    try:
        age = time.time() - verrou.stat().st_mtime
    except OSError:
        return True

    if age > age_max_secondes:
        try:
            verrou.unlink()
        except OSError:
            return True
        return False

    return True


def acquerir_verrou_transcription(audio: Path) -> int | None:
    DOSSIER_VERROUS_TRANSCRIPTION.mkdir(parents=True, exist_ok=True)
    verrou = chemin_verrou_transcription(audio)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

    try:
        fd = os.open(str(verrou), flags)
    except FileExistsError:
        if transcription_en_cours(audio):
            return None
        try:
            fd = os.open(str(verrou), flags)
        except FileExistsError:
            return None

    os.write(
        fd,
        (
            f"pid={os.getpid()} "
            f"audio={audio.name} "
            f"started_at={datetime.now().isoformat(timespec='seconds')}\n"
        ).encode("utf-8"),
    )
    return fd


def liberer_verrou_transcription(audio: Path, fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass

    try:
        chemin_verrou_transcription(audio).unlink()
    except OSError:
        pass


def parser_arguments() -> argparse.Namespace:
    return creer_parser().parse_args()


def creer_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pipeline local BASCO : transcription + extraction + CSV."
        )
    )
    parser.add_argument(
        "--audio",
        action="append",
        help="Chemin d'un fichier audio à traiter (répétable).",
    )
    parser.add_argument(
        "--tous-les-audios",
        action="store_true",
        help="Traiter tous les audios du dossier ressources.",
    )
    parser.add_argument(
        "--sans-transcription",
        action="store_true",
        help=(
            "Réutilise les JSON de transcription existants "
            "sans relancer Whisper."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Mode sec : pas d'import ERP (aucun import automatique "
            "n'est réalisé dans ce projet)."
        ),
    )
    parser.add_argument(
        "--date-reference",
        help="Date de référence YYYY-MM-DD pour la détection des dates.",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Affiche un résumé performance en fin de traitement.",
    )

    return parser


def resoudre_liste_audios(
    arguments: argparse.Namespace,
) -> list[Path]:
    audios: list[Path] = []

    if arguments.audio:
        for brut in arguments.audio:
            chemin = Path(brut).expanduser()
            if not chemin.is_absolute():
                chemin = RACINE_PROJET / chemin
            audios.append(chemin)

    if arguments.tous_les_audios or (
        not arguments.audio
    ):
        for dossier_audio in DOSSIERS_AUDIOS:
            if not dossier_audio.exists():
                continue
            audios.extend(
                sorted(
                    fichier
                    for fichier in dossier_audio.rglob("*")
                    if fichier.is_file()
                    and fichier.suffix.lower()
                    in EXTENSIONS_AUDIO
                )
            )

    uniques = []
    deja = set()

    for audio in audios:
        cle = str(audio.resolve())
        if cle in deja:
            continue
        deja.add(cle)
        uniques.append(audio)

    return uniques


def transcrire_liste_audios(
    audios: list[Path],
) -> list[Path]:
    from faster_whisper import WhisperModel
    from transcrire_audios import (
        APPAREIL,
        CPU_THREADS,
        MODELE,
        NUM_WORKERS,
        PROMPT_METIER,
        TYPE_CALCUL,
        creer_resume_txt,
        transcrire_audio,
    )

    DOSSIER_TRANSCRIPTIONS.mkdir(
        parents=True,
        exist_ok=True,
    )

    sorties_pretes: list[Path] = []
    audios_a_transcrire: list[Path] = []
    verrous_transcription: dict[Path, int] = {}

    for audio in audios:
        if not audio.exists():
            raise FileNotFoundError(
                f"Audio introuvable : {audio}"
            )

        chemin_json = chemin_transcription_audio(audio)

        if chemin_json.exists():
            sorties_pretes.append(chemin_json)
            continue

        fd = acquerir_verrou_transcription(audio)

        if fd is None:
            print(
                "Transcription deja en cours, audio ignore : "
                f"{audio.name}"
            )
            continue

        verrous_transcription[audio] = fd
        audios_a_transcrire.append(audio)

    if not audios_a_transcrire:
        return sorties_pretes

    audios = audios_a_transcrire

    print(f"Chargement modele local : {MODELE}")
    print(
        "Prompt métier actif : "
        f"{PROMPT_METIER[:55]}..."
    )

    modele = WhisperModel(
        MODELE,
        device=APPAREIL,
        compute_type=TYPE_CALCUL,
        cpu_threads=CPU_THREADS,
        num_workers=NUM_WORKERS,
    )

    sorties: list[Path] = list(sorties_pretes)

    for index, audio in enumerate(audios, start=1):
        if not audio.exists():
            raise FileNotFoundError(
                f"Audio introuvable : {audio}"
            )

        print(f"[{index}/{len(audios)}] Transcription {audio.name}")
        resultat = transcrire_audio(
            modele=modele,
            chemin_audio=audio,
        )

        resultat_complet = {
            "fichier_audio": audio.name,
            "genere_le": datetime.now().isoformat(),
            "modele": MODELE,
            "appareil": APPAREIL,
            "type_calcul": TYPE_CALCUL,
            **resultat,
        }

        nom_base = audio.stem
        chemin_json = (
            DOSSIER_TRANSCRIPTIONS
            / f"{nom_base}__transcription.json"
        )
        chemin_txt = (
            DOSSIER_TRANSCRIPTIONS
            / f"{nom_base}__transcription.txt"
        )

        chemin_json.write_text(
            json.dumps(
                resultat_complet,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        chemin_txt.write_text(
            creer_resume_txt(
                nom_audio=audio.name,
                resultat=resultat,
            ),
            encoding="utf-8",
        )

        sorties.append(chemin_json)
        print(f"    JSON : {chemin_json}")
        print(f"    TXT  : {chemin_txt}")
        fd = verrous_transcription.pop(audio, None)
        liberer_verrou_transcription(audio, fd)

    return sorties


def chemins_transcriptions_depuis_audios(
    audios: list[Path],
) -> list[Path]:
    chemins = []

    for audio in audios:
        chemin = (
            DOSSIER_TRANSCRIPTIONS
            / f"{audio.stem}__transcription.json"
        )
        if not chemin.exists():
            raise FileNotFoundError(
                "Transcription manquante pour --sans-transcription : "
                f"{chemin}"
            )
        chemins.append(chemin)

    return chemins


def parse_date_reference(
    valeur: str | None,
) -> date | None:
    if not valeur:
        return None

    return date.fromisoformat(valeur)


def main(argv: list[str] | None = None) -> int:
    arguments = parser_arguments() if argv is None else parser_arguments_from_argv(argv)
    debut = time.perf_counter()

    audios = resoudre_liste_audios(arguments)

    if not audios:
        raise RuntimeError("Aucun audio à traiter.")

    if arguments.sans_transcription:
        chemins_transcriptions = (
            chemins_transcriptions_depuis_audios(audios)
        )
    else:
        chemins_transcriptions = transcrire_liste_audios(
            audios
        )

    date_reference = parse_date_reference(
        arguments.date_reference
    )

    from extraire_informations import (
        exporter_csv_commandes,
        traiter_transcriptions,
    )

    commandes = traiter_transcriptions(
        chemins_transcriptions=chemins_transcriptions,
        date_reference=date_reference,
    )

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_validees, csv_problematiques = exporter_csv_commandes(
        commandes=commandes,
        run_id=run_id,
    )

    nb_validees = sum(
        1
        for commande in commandes
        if commande.get("statut") == "VALIDEE"
    )
    nb_problematiques = len(commandes) - nb_validees

    print("")
    print("Traitement terminé.")
    print(f"Commandes validées : {nb_validees}")
    print(f"Commandes problématiques : {nb_problematiques}")
    print(f"CSV validées : {csv_validees}")
    print(f"CSV problématiques : {csv_problematiques}")

    if arguments.dry_run:
        print(
            "Mode dry-run actif : aucun import Copilote déclenché."
        )

    if arguments.benchmark:
        duree = max(0.001, time.perf_counter() - debut)
        audios_heure = (len(commandes) / duree) * 3600
        print(
            "Benchmark : "
            f"{len(commandes)} audios en {duree:.2f}s "
            f"({audios_heure:.1f} audios/heure)"
        )
    return 0


def parser_arguments_from_argv(argv: list[str]) -> argparse.Namespace:
    return creer_parser().parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
