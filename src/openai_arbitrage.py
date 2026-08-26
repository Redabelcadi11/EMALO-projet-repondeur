from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.runtime_paths import get_project_root


CONFIG_PATH = get_project_root() / "config" / "openai-recognition.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "model": "gpt-4.1",
    "temperature": 0,
    "timeout_seconds": 60,
    "candidate_limit": 5,
    "min_product_confidence": 0.72,
    "only_problematic": True,
    "max_products": 15,
    "max_retries": 2,
}


def load_config() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            config.update(loaded)
    # Verrou applicatif : le projet fonctionne exclusivement sur l'instance.
    # Une ancienne configuration ou une variable d'environnement ne peut pas
    # reactiver un service externe.
    config["enabled"] = False
    config["disabled_reason"] = "traitement_exclusivement_sur_instance_locale"
    return config


def api_key_available() -> bool:
    """Toujours faux : les services OpenAI externes sont interdits."""
    return False


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compact_client(candidat: dict[str, Any]) -> dict[str, Any]:
    return {
        "code_client": candidat.get("code_client", ""),
        "nom_client": candidat.get("nom_client", ""),
        "ville": candidat.get("ville", ""),
        "adresse_1": candidat.get("adresse_1", ""),
        "telephone": candidat.get("telephone", ""),
        "score_global": candidat.get("score_global", ""),
        "score_nom": candidat.get("score_nom", ""),
        "score_ville": candidat.get("score_ville", ""),
        "score_cadencier": candidat.get("score_cadencier", ""),
        "nb_commandes_recentes": candidat.get("nb_commandes_recentes", ""),
    }


def _compact_product(candidat: dict[str, Any]) -> dict[str, Any]:
    return {
        "code_article": candidat.get("code_article", ""),
        "libelle_article": candidat.get("libelle_article", ""),
        "unite": candidat.get("unite", ""),
        "prix": candidat.get("prix", ""),
        "dans_cadencier_client": bool(candidat.get("dans_cadencier_client")),
        "source_recherche": candidat.get("source_recherche", ""),
        "score_global": candidat.get("score_global", ""),
        "score_texte": candidat.get("score_texte", ""),
        "score_conditionnement": candidat.get("score_conditionnement", ""),
        "quantite_resolue": candidat.get("quantite_resolue", ""),
        "unite_resolue": candidat.get("unite_resolue", ""),
        "nb_ventes_article_total": candidat.get("nb_ventes_article_total", ""),
        "nb_ventes_article_recentes": candidat.get("nb_ventes_article_recentes", ""),
    }


