"""Inspection and approval profile loading utilities."""

from __future__ import annotations

from pathlib import Path

import yaml

from spot_train.models import ApprovalProfile, InspectionProfile

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PROFILE_ROOT = _PROJECT_ROOT / "profiles"


def inspection_profile_path(name: str, base_dir: Path | None = None) -> Path:
    return _resolve_profile_path(name, category="inspection", base_dir=base_dir)


def approval_profile_path(name: str, base_dir: Path | None = None) -> Path:
    return _resolve_profile_path(name, category="approval", base_dir=base_dir)


def load_inspection_profile(name: str, base_dir: Path | None = None) -> InspectionProfile:
    payload = _load_yaml(inspection_profile_path(name, base_dir))
    return InspectionProfile.model_validate(payload)


def load_approval_profile(name: str, base_dir: Path | None = None) -> ApprovalProfile:
    payload = _load_yaml(approval_profile_path(name, base_dir))
    return ApprovalProfile.model_validate(payload)


def load_default_profiles(
    base_dir: Path | None = None,
) -> tuple[ApprovalProfile, InspectionProfile]:
    approval = load_approval_profile("default_dry_run", base_dir)
    inspection = load_inspection_profile("lab_readiness_v1", base_dir)
    return approval, inspection


def _resolve_profile_path(name: str, *, category: str, base_dir: Path | None) -> Path:
    root = base_dir or _DEFAULT_PROFILE_ROOT
    candidate = Path(name)
    if candidate.suffix != ".yaml":
        candidate = candidate.with_suffix(".yaml")
    if candidate.is_absolute():
        return candidate
    return root / category / candidate.name


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in profile file: {path}")
    return payload


__all__ = [
    "approval_profile_path",
    "inspection_profile_path",
    "load_approval_profile",
    "load_default_profiles",
    "load_inspection_profile",
]
