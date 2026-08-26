from __future__ import annotations

"""Façade client: conserve le verrou téléphone et réduit la boucle produit->client."""

from typing import Any

from . import _clients_legacy as _legacy

_ORIGINAL_SCORE_CADENCIER = _legacy.calculer_score_cadencier


def calculer_score_cadencier(
    mentions_produits: list[dict[str, Any]],
    produits_client: list[dict[str, Any]],
) -> tuple[float, list[str], list[dict[str, Any]]]:
    """Le cadencier reste un départageur client, mais ne pèse plus 20 % seul.

    ``identifier_client`` multiplie ce score par 0,20. En ramenant ici le
    score à 25 % de sa valeur, son poids effectif devient 5 %, sans toucher au
    verrouillage par téléphone exact que les données BASCO rendent fiable.
    """
    score, raisons, details = _ORIGINAL_SCORE_CADENCIER(
        mentions_produits=mentions_produits,
        produits_client=produits_client,
    )
    return round(float(score) * 0.25, 2), raisons, details


_legacy.calculer_score_cadencier = calculer_score_cadencier

for _nom in dir(_legacy):
    if _nom.startswith("__"):
        continue
    globals()[_nom] = getattr(_legacy, _nom)

globals()["calculer_score_cadencier"] = calculer_score_cadencier