def build_payload(commande: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    try:
        candidate_limit = int(config.get("candidate_limit") or 5)
    except (TypeError, ValueError):
        candidate_limit = 5

    produits = []
    for index, produit in enumerate(commande.get("produits") or []):
        candidats = [
            _compact_product(item)
            for item in (produit.get("candidats") or [])[:candidate_limit]
        ]
        produits.append(
            {
                "index": index,
                "texte_source": produit.get("texte_source", ""),
                "texte_produit": produit.get("texte_produit", ""),
                "produit_normalise": produit.get("produit_normalise", ""),
                "quantite_detectee": produit.get("quantite"),
                "unite_detectee": produit.get("unite_principale", ""),
                "quantite_actuelle": produit.get("quantite_resolue"),
                "unite_actuelle": produit.get("unite_resolue"),
                "ambigu": bool(produit.get("ambigu")),
                "produit_fiable": bool(produit.get("produit_fiable")),
                "raisons_ambiguite": produit.get("raisons_ambiguite", []),
                "candidats": candidats,
            }
        )

    return {
        "fichier": commande.get("fichier_transcription") or commande.get("fichier_audio"),
        "transcription": commande.get("transcription", ""),
        "statut_actuel": commande.get("statut"),
        "raisons_actuelles": commande.get("raisons_problematiques", []),
        "client_actuel": commande.get("client_retenu"),
        "clients_candidats": [
            _compact_client(item)
            for item in (commande.get("clients_candidats") or [])[:12]
        ],
        "date_livraison_actuelle": commande.get("date_livraison"),
        "produits_detectes": produits,
    }


def _call_openai(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    del payload, config
    raise RuntimeError(
        "API OpenAI desactivee : traitement exclusivement sur instance locale"
    )

def validate_decision(
    commande: dict[str, Any],
    decision: dict[str, Any],
    config: dict[str, Any],
) -> tuple[bool, list[str]]:
    errors: list[str] = []

    client_allowed = {
        str(item.get("code_client") or "").strip()
        for item in commande.get("clients_candidats") or []
    }
    client_code = str(decision.get("client_code") or "").strip()
    if not client_code or client_code not in client_allowed:
        errors.append("client_hors_candidats")

    produits = commande.get("produits") or []
    decisions = decision.get("produits") or []
    if len(decisions) != len(produits):
        errors.append("nombre_lignes_produits_incorrect")

    try:
        min_confidence = float(config.get("min_product_confidence") or 0.72)
    except (TypeError, ValueError):
        min_confidence = 0.72

    produits_par_index = {index: produit for index, produit in enumerate(produits)}
    for item in decisions:
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            errors.append("index_produit_invalide")
            continue
        produit = produits_par_index.get(index)
        if produit is None:
            errors.append(f"produit_{index}_inexistant")
            continue

        code = str(item.get("code_article") or "").strip()
        candidats = produit.get("candidats") or []
        allowed_all = {str(c.get("code_article") or "").strip() for c in candidats}
        allowed_cadencier = {
            str(c.get("code_article") or "").strip()
            for c in candidats
            if c.get("dans_cadencier_client")
        }
        allowed = allowed_all
        if not code or code not in allowed:
            errors.append(f"produit_{index}_hors_candidats")
        else:
            chosen = next(
                (c for c in candidats if str(c.get("code_article") or "").strip() == code),
                {},
            )
            meilleur_score_cadencier = max(
                (
                    float(c.get("score_global") or 0.0)
                    for c in candidats
                    if c.get("dans_cadencier_client")
                ),
                default=0.0,
            )
            if (
                not chosen.get("dans_cadencier_client")
                and allowed_cadencier
                and meilleur_score_cadencier >= 70.0
            ):
                errors.append(f"produit_{index}_global_malgre_cadencier_fiable")

        if item.get("quantite") in (None, "", 0):
            errors.append(f"produit_{index}_quantite_absente")
        if not str(item.get("unite") or "").strip():
            errors.append(f"produit_{index}_unite_absente")

        confidence = _float_or_none(item.get("confidence"))
        if confidence is not None and confidence < min_confidence:
            errors.append(f"produit_{index}_confidence_faible")

    return not errors, sorted(set(errors))


def apply_decision(commande: dict[str, Any], decision: dict[str, Any]) -> None:
    commande["client_retenu"] = str(decision.get("client_code") or "").strip()
    commande["decision_automatique_client"] = True
    commande["raisons_decision_client"] = [
        "openai_arbitrage_client"
    ]

    produits = commande.get("produits") or []
    produits_par_index = {index: produit for index, produit in enumerate(produits)}
    for item in decision.get("produits") or []:
        index = int(item.get("index"))
        produit = produits_par_index[index]
        code = str(item.get("code_article") or "").strip()
        candidat = next(
            (
                dict(candidat)
                for candidat in produit.get("candidats") or []
                if str(candidat.get("code_article") or "").strip() == code
            ),
            None,
        )
        if candidat is None:
            continue

        quantite = item.get("quantite")
        unite = str(item.get("unite") or "").strip()
        candidat["quantite_resolue"] = quantite
        candidat["unite_resolue"] = unite
        candidat.setdefault("raisons", [])
        candidat["raisons"].append("regle_selection=openai_arbitrage")
        candidat["regle_selection"] = "openai_arbitrage"

        produit["selection"] = candidat
        produit["quantite_resolue"] = quantite
        produit["unite_resolue"] = unite
        produit["produit_fiable"] = True
        produit["ambigu"] = False
        produit["raisons_ambiguite"] = []
        produit["selection_ia"] = {
            "code_article": code,
            "confidence": item.get("confidence"),
            "raison": item.get("raison", ""),
        }


def arbitrer_commande(commande: dict[str, Any]) -> dict[str, Any]:
    del commande
    return {
        "enabled": False,
        "api_key_available": False,
        "applied": False,
        "skipped": "traitement_exclusivement_sur_instance_locale",
    }
