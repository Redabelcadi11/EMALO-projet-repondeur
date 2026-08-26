from __future__ import annotations

from collections import defaultdict
from typing import Any


def indexer_lignes_par_segment(
    lignes_commande: list[dict[str, Any]] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Indexe les lignes par identifiant de segment, sans couplage positionnel.

    Le second index ne sert qu'aux anciennes extractions qui ne portaient pas
    encore de ``segment_id``. Il n'est utilise que lorsque le texte source est
    unique, afin de ne jamais reintroduire un decalage silencieux.
    """

    par_segment: dict[str, dict[str, Any]] = {}
    par_texte_source: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for ligne in lignes_commande or []:
        if not isinstance(ligne, dict):
            continue
        segment_ids = [
            str(segment_id or "").strip()
            for segment_id in (
                ligne.get("segment_ids")
                or [ligne.get("segment_id")]
            )
            if str(segment_id or "").strip()
        ]
        for segment_id in segment_ids:
            par_segment[segment_id] = ligne
        texte_source = str(ligne.get("texte_source") or "").strip()
        if texte_source:
            par_texte_source[texte_source].append(ligne)

    return par_segment, dict(par_texte_source)


def ligne_associee_au_segment(
    produit: dict[str, Any],
    lignes_par_segment: dict[str, dict[str, Any]],
    lignes_legacy_par_texte: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """Retrouve la ligne du meme segment, jamais celle du meme index."""

    segment_id = str(produit.get("segment_id") or "").strip()
    if segment_id:
        return lignes_par_segment.get(segment_id)

    # Compatibilite lecture seule des anciennes extractions : le rapprochement
    # par texte est accepte uniquement s'il est non ambigu.
    texte_source = str(produit.get("texte_source") or "").strip()
    candidates = lignes_legacy_par_texte.get(texte_source, [])
    return candidates[0] if len(candidates) == 1 else None
