from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher
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

_FINS_ASR_FRAGMENTAIRES = {
    "a", "avec", "bur", "d", "de", "des", "du", "en", "et", "pa",
    "par", "pour", "s", "sans",
}
_MOTS_COURTS_PRODUIT_COMPLETS = {
    "ail", "eau", "jus", "lait", "miel", "oeuf", "pain", "riz", "sel",
    "thon", "vin",
}
_NOMBRES_ASR = {
    "un": "1", "une": "1", "deux": "2", "trois": "3",
    "quatre": "4", "cinq": "5", "six": "6", "sept": "7",
    "huit": "8", "neuf": "9", "dix": "10",
}
_CANONIQUES_ASR_ANCRAGE = {
    # Variantes ordinaires observees entre deux decodages du meme passage.
    # Elles servent uniquement a retrouver une ancre temporelle, jamais a
    # creer une ligne produit.
    "oeuf": "oeuf",
    "oeufs": "oeuf",
    "oeux": "oeuf",
}


def _mots_asr_avec_spans(texte: str) -> list[tuple[str, tuple[int, int]]]:
    """Retourne des mots comparables entre deux passages ASR du meme audio."""
    bruts: list[tuple[str, tuple[int, int]]] = []
    for match in re.finditer(r"[\w%]+", str(texte or ""), flags=re.UNICODE):
        sans_accents = "".join(
            caractere
            for caractere in unicodedata.normalize("NFKD", match.group())
            if not unicodedata.combining(caractere)
        ).casefold()
        if sans_accents:
            bruts.append((sans_accents, match.span()))

    resultat: list[tuple[str, tuple[int, int]]] = []
    index = 0
    while index < len(bruts):
        mots = [mot for mot, _ in bruts[index:index + 3]]
        # Les deux graphies courantes ``90`` et ``quatre-vingt-dix`` doivent
        # pouvoir constituer une ancre de meme audio entre deux passes ASR.
        if mots == ["quatre", "vingt", "dix"]:
            resultat.append(("90", (bruts[index][1][0], bruts[index + 2][1][1])))
            index += 3
            continue
        mot, span = bruts[index]
        resultat.append((
            _CANONIQUES_ASR_ANCRAGE.get(_NOMBRES_ASR.get(mot, mot), mot),
            span,
        ))
        index += 1
    return resultat


def transcription_liste_longue_a_controler(
    texte: str,
    *,
    duree_audio: float,
    nb_segments: int,
) -> bool:
    """Declenche une verification audio seulement pour les longues listes.

    Faster-Whisper peut parfois couper une enumeration a une frontiere VAD
    alors que le message se poursuit. Une courte commande ou une formule de
    politesse ne justifie pas de repasser le GPU : on exige ici une duree,
    plusieurs segments et au moins quatre marqueurs de quantite.
    """
    if duree_audio < 35.0 or nb_segments < 2:
        return False
    marqueurs_quantite = re.findall(
        r"\b(?:\d+(?:[.,]\d+)?|un|une|deux|trois|quatre|cinq|six|sept|"
        r"huit|neuf|dix|onze|douze)\s+(?:cartons?|colis|pots?|poches?|"
        r"boites?|bouteilles?|kilos?|kg|litres?|l|pieces?)\b",
        str(texte or "").casefold(),
    )
    return len(marqueurs_quantite) >= 4


def fin_liste_avec_fragment_suspect(texte: str) -> bool:
    """Repere un fragment ASR juste avant une formule de cloture.

    ``merci`` peut masquer la coupure d'un dernier article : la detection de
    fin classique voit alors une phrase correctement terminee. Ici on ne
    declenche une reprise que si le dernier mot *avant* la cloture est un
    fragment tres court, ce qui reste un signal audio faible mais general.
    """
    normalise = " ".join(mot for mot, _ in _mots_asr_avec_spans(texte))
    avant_cloture = re.sub(
        r"\b(?:merci(?:\s+beaucoup)?|au revoir|bonne journee|bonne soiree)\b.*$",
        "",
        normalise,
    ).strip()
    if not avant_cloture:
        return False
    dernier = avant_cloture.split()[-1]
    return (
        len(dernier) <= 3
        and dernier not in _MOTS_COURTS_PRODUIT_COMPLETS
        and not dernier.isdigit()
    )


