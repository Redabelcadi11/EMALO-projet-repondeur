from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.runtime_paths import (
    bootstrap_runtime_environment,
    get_project_root,
)

bootstrap_runtime_environment()
from faster_whisper import WhisperModel


# -------------------------------------------------------------------
# Configuration générale
# -------------------------------------------------------------------

RACINE_PROJET = get_project_root()

DOSSIER_AUDIOS = (
    RACINE_PROJET
    / "ressources-originales"
    / "audio-exemples"
)

DOSSIER_RESULTATS = (
    RACINE_PROJET
    / "resultats"
    / "transcriptions"
)

# Modèle local précis.
MODELE = os.environ.get("REPONDEUR_WHISPER_MODEL", "large-v3")

# Configuration adaptée à un serveur ou PC sans GPU.
APPAREIL = os.environ.get("REPONDEUR_WHISPER_DEVICE", "cpu")
TYPE_CALCUL = os.environ.get("REPONDEUR_WHISPER_COMPUTE", "int8")
CPU_THREADS = int(os.environ.get("REPONDEUR_WHISPER_CPU_THREADS", "4"))
NUM_WORKERS = int(os.environ.get("REPONDEUR_WHISPER_NUM_WORKERS", "1"))
BEAM_SIZE = int(os.environ.get("REPONDEUR_WHISPER_BEAM_SIZE", "1"))
WORD_TIMESTAMPS = (
    os.environ.get("REPONDEUR_WHISPER_WORD_TIMESTAMPS", "0").strip().lower()
    in {"1", "true", "oui", "yes"}
)
CONDITION_ON_PREVIOUS_TEXT = (
    os.environ.get("REPONDEUR_WHISPER_CONDITION_ON_PREVIOUS_TEXT", "0").strip().lower()
    in {"1", "true", "oui", "yes"}
)

# En dessous de ce seuil, le mot sera conservé dans la liste
# des éléments à vérifier lors de l'étape suivante.
SEUIL_PROBABILITE_MOT_INCERTAIN = 0.70

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

PROMPT_METIER = """
Message vocal en français destiné à prendre une commande alimentaire pour BASCO.

Le client peut annoncer :
- le nom d'un restaurant, d'un hôtel, d'un bar ou d'un commerce ;
- une date de livraison ;
- des quantités ;
- des unités comme pièce, carton, colis, kilo, boîte ou palette ;
- des noms de produits alimentaires.

Transcrire fidèlement les noms propres, les nombres, les unités et les produits.
Ne pas résumer.
Ne pas inventer de produit ou de quantité.
""".strip()


# -------------------------------------------------------------------
# Transcription d'un audio
# -------------------------------------------------------------------

def transcrire_audio(
    modele: WhisperModel,
    chemin_audio: Path,
    hotwords: str | None = None,
) -> dict[str, Any]:
    """
    Transcrit un audio avec la configuration principale.

    Le résultat conserve :
    - le texte complet ;
    - les segments horodatés ;
    - les mots et leur probabilité ;
    - les mots incertains.
    """

    debut_traitement = time.perf_counter()

    segments_generateur, informations = modele.transcribe(
        str(chemin_audio),
        language="fr",
        task="transcribe",
        initial_prompt=PROMPT_METIER,
        hotwords=hotwords or None,
        beam_size=BEAM_SIZE,
        temperature=0.0,
        word_timestamps=WORD_TIMESTAMPS,
        vad_filter=True,
        condition_on_previous_text=CONDITION_ON_PREVIOUS_TEXT,
    )

    segments = list(segments_generateur)

    texte_complet = " ".join(
        segment.text.strip()
        for segment in segments
        if segment.text.strip()
    ).strip()

    segments_json: list[dict[str, Any]] = []
    mots_incertains: list[dict[str, Any]] = []

    for segment in segments:
        mots_json: list[dict[str, Any]] = []

        for mot in segment.words or []:
            probabilite = float(mot.probability)

            mot_json = {
                "mot": mot.word,
                "debut": round(float(mot.start), 3),
                "fin": round(float(mot.end), 3),
                "probabilite": round(probabilite, 4),
            }

            mots_json.append(mot_json)

            if probabilite < SEUIL_PROBABILITE_MOT_INCERTAIN:
                mots_incertains.append(mot_json)

        segments_json.append(
            {
                "debut": round(float(segment.start), 3),
                "fin": round(float(segment.end), 3),
                "texte": segment.text.strip(),
                "logprob_moyen": round(
                    float(segment.avg_logprob),
                    4,
                ),
                "mots": mots_json,
            }
        )

    duree_traitement = round(
        time.perf_counter() - debut_traitement,
        3,
    )

    return {
        "texte": texte_complet,
        "contexte_asr_actif": bool(hotwords),
        "contexte_asr_nb_termes": (
            len([terme for terme in (hotwords or "").split(",") if terme.strip()])
        ),
        "langue_detectee": informations.language,
        "probabilite_langue": round(
            float(informations.language_probability),
            4,
        ),
        "duree_traitement_secondes": duree_traitement,
        "mots_incertains": mots_incertains,
        "segments": segments_json,
    }


