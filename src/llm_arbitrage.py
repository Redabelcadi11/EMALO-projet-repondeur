"""
Module d'arbitrage sémantique par LLM local (Ollama).

Ce module est appelé APRÈS l'extraction classique pour résoudre
les ambiguïtés phonétiques que l'algorithme classique ne peut pas résoudre.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1:70b"
TIMEOUT_SECONDS = 60


def _call_ollama(
    prompt: str,
    model: str = OLLAMA_MODEL,
    num_predict: int = 256,
) -> str | None:
    """Appelle Ollama en local et retourne la réponse brute."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,  # 0 = déterministe, pas de créativité
            "num_predict": num_predict,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = json.load(resp)
            return data.get("response", "").strip()
    except urllib.error.URLError as exc:
        logger.warning("Ollama indisponible : %s", exc)
        return None
    except Exception as exc:
        logger.warning("Erreur Ollama inattendue : %s", exc)
        return None


def ollama_disponible() -> bool:
    """Vérifie qu'Ollama répond et que le modèle est chargé."""
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp)
            models = [m["name"] for m in data.get("models", [])]
            return any(OLLAMA_MODEL.split(":")[0] in m for m in models)
    except Exception:
        return False


def arbitrer_produit_phonetique(
    mention_texte: str,
    candidats: list[dict[str, Any]],
    client_nom: str = "",
) -> dict[str, Any] | None:
    """
    Demande au LLM de choisir parmi les candidats celui qui correspond
    sémantiquement à la mention phonétique transcrite par Whisper.
    
    Args:
        mention_texte: Le texte brut transcrit (ex: "chantilly de bique")
        candidats: Liste des candidats du cadencier [{libelle, code, ...}, ...]
        client_nom: Nom du client pour contextualiser
    
    Returns:
        Le candidat choisi, ou None si aucun match.
    """
    if not candidats:
        return None

    # Préparer la liste numérotée des candidats
    candidats_str = "\n".join(
        f"{i+1}. [{c.get('code_article', '')}] "
        f"{c.get('libelle_article') or c.get('libelle') or c.get('designation', '')}"
        for i, c in enumerate(candidats[:15])  # max 15 candidats
    )

    prompt = f"""Tu es un assistant expert en restauration professionnelle et en produits alimentaires français.

Un client du restaurant "{client_nom}" a passé une commande vocale. La transcription automatique a retranscrit phonétiquement la commande.

Texte transcrit par le logiciel vocal (peut contenir des erreurs phonétiques) :
"{mention_texte}"

Voici les produits disponibles dans le catalogue de ce client :
{candidats_str}

Ta mission : Quel est le numéro du produit (de la liste ci-dessus) que le client souhaitait commander ?
- Réponds UNIQUEMENT avec le numéro (ex: "3") ou "0" si aucun produit ne correspond.
- N'explique rien, ne justifie pas, réponds seulement avec le numéro.
- Tiens compte des erreurs phonétiques typiques du français (ex: "bique" peut être "Debic", "debi", etc.)
- Si le texte est ambigu et que plusieurs produits pourraient convenir, choisis le plus probable dans un contexte de restauration.

Réponse :"""

    response = _call_ollama(prompt)
    if not response:
        return None

    # Parser la réponse (on attend un chiffre)
    try:
        num = int(response.strip().split()[0].rstrip("."))
        if 1 <= num <= len(candidats):
            return candidats[num - 1]
        return None
    except (ValueError, IndexError):
        return None


def arbitrer_client_ambigu(
    zone_client: str,
    candidats: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Arbitre uniquement entre les clients actifs deja preselctionnes."""
    candidats = list(candidats[:15])
    if not candidats:
        return None

    lignes_candidats: list[str] = []
    for index, candidat in enumerate(candidats, start=1):
        adresse = " ".join(
            str(candidat.get(champ, "") or "").strip()
            for champ in ("adresse_1", "adresse_2", "code_postal")
            if str(candidat.get(champ, "") or "").strip()
        )
        lignes_candidats.append(
            f"{index}. [{candidat.get('code_client', '')}] "
            f"{candidat.get('nom_client', '')} | "
            f"ville: {candidat.get('ville', '')} | adresse: {adresse}"
        )
    candidats_str = "\n".join(lignes_candidats)
    prompt = f"""Tu arbitres l'identification d'un client de restauration.

Presentation transcrite (elle peut contenir des erreurs phonetiques) :
"{zone_client}"

Choisis UN SEUL numero uniquement parmi les clients actifs ci-dessous.
Un mot qui apparait seulement dans une adresse n'est pas une preuve
d'enseigne. Tiens compte des villes prononcees phonetiquement.
Reponds UNIQUEMENT par le numero choisi, ou 0 si aucun choix n'est fiable.

Clients actifs candidats :
{candidats_str}

Reponse :"""
    response = _call_ollama(prompt, num_predict=16)
    if not response:
        return None
    match = re.search(r"\b(\d{1,2})\b", response)
    if not match:
        return None
    index = int(match.group(1))
    if 1 <= index <= len(candidats):
        return candidats[index - 1]
    return None


def normaliser_quantite_phonetique(
    mention_texte: str,
    unite_article: str,
    client_nom: str = "",
) -> dict[str, Any] | None:
    """
    Demande au LLM de résoudre une ambiguïté de quantité/unité.
    
    Ex: Le client dit "trois cartons" mais l'article se vend par pièce.
    Le LLM sait qu'un carton de lait UHT contient 12 pièces.
    
    Returns:
        {"quantite": float, "unite": str} ou None
    """
    prompt = f"""Tu es un expert en restauration professionnelle.

Un client a dit : "{mention_texte}"
L'unité de vente de l'article est : "{unite_article}"

Quelle est la quantité à commander dans l'unité "{unite_article}" ?
- Réponds UNIQUEMENT avec un nombre décimal (ex: "12" ou "2.5")
- Réponds "?" si tu ne peux pas déterminer la quantité.
- Ne dis rien d'autre.

Quantité en {unite_article} :"""

    response = _call_ollama(prompt)
    if not response or response == "?":
        return None

    try:
        quantite = float(response.strip().split()[0].replace(",", "."))
        return {"quantite": quantite, "unite": unite_article}
    except ValueError:
        return None