def recuperer_suffixe_liste_fragmentaire(
    texte_initial: str,
    texte_fenetre: str,
) -> str:
    """Remplace un suffixe fragmentaire par le meme passage re-entendu.

    Le remplacement exige un mot long commun avant le fragment et conserve
    tout le prefixe initial. Il sert aux fins du type ``... creme fraiche et
    deux kilos de glaire ap. Merci`` : une fenetre de fin peut confirmer le
    texte situe apres ``fraiche`` sans toucher aux lignes precedentes.
    """
    if not fin_liste_avec_fragment_suspect(texte_initial):
        return texte_initial
    initial = _mots_asr_avec_spans(texte_initial)
    fenetre = _mots_asr_avec_spans(texte_fenetre)
    if not initial or not fenetre:
        return texte_initial

    exclus = {"merci", "bonjour", "bonsoir", "commande", "carton", "kilos", "litres"}
    ancrage: tuple[int, int, int] | None = None
    # Une paire ``2 kilos`` / ``deux kilos`` est une ancre temporelle forte
    # dans une commande longue, meme si le mot precedent (creme/canne) a ete
    # deforme. Elle permet de ne remplacer que l'article incomplet apres la
    # quantite, jamais l'article precedent.
    for taille in (3, 2):
        for index_initial in range(len(initial) - taille, -1, -1):
            reference = [mot for mot, _ in initial[index_initial:index_initial + taille]]
            for index_fenetre in range(len(fenetre) - taille, -1, -1):
                if [mot for mot, _ in fenetre[index_fenetre:index_fenetre + taille]] == reference:
                    ancrage = index_initial, index_fenetre, taille
                    break
            if ancrage is not None:
                break
        if ancrage is not None:
            break
    if ancrage is not None:
        fin_prefixe = initial[ancrage[0] + ancrage[2] - 1][1][1]
        debut_suffixe = fenetre[ancrage[1] + ancrage[2] - 1][1][1]
        suffixe = str(texte_fenetre or "")[debut_suffixe:].lstrip(" ,;:.-â€“â€”")
        if len(_mots_asr_avec_spans(suffixe)) >= 3:
            prefixe = str(texte_initial or "")[:fin_prefixe].rstrip()
            return f"{prefixe} {suffixe}".strip()

    ancrage_simple: tuple[int, int] | None = None
    for index_initial in range(len(initial) - 1, -1, -1):
        mot = initial[index_initial][0]
        if len(mot) < 6 or mot in exclus:
            continue
        for index_fenetre in range(len(fenetre) - 1, -1, -1):
            if fenetre[index_fenetre][0] == mot:
                ancrage_simple = index_initial, index_fenetre
                break
        if ancrage_simple is not None:
            break
    if ancrage_simple is None:
        return texte_initial

    debut_suffixe = fenetre[ancrage_simple[1]][1][1]
    suffixe = str(texte_fenetre or "")[debut_suffixe:].lstrip(" ,;:.-â€“â€”")
    if len(_mots_asr_avec_spans(suffixe)) < 3:
        return texte_initial
    fin_prefixe = initial[ancrage_simple[0]][1][1]
    prefixe = str(texte_initial or "")[:fin_prefixe].rstrip()
    return f"{prefixe} {suffixe}".strip()


def retranscrire_suffixe_liste_fragmentaire(
    modele: WhisperModel,
    chemin_audio: Path,
    *,
    duree_audio: float,
    hotwords: str | None,
    texte_initial: str,
) -> tuple[str, dict[str, Any]]:
    """Rejoue les 22 dernieres secondes uniquement lorsqu'un fragment le justifie."""
    debut = max(0.0, duree_audio - 22.0)
    generateur, _ = modele.transcribe(
        str(chemin_audio),
        language="fr",
        task="transcribe",
        initial_prompt=PROMPT_METIER,
        hotwords=hotwords or None,
        beam_size=max(3, BEAM_SIZE),
        temperature=0.0,
        word_timestamps=False,
        vad_filter=False,
        condition_on_previous_text=False,
        clip_timestamps=[debut, duree_audio],
    )
    texte_fenetre = " ".join(
        str(segment.text or "").strip()
        for segment in generateur
        if str(segment.text or "").strip()
    ).strip()
    return recuperer_suffixe_liste_fragmentaire(texte_initial, texte_fenetre), {
        "fenetre_debut_secondes": round(debut, 3),
        "fenetre_fin_secondes": round(duree_audio, 3),
        "texte_fenetre": texte_fenetre,
    }


