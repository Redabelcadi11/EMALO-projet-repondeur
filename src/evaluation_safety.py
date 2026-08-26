from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "config" / "evaluation-safety.json"


@dataclass(frozen=True)
class EvaluationSafetyPolicy:
    valid: bool
    mode: str
    allow_aggressive_profiles: bool
    allow_historical_erp_enrichment: bool
    allow_client_specific_learned_rules: bool
    allowed_prediction_rule_origins: frozenset[str]
    reason: str = ""


def load_evaluation_safety_policy() -> EvaluationSafetyPolicy:
    try:
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return EvaluationSafetyPolicy(
            valid=False,
            mode="strict_no_target_leakage",
            allow_aggressive_profiles=False,
            allow_historical_erp_enrichment=False,
            allow_client_specific_learned_rules=False,
            allowed_prediction_rule_origins=frozenset(),
            reason=f"politique absente ou illisible: {exc}",
        )
    if not isinstance(payload, dict):
        return EvaluationSafetyPolicy(
            valid=False,
            mode="strict_no_target_leakage",
            allow_aggressive_profiles=False,
            allow_historical_erp_enrichment=False,
            allow_client_specific_learned_rules=False,
            allowed_prediction_rule_origins=frozenset(),
            reason="la politique doit etre un objet JSON",
        )
    origins = frozenset(
        str(value).strip()
        for value in payload.get("allowed_prediction_rule_origins", [])
        if str(value).strip()
    )
    return EvaluationSafetyPolicy(
        valid=True,
        mode=str(payload.get("mode") or "strict_no_target_leakage"),
        allow_aggressive_profiles=payload.get("allow_aggressive_profiles") is True,
        allow_historical_erp_enrichment=(
            payload.get("allow_historical_erp_enrichment") is True
        ),
        allow_client_specific_learned_rules=(
            payload.get("allow_client_specific_learned_rules") is True
        ),
        allowed_prediction_rule_origins=origins,
    )


def filter_prediction_rules(rules: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only explicitly safe, general rules; fail closed on bad policy."""
    policy = load_evaluation_safety_policy()
    if not policy.valid:
        return []
    safe: list[dict[str, Any]] = []
    for rule in rules:
        origin = str(rule.get("origin") or "").strip()
        if origin not in policy.allowed_prediction_rule_origins:
            continue
        if not policy.allow_client_specific_learned_rules and any(
            key.startswith("client_") and rule.get(key)
            for key in rule
        ):
            continue
        safe.append(rule)
    return safe

