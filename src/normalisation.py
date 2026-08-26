from __future__ import annotations

import re
import unicodedata
from typing import Any


MOTS_GENERIQUES_CLIENT = {
    "le",
    "la",
    "les",
    "un",
    "une",
    "restaurant",
    "resto",
    "hotel",
    "bar",
    "bistrot",
    "brasserie",
    "sarl",
    "sas",
    "sasu",
    "eurl",
    "societe",
}


def enlever_accents(texte: str) -> str:
    texte = unicodedata.normalize("NFD", texte)

    return "".join(
        caractere
        for caractere in texte
        if unicodedata.category(caractere) != "Mn"
    )


def normaliser_texte(valeur: Any) -> str:
    texte = "" if valeur is None else str(valeur)
    texte = enlever_accents(texte).lower()
    texte = re.sub(r"[^a-z0-9]+", " ", texte)

    return re.sub(r"\s+", " ", texte).strip()


def tokens_normalises(valeur: Any) -> list[str]:
    texte = normaliser_texte(valeur)

    if not texte:
        return []

    return texte.split()


def simplifier_nom_client(texte: str) -> str:
    tokens = tokens_normalises(texte)
    tokens = [
        token
        for token in tokens
        if token not in MOTS_GENERIQUES_CLIENT
    ]

    return " ".join(tokens)


def contient_sequence_tokens(
    tokens_texte: list[str],
    tokens_recherche: list[str],
) -> bool:
    if not tokens_recherche:
        return False

    taille = len(tokens_recherche)

    if taille > len(tokens_texte):
        return False

    for index in range(
        len(tokens_texte) - taille + 1
    ):
        if tokens_texte[index : index + taille] == tokens_recherche:
            return True

    return False