def _meilleur_ancrage(
    source: list[str],
    cible: list[str],
    *,
    rechercher_depuis_fin: bool,
) -> tuple[int, int] | None:
    """Trouve une suite de mots commune; retourne (debut, taille) dans cible."""
    maximum = min(12, len(source), len(cible))
    for taille in range(maximum, 1, -1):
        reference = source[-taille:] if rechercher_depuis_fin else source[:taille]
        positions = range(len(cible) - taille, -1, -1) if rechercher_depuis_fin else range(len(cible) - taille + 1)
        for position in positions:
            if cible[position:position + taille] == reference:
                return position, taille
    return None


def extraire_pont_fenetre_asr(
    texte_gauche: str,
    texte_fenetre: str,
    texte_droite: str,
) -> str:
    """Extrait, entre deux segments contigus, le seul pont prouve par l'audio.

    Le passage secondaire couvre la frontiere temporelle avec VAD desactive.
    Il ne peut completer le texte principal que si ses deux extremites sont
    ancrees sur la fin et le debut deja transcrits. On n'ajoute donc jamais
    un produit invente ou un simple candidat catalogue.
    """
    gauche = _mots_asr_avec_spans(texte_gauche)
    fenetre = _mots_asr_avec_spans(texte_fenetre)
    droite = _mots_asr_avec_spans(texte_droite)
    if not gauche or not fenetre or not droite:
        return ""

    gauche_mots = [mot for mot, _ in gauche]
    fenetre_mots = [mot for mot, _ in fenetre]
    droite_mots = [mot for mot, _ in droite]
    ancrage_gauche = _meilleur_ancrage(
        gauche_mots, fenetre_mots, rechercher_depuis_fin=True
    )
    if ancrage_gauche is None:
        return ""
    debut_droite = ancrage_gauche[0] + ancrage_gauche[1]
    # La droite est cherchee apres la gauche afin d'eviter de reunir deux
    # repetitions differentes d'une meme longue liste.
    maximum = min(12, len(droite_mots), len(fenetre_mots) - debut_droite)
    ancrage_droite: tuple[int, int] | None = None
    for taille in range(maximum, 1, -1):
        reference = droite_mots[:taille]
        for position in range(debut_droite, len(fenetre_mots) - taille + 1):
            if fenetre_mots[position:position + taille] == reference:
                ancrage_droite = position, taille
                break
        if ancrage_droite is not None:
            break
    if ancrage_droite is None or ancrage_droite[0] <= debut_droite:
        return ""

    debut_original = fenetre[debut_droite - 1][1][1]
    fin_original = fenetre[ancrage_droite[0]][1][0]
    pont = str(texte_fenetre or "")[debut_original:fin_original]
    # La ponctuation finale appartient au pont : elle separe le dernier mot
    # recupere du debut du segment droit (ex. huile, 90 oeufs). On retire
    # seulement le separateur deja porte par l'ancre gauche.
    return pont.lstrip(" ,;:.-â€“â€”").rstrip()