# -------------------------------------------------------------------
# Création du fichier TXT lisible
# -------------------------------------------------------------------

def creer_resume_txt(
    nom_audio: str,
    resultat: dict[str, Any],
) -> str:
    lignes: list[str] = [
        f"FICHIER AUDIO : {nom_audio}",
        f"MODÈLE : {MODELE}",
        f"DURÉE DU TRAITEMENT : {resultat['duree_traitement_secondes']} s",
        f"LANGUE DÉTECTÉE : {resultat['langue_detectee']}",
        (
            "PROBABILITÉ DE LA LANGUE : "
            f"{resultat['probabilite_langue']}"
        ),
        "",
        "=" * 80,
        "TRANSCRIPTION",
        "=" * 80,
        "",
        resultat["texte"] or "[TRANSCRIPTION VIDE]",
        "",
    ]

    if resultat["mots_incertains"]:
        lignes.extend(
            [
                "=" * 80,
                "MOTS OU MORCEAUX À VÉRIFIER",
                "=" * 80,
                "",
            ]
        )

        for mot in resultat["mots_incertains"]:
            lignes.append(
                f"- {mot['mot']!r} "
                f"(probabilité : {mot['probabilite']}, "
                f"temps : {mot['debut']} s → {mot['fin']} s)"
            )

        lignes.append("")

    return "\n".join(lignes)


# -------------------------------------------------------------------
# Programme principal
# -------------------------------------------------------------------

def main() -> None:
    if not DOSSIER_AUDIOS.exists():
        raise FileNotFoundError(
            f"Dossier audio introuvable : {DOSSIER_AUDIOS}"
        )

    DOSSIER_RESULTATS.mkdir(
        parents=True,
        exist_ok=True,
    )

    fichiers_audio = sorted(
        chemin
        for chemin in DOSSIER_AUDIOS.iterdir()
        if chemin.is_file()
        and chemin.suffix.lower() in EXTENSIONS_AUDIO
    )

    if not fichiers_audio:
        raise RuntimeError(
            f"Aucun fichier audio trouvé dans : {DOSSIER_AUDIOS}"
        )

    print(f"Chargement du modèle local : {MODELE}")
    print(
        "Le premier lancement peut être plus long : "
        "téléchargement du modèle."
    )
    print("")

    modele = WhisperModel(
        MODELE,
        device=APPAREIL,
        compute_type=TYPE_CALCUL,
        cpu_threads=CPU_THREADS,
        num_workers=NUM_WORKERS,
    )

    debut_total = time.perf_counter()

    for index, chemin_audio in enumerate(
        fichiers_audio,
        start=1,
    ):
        print(
            f"[{index}/{len(fichiers_audio)}] "
            f"Transcription : {chemin_audio.name}"
        )

        resultat = transcrire_audio(
            modele=modele,
            chemin_audio=chemin_audio,
        )

        resultat_complet = {
            "fichier_audio": chemin_audio.name,
            "genere_le": datetime.now().isoformat(),
            "modele": MODELE,
            "appareil": APPAREIL,
            "type_calcul": TYPE_CALCUL,
            **resultat,
        }

        nom_base = chemin_audio.stem

        chemin_json = (
            DOSSIER_RESULTATS
            / f"{nom_base}__transcription.json"
        )

        chemin_txt = (
            DOSSIER_RESULTATS
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
                nom_audio=chemin_audio.name,
                resultat=resultat,
            ),
            encoding="utf-8",
        )

        print(
            "    Terminé en "
            f"{resultat['duree_traitement_secondes']} s"
        )
        print(f"    JSON : {chemin_json}")
        print(f"    TXT  : {chemin_txt}")
        print("")

    duree_totale = round(
        time.perf_counter() - debut_total,
        3,
    )

    print("Terminé.")
    print(f"Durée totale : {duree_totale} s")
    print(f"Résultats : {DOSSIER_RESULTATS}")


if __name__ == "__main__":
    main()
