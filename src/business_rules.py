"""Activation explicite des règles métier expérimentales sûres."""
from __future__ import annotations

import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = PROJECT_ROOT / "config" / "regles-metier-sures.json"


def business_rule_enabled(name: str) -> bool:
    # Réservé aux évaluations A/B : le processus de production ne reçoit pas
    # cette variable. Elle permet de mesurer une règle isolée sans éditer la
    # configuration active ni exposer une quelconque vérité terrain.
    disabled = {
        item.strip()
        for item in os.environ.get("EMALO_DISABLED_BUSINESS_RULES", "").split(",")
        if item.strip()
    }
    if name in disabled:
        return False
    try:
        payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    return payload.get(name) is True