def completer_frontieres_longue_liste(
    modele: WhisperModel,
    chemin_audio: Path,
    segments: list[Any],
    *,
    duree_audio: float,
    hotwords: str | None,
) -> tuple[str, int, list[dict[str, Any]]]:
    """Repasse les frontieres VAD d'une longue liste avec une fenetre audio.

    Chaque fenetre recouvre 10 s avant/apres la frontiere. Le texte initial
    reste la base; seuls les mots situes entre deux ancrages concordants sont
    ajoutes. Cela cible les omissions entre segments sans substituer une
    transcription complete ni envoyer de donnees a l'ERP.
    """
    textes = [str(segment.text or "").strip() for segment in segments]
    if len(textes) < 2 or duree_audio <= 0.0:
        return " ".join(texte for texte in textes if texte).strip(), 0, []

    morceaux: list[str] = [textes[0]]
    ponts_ajoutes = 0
    diagnostics: list[dict[str, Any]] = []
    for index in range(len(textes) - 1):
        frontiere = float(getattr(segments[index], "end", 0.0) or 0.0)
        # Quinze secondes de chaque cote couvrent les enumerations denses
        # sans refaire l'audio entier. La large zone commune permet de
        # retrouver aussi les mots deformes juste avant la coupure VAD.
        debut = max(0.0, frontiere - 15.0)
        fin = min(duree_audio, frontiere + 15.0)
        fenetre_generateur, _ = modele.transcribe(
            str(chemin_audio),
            language="fr",
            task="transcribe",
            initial_prompt=PROMPT_METIER,
            hotwords=hotwords or None,
            beam_size=max(3, BEAM_SIZE),
            temperature=0.0,
            word_timestamps=False,
            vad_filter=False,
            condition_on_previous_text=False,
            clip_timestamps=[debut, fin],
        )
        texte_fenetre = " ".join(
            str(segment.text or "").strip()
            for segment in fenetre_generateur
            if str(segment.text or "").strip()
        ).strip()
        pont = extraire_pont_fenetre_asr(
            textes[index], texte_fenetre, textes[index + 1]
        )
        diagnostics.append({
            "frontiere_secondes": round(frontiere, 3),
            "fenetre_debut_secondes": round(debut, 3),
            "fenetre_fin_secondes": round(fin, 3),
            "texte_fenetre": texte_fenetre,
            "pont_confirme": pont,
        })
        if pont:
            morceaux.append(pont)
            ponts_ajoutes += 1
        morceaux.append(textes[index + 1])
    return (
        " ".join(morceau for morceau in morceaux if morceau).strip(),
        ponts_ajoutes,
        diagnostics,
    )


def _fenetres_couvrantes_longue_liste(
    duree_audio: float,
    *,
    largeur: float = 22.0,
    chevauchement: float = 4.0,
) -> list[tuple[float, float]]:
    """Decoupe un long audio en fenetres qui se recouvrent reellement."""
    if duree_audio <= 0.0:
        return []
    largeur = max(8.0, largeur)
    pas = max(4.0, largeur - max(1.0, chevauchement))
    resultat: list[tuple[float, float]] = []
    debut = 0.0
    while debut < duree_audio:
        fin = min(duree_audio, debut + largeur)
        couple = (round(debut, 3), round(fin, 3))
        if not resultat or resultat[-1] != couple:
            resultat.append(couple)
        if fin >= duree_audio:
            break
        debut += pas
    # Garantit la couverture de la toute fin sans creer une fenetre dupliquee.
    dernier_debut = max(0.0, duree_audio - largeur)
    dernier = (round(dernier_debut, 3), round(duree_audio, 3))
    if resultat[-1] != dernier:
        resultat.append(dernier)
    return resultat


def _score_couverture_contexte_asr(
    texte: str,
    hotwords: str | None,
) -> tuple[float, set[str]]:
    """Mesure seulement les termes fournis avant ASR par le cadencier client."""
    tokens_texte = [mot for mot, _ in _mots_asr_avec_spans(texte)]
    if not tokens_texte or not hotwords:
        return 0.0, set()
    trouves: set[str] = set()
    score = 0.0
    for terme in (partie.strip() for partie in hotwords.split(",")):
        tokens_terme = [mot for mot, _ in _mots_asr_avec_spans(terme)]
        if not tokens_terme:
            continue
        cle = " ".join(tokens_terme)
        if len(tokens_terme) >= 2:
            present = any(
                tokens_texte[index:index + len(tokens_terme)] == tokens_terme
                for index in range(len(tokens_texte) - len(tokens_terme) + 1)
            )
            poids = min(4.0, float(len(tokens_terme)))
        else:
            present = len(tokens_terme[0]) >= 5 and tokens_terme[0] in tokens_texte
            poids = 0.5
        if present:
            trouves.add(cle)
            score += poids
    return score, trouves


