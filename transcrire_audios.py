from __future__ import annotations

"""Façade de transcription de production, orientée fiabilité."""

import os
import re
from pathlib import Path
from typing import Any

import _transcrire_audios_legacy as _legacy

# La qualité devient le défaut. Les variables d'environnement gardent la
# possibilité de réduire le coût explicitement sur une machine donnée.
_legacy.BEAM_SIZE = int(os.environ.get("REPONDEUR_WHISPER_BEAM_SIZE", "3"))
_legacy.WORD_TIMESTAMPS = (
    os.environ.get("REPONDEUR_WHISPER_WORD_TIMESTAMPS", "1").strip().lower()
    in {"1", "true", "oui", "yes"}
)

_ORIGINAL_TRANSCRIRE_AUDIO = _legacy.transcrire_audio

_QTE_RE = re.compile(
    r"\b(?:\d+(?:[.,]\d+)?|un|une|deux|trois|quatre|cinq|six|sept|"
    r"huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|vingt)\b",
    flags=re.IGNORECASE,
)


def transcription_liste_longue_a_controler(
    texte: str,
    *,
    duree_audio: float,
    nb_segments: int,
) -> bool:
    """Contrôle une énumération même si Whisper a déjà perdu des unités."""
    if duree_audio < 18.0 or nb_segments < 2:
        return False

    normalise = str(texte or "").casefold()
    quantite_unite = re.findall(
        r"\b(?:\d+(?:[.,]\d+)?|un|une|deux|trois|quatre|cinq|six|sept|"
        r"huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|vingt)\s+"
        r"(?:cartons?|colis|pots?|poches?|boites?|bouteilles?|kilos?|kg|"
        r"litres?|l|pieces?|paquets?|sacs?|seaux?|barquettes?)\b",
        normalise,
    )
    quantites = _QTE_RE.findall(normalise)
    transitions = re.findall(
        r"\b(?:et|puis|ensuite|aussi|egalement|apres)\b",
        normalise,
    )
    return (
        len(quantite_unite) >= 2
        or (len(quantites) >= 3 and len(transitions) >= 2)
    )


def _fenetres_plus_informatives_sans_hotwords(
    texte_initial: str,
    texte_fenetres: str,
) -> bool:
    """Secours strict quand aucun contexte téléphone n'est disponible."""
    initial = " ".join(str(texte_initial or "").split()).strip()
    alternatif = " ".join(str(texte_fenetres or "").split()).strip()
    if not initial or len(alternatif) < 0.80 * len(initial):
        return False
    return len(_QTE_RE.findall(alternatif)) >= len(_QTE_RE.findall(initial)) + 2


def transcrire_audio(
    modele: Any,
    chemin_audio: Path,
    hotwords: str | None = None,
) -> dict[str, Any]:
    """Ajoute la mosaïque sans VAD existante aux longues listes détectées."""
    resultat = _ORIGINAL_TRANSCRIRE_AUDIO(
        modele=modele,
        chemin_audio=chemin_audio,
        hotwords=hotwords,
    )

    segments = list(resultat.get("segments") or [])
    duree_observee = max(
        (float(segment.get("fin") or 0.0) for segment in segments),
        default=0.0,
    )
    if not transcription_liste_longue_a_controler(
        str(resultat.get("texte") or ""),
        duree_audio=duree_observee,
        nb_segments=len(segments),
    ):
        return resultat

    texte_fenetres, diagnostics = (
        _legacy.retranscrire_fenetres_couvrantes_longue_liste(
            modele,
            chemin_audio,
            duree_audio=duree_observee,
            hotwords=hotwords,
        )
    )
    initial = str(resultat.get("texte") or "")
    preferee = _legacy.transcription_fenetres_preferee(
        initial,
        texte_fenetres,
        hotwords,
    )
    if not preferee and not hotwords:
        preferee = _fenetres_plus_informatives_sans_hotwords(
            initial,
            texte_fenetres,
        )

    if preferee:
        if not resultat.get("texte_initial_fragmentaire"):
            resultat["texte_initial_fragmentaire"] = initial
        resultat["texte"] = texte_fenetres
        resultat["reprise_fenetres_couvrantes"] = True
    resultat["diagnostics_fenetres_couvrantes"] = diagnostics
    return resultat


_legacy.transcription_liste_longue_a_controler = (
    transcription_liste_longue_a_controler
)
_legacy.transcrire_audio = transcrire_audio

for _nom in dir(_legacy):
    if _nom.startswith("__"):
        continue
    globals()[_nom] = getattr(_legacy, _nom)

globals()["BEAM_SIZE"] = _legacy.BEAM_SIZE
globals()["WORD_TIMESTAMPS"] = _legacy.WORD_TIMESTAMPS
globals()["transcription_liste_longue_a_controler"] = (
    transcription_liste_longue_a_controler
)
globals()["transcrire_audio"] = transcrire_audio


if __name__ == "__main__":
    _legacy.main()
