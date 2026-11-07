"""Diff the current catalog against a previous immutable snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_model_ledger.load import load_fx, load_models, load_vendors
from ai_model_ledger.validate import canonical, price_fingerprint


def public(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not str(key).startswith("_")}


def snapshot_date(models: list[dict[str, Any]]) -> str:
    return max(model["verified_at"] for model in models)


def build_snapshot(root: Path) -> dict[str, Any]:
    models = [public(model) for model in load_models(root)]
    models.sort(key=lambda model: model["id"])
    return {
        "schema_version": 1,
        "snapshot_date": snapshot_date(models),
        "fx": public(load_fx(root)),
        "vendors": load_vendors(root),
        "models": models,
    }


def dump_snapshot(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def snapshot_paths(root: Path) -> list[Path]:
    directory = root / "snapshots"
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def read_snapshot(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Change:
    kind: str
    model_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None

    @property
    def model(self) -> dict[str, Any]:
        return self.after or self.before or {}


def _meta_fingerprint(model: dict[str, Any]) -> Any:
    return canonical(
        {
            "status": model.get("status"),
            "context": model.get("context"),
            "release": model.get("release"),
            "api_model_id": model.get("api_model_id"),
            "deployment_zh": model.get("deployment_zh"),
        }
    )


def diff_catalogs(
    baseline: list[dict[str, Any]] | None,
    current: list[dict[str, Any]],
) -> list[Change]:
    before = {model["id"]: model for model in (baseline or [])}
    after = {model["id"]: model for model in current}
    changes: list[Change] = []
    for model_id in sorted(set(before) | set(after)):
        old = before.get(model_id)
        new = after.get(model_id)
        if old is None:
            changes.append(Change("added", model_id, None, new))
            continue
        if new is None:
            changes.append(Change("removed", model_id, old, None))
            continue
        price_changed = price_fingerprint(old) != price_fingerprint(new)
        meta_changed = _meta_fingerprint(old) != _meta_fingerprint(new)
        if price_changed:
            changes.append(Change("price_changed", model_id, old, new))
        elif meta_changed:
            changes.append(Change("metadata_changed", model_id, old, new))
    return changes


def previous_snapshot(root: Path, current_date: str) -> dict[str, Any] | None:
    earlier = [path for path in snapshot_paths(root) if path.stem < current_date]
    if not earlier:
        return None
    return read_snapshot(earlier[-1])