def transcription_fenetres_preferee(
    texte_initial: str,
    texte_fenetres: str,
    hotwords: str | None,
) -> bool:
    """Accepte une mosaique audio seulement si elle augmente la couverture.

    La comparaison ne regarde jamais une commande ERP : uniquement les deux
    passages ASR du meme audio et le vocabulaire de production connu avant
    l'appel. Les termes deja couverts ne peuvent pas disparaitre en masse.
    """
    initial = " ".join(str(texte_initial or "").split()).strip()
    alternatif = " ".join(str(texte_fenetres or "").split()).strip()
    if not initial or not alternatif or len(alternatif) < 0.60 * len(initial):
        return False
    score_initial, termes_initial = _score_couverture_contexte_asr(initial, hotwords)
    score_alternatif, termes_alternatif = _score_couverture_contexte_asr(
        alternatif, hotwords
    )
    pertes = termes_initial - termes_alternatif
    perte_max = max(2, int(math.ceil(len(termes_initial) * 0.10)))
    return (
        score_alternatif >= score_initial + 4.0
        and len(pertes) <= perte_max
    )


def retranscrire_fenetres_couvrantes_longue_liste(
    modele: WhisperModel,
    chemin_audio: Path,
    *,
    duree_audio: float,
    hotwords: str | None,
) -> tuple[str, list[dict[str, Any]]]:
    """Produit une seconde transcription couvrante des longues enumerations."""
    texte_fusionne = ""
    diagnostics: list[dict[str, Any]] = []
    for debut, fin in _fenetres_couvrantes_longue_liste(duree_audio):
        generateur, _ = modele.transcribe(
            str(chemin_audio),
            language="fr",
            task="transcribe",
            initial_prompt=PROMPT_METIER,
            hotwords=hotwords or None,
            beam_size=max(3, BEAM_SIZE),
            temperature=0.0,
            word_timestamps=False,
            vad_filter=False,
            condition_on_previous_text=False,
            clip_timestamps=[debut, fin],
        )
        texte_fenetre = " ".join(
            str(segment.text or "").strip()
            for segment in generateur
            if str(segment.text or "").strip()
        ).strip()
        diagnostics.append({
            "fenetre_debut_secondes": debut,
            "fenetre_fin_secondes": fin,
            "texte_fenetre": texte_fenetre,
        })
        if texte_fenetre:
            texte_fusionne = fusionner_transcription_avec_fin(
                texte_fusionne,
                texte_fenetre,
            )
    return texte_fusionne, diagnostics


def fin_transcription_suspecte(
    texte: str,
    *,
    fin_dernier_segment: float | None = None,
    duree_audio: float | None = None,
) -> bool:
    """Detecte une fin probablement coupee sans deviner le produit manquant."""
    sans_accents = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", str(texte or ""))
        if not unicodedata.combining(caractere)
    )
    normalise = re.sub(r"[^a-z0-9]+", " ", sans_accents.casefold()).strip()
    if not normalise:
        return True
    ponctuation_ouverte = bool(
        re.search(r"(?:[,;:]|[-–—])\s*$", str(texte or "").strip())
    )
    dernier = normalise.split()[-1]
    fragment_lexical = bool(
        dernier in _FINS_ASR_FRAGMENTAIRES
        or (
            len(dernier) <= 3
            and dernier not in _MOTS_COURTS_PRODUIT_COMPLETS
            and re.search(r"\b\d+(?:\.\d+)?\s+[a-z]{1,3}$", normalise)
        )
    )
    fermeture_normale = bool(re.search(
        r"\b(?:au revoir|bonne journee|bonne soiree|merci beaucoup|merci)$",
        normalise,
    ))
    coupure_vad = bool(
        fin_dernier_segment is not None
        and duree_audio is not None
        and duree_audio - fin_dernier_segment >= 2.5
        and not fermeture_normale
    )
    return ponctuation_ouverte or fragment_lexical or coupure_vad


