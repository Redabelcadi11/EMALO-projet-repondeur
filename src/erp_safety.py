from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = PROJECT_ROOT / "config" / "erp-safety.json"


class ERPWriteBlocked(RuntimeError):
    """Raised before any operation that could mutate the ERP."""


@dataclass(frozen=True)
class ERPSafetyStatus:
    policy_path: Path
    mode: str
    evaluation_lock: bool
    reads_allowed: bool
    writes_allowed: bool
    policy_valid: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_path": str(self.policy_path),
            "mode": self.mode,
            "evaluation_lock": self.evaluation_lock,
            "reads_allowed": self.reads_allowed,
            "writes_allowed": self.writes_allowed,
            "policy_valid": self.policy_valid,
            "reason": self.reason,
        }


def _policy_path() -> Path:
    # The policy location is deliberately not overridable from the environment:
    # otherwise a process could point at a permissive replacement policy.
    return DEFAULT_POLICY_PATH


def _load_policy() -> tuple[Path, dict[str, Any], str]:
    path = _policy_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return path, {}, f"politique absente ou illisible: {exc}"
    if not isinstance(payload, dict):
        return path, {}, "la politique ERP doit etre un objet JSON"
    return path, payload, ""


def erp_safety_status() -> ERPSafetyStatus:
    path, policy, load_error = _load_policy()
    if load_error:
        return ERPSafetyStatus(
            policy_path=path,
            mode="evaluation",
            evaluation_lock=True,
            reads_allowed=False,
            writes_allowed=False,
            policy_valid=False,
            reason=load_error,
        )

    mode = str(policy.get("mode") or "evaluation").strip().casefold()
    forced_mode = os.environ.get("REPONDEUR_ERP_MODE", "").strip().casefold()
    evaluation_lock = policy.get("evaluation_lock") is not False
    reads_allowed = policy.get("allow_erp_reads") is True
    configured_writes = policy.get("allow_erp_writes") is True

    reasons: list[str] = []
    if evaluation_lock:
        reasons.append("verrou d'evaluation actif")
    if mode != "production":
        reasons.append(f"mode={mode or 'indefini'}")
    if forced_mode and forced_mode != "production":
        reasons.append(f"REPONDEUR_ERP_MODE={forced_mode}")
    if not configured_writes:
        reasons.append("allow_erp_writes n'est pas true")

    confirmation_env = str(
        policy.get("write_confirmation_env") or "REPONDEUR_ERP_WRITE_CONFIRMATION"
    ).strip()
    confirmation_value = str(policy.get("write_confirmation_value") or "").strip()
    confirmation_ok = bool(
        confirmation_env
        and confirmation_value
        and os.environ.get(confirmation_env, "") == confirmation_value
    )
    if not confirmation_ok:
        reasons.append("confirmation de production absente")

    writes_allowed = not reasons
    return ERPSafetyStatus(
        policy_path=path,
        mode=mode,
        evaluation_lock=evaluation_lock,
        reads_allowed=reads_allowed,
        writes_allowed=writes_allowed,
        policy_valid=True,
        reason="; ".join(reasons) if reasons else "ecritures ERP explicitement autorisees",
    )


def assert_erp_read_allowed(operation: str = "lecture ERP") -> None:
    status = erp_safety_status()
    if not status.policy_valid or not status.reads_allowed:
        raise RuntimeError(
            f"[ERP_READ_BLOCKED] {operation}: {status.reason} "
            f"(politique={status.policy_path})"
        )


def assert_erp_write_allowed(operation: str, *, target: str = "Copilote ERP") -> None:
    status = erp_safety_status()
    if not status.writes_allowed:
        raise ERPWriteBlocked(
            f"[ERP_WRITE_BLOCKED] {operation} vers {target}: {status.reason} "
            f"(politique={status.policy_path})"
        )