def reprise_transcription_preferee(texte_initial: str, texte_reprise: str) -> bool:
    """Accepte une reprise seulement si elle prolonge une transcription stable."""
    initial = " ".join(str(texte_initial or "").split())
    reprise = " ".join(str(texte_reprise or "").split())
    if len(reprise) < len(initial) + 4:
        return False
    largeur = min(len(initial), len(reprise))
    if largeur < 12:
        return False
    stabilite = SequenceMatcher(
        None,
        initial[:largeur].casefold(),
        reprise[:largeur].casefold(),
    ).ratio()
    return stabilite >= 0.72 and not fin_transcription_suspecte(reprise)


def fusionner_transcription_avec_fin(
    texte_initial: str,
    texte_fin: str,
) -> str:
    """Fusionne une fenetre finale ASR sans repeter son chevauchement.

    La fenetre est issue du meme fichier audio, pas d'une source externe. Un
    chevauchement lexical est retire lorsqu'il est retrouve ; sinon la fin
    est simplement ajoutee. Les repetitions produit eventuelles restent
    ensuite traitees par le dedoublonnage metier habituel.
    """
    initial = " ".join(str(texte_initial or "").split()).strip()
    fin = " ".join(str(texte_fin or "").split()).strip()
    if not initial:
        return fin
    if not fin or fin_transcription_suspecte(fin):
        return initial

    def mots_et_spans(texte: str) -> tuple[list[str], list[tuple[int, int]]]:
        mots: list[str] = []
        spans: list[tuple[int, int]] = []
        for match in re.finditer(r"[\w%]+", texte, flags=re.UNICODE):
            sans_accents = "".join(
                caractere
                for caractere in unicodedata.normalize("NFKD", match.group())
                if not unicodedata.combining(caractere)
            )
            mots.append(sans_accents.casefold())
            spans.append(match.span())
        return mots, spans

    mots_initial, _ = mots_et_spans(initial)
    mots_fin, spans_fin = mots_et_spans(fin)
    if not mots_fin:
        return initial

    max_chevauchement = min(16, len(mots_initial), len(mots_fin))
    chevauchement = 0
    for taille in range(max_chevauchement, 1, -1):
        if mots_initial[-taille:] == mots_fin[:taille]:
            chevauchement = taille
            break

    if chevauchement:
        debut_nouveau = spans_fin[chevauchement - 1][1]
        ajout = fin[debut_nouveau:].lstrip(" ,;:.-–—")
    else:
        ajout = fin

    if not ajout:
        return initial
    return f"{initial.rstrip()} {ajout}".strip()

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

    reprise_fin_audio = False
    mode_reprise_fin_audio = ""
    texte_initial_fragmentaire = ""
    fin_segment = float(segments[-1].end) if segments else None
    duree_audio = float(getattr(informations, "duration", 0.0) or 0.0)
    if fin_transcription_suspecte(
        texte_complet,
        fin_dernier_segment=fin_segment,
        duree_audio=duree_audio,
    ):
        reprise_generateur, informations_reprise = modele.transcribe(
            str(chemin_audio),
            language="fr",
            task="transcribe",
            initial_prompt=PROMPT_METIER,
            hotwords=hotwords or None,
            beam_size=max(3, BEAM_SIZE),
            temperature=0.0,
            word_timestamps=WORD_TIMESTAMPS,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        segments_reprise = list(reprise_generateur)
        texte_reprise = " ".join(
            segment.text.strip()
            for segment in segments_reprise
            if segment.text.strip()
        ).strip()
        if reprise_transcription_preferee(texte_complet, texte_reprise):
            texte_initial_fragmentaire = texte_complet
            texte_complet = texte_reprise
            segments = segments_reprise
            informations = informations_reprise
            reprise_fin_audio = True
            mode_reprise_fin_audio = "seconde_passe_complete_sans_vad"
        elif duree_audio > 0.0 and fin_segment is not None:
            # Une longue commande peut faire ignorer une courte reprise apres
            # une pause (produit final ou formule de cloture), meme sans VAD.
            # Une fenetre finale avec six secondes de chevauchement force le
            # decodeur a ecouter cette zone sans lui fournir la verite cible.
            debut_fenetre = max(0.0, fin_segment - 6.0)
            fin_generateur, _ = modele.transcribe(
                str(chemin_audio),
                language="fr",
                task="transcribe",
                initial_prompt=PROMPT_METIER,
                hotwords=hotwords or None,
                beam_size=max(3, BEAM_SIZE),
                temperature=0.0,
                word_timestamps=WORD_TIMESTAMPS,
                vad_filter=False,
                condition_on_previous_text=False,
                clip_timestamps=[debut_fenetre, duree_audio],
            )
            segments_fin = list(fin_generateur)
            texte_fin = " ".join(
                segment.text.strip()
                for segment in segments_fin
                if segment.text.strip()
            ).strip()
            texte_fusionne = fusionner_transcription_avec_fin(
                texte_complet,
                texte_fin,
            )
            if texte_fusionne != texte_complet:
                texte_initial_fragmentaire = texte_complet
                texte_complet = texte_fusionne
                segments.extend(segments_fin)
                reprise_fin_audio = True
                mode_reprise_fin_audio = "fenetre_finale_avec_chevauchement"

    # Une fin correcte n'exclut pas une omission *au milieu* d'une longue
    # enumeration : le cas typique est une coupure VAD entre deux segments,
    # avec un produit saute alors que les produits avant/apres sont entendus.
    # La reprise est bornee aux vraies longues listes et n'ajoute que le pont
    # commun aux deux segments, confirme par une fenetre audio recouvrante.
    reprise_interieure_audio = False
    nb_ponts_interieurs_audio = 0
    diagnostics_reprise_interieure: list[dict[str, Any]] = []
    reprise_fenetres_couvrantes = False
    diagnostics_fenetres_couvrantes: list[dict[str, Any]] = []
    liste_longue_a_controler = transcription_liste_longue_a_controler(
        texte_complet,
        duree_audio=duree_audio,
        nb_segments=len(segments),
    )
    if liste_longue_a_controler:
        (
            texte_complete,
            nb_ponts_interieurs_audio,
            diagnostics_reprise_interieure,
        ) = (
            completer_frontieres_longue_liste(
                modele,
                chemin_audio,
                segments,
                duree_audio=duree_audio,
                hotwords=hotwords,
            )
        )
        if texte_complete != texte_complet:
            if not texte_initial_fragmentaire:
                texte_initial_fragmentaire = texte_complet
            texte_complet = texte_complete
            reprise_interieure_audio = nb_ponts_interieurs_audio > 0

    reprise_suffixe_fragmentaire = False
    diagnostic_suffixe_fragmentaire: dict[str, Any] = {}
    if (
        liste_longue_a_controler
        and fin_liste_avec_fragment_suspect(texte_complet)
    ):
        texte_suffixe, diagnostic_suffixe_fragmentaire = (
            retranscrire_suffixe_liste_fragmentaire(
                modele,
                chemin_audio,
                duree_audio=duree_audio,
                hotwords=hotwords,
                texte_initial=texte_complet,
            )
        )
        if texte_suffixe != texte_complet:
            if not texte_initial_fragmentaire:
                texte_initial_fragmentaire = texte_complet
            texte_complet = texte_suffixe
            reprise_suffixe_fragmentaire = True

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
        "reprise_fin_audio": reprise_fin_audio,
        "mode_reprise_fin_audio": mode_reprise_fin_audio,
        "texte_initial_fragmentaire": texte_initial_fragmentaire,
        "reprise_interieure_audio": reprise_interieure_audio,
        "nb_ponts_interieurs_audio": nb_ponts_interieurs_audio,
        "diagnostics_reprise_interieure": diagnostics_reprise_interieure,
        "reprise_fenetres_couvrantes": reprise_fenetres_couvrantes,
        "diagnostics_fenetres_couvrantes": diagnostics_fenetres_couvrantes,
        "reprise_suffixe_fragmentaire": reprise_suffixe_fragmentaire,
        "diagnostic_suffixe_fragmentaire": diagnostic_suffixe_fragmentaire,
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
