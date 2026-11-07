"""Append-only price history. Existing observations are never rewritten."""

from __future__ import annotations

from typing import Any

import yaml

from ai_model_ledger.validate import canonical


def render_history(model: dict[str, Any]) -> str:
    document = {
        "schema_version": 1,
        "model_id": model["id"],
        "observations": [
            {
                "id": f"{model['verified_at']}-initial",
                "observed_at": model["verified_at"],
                "kind": "initial",
                "source_url": model["source"]["url"],
                "billing": model["billing"],
                "conversion": model["conversion"],
                "note_zh": "首次建档。单价抄自当时核验的官方定价页，不回填更早、未经本账本核验的价格。",
            }
        ],
    }
    return yaml.safe_dump(
        document,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def extension_errors(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    """Return errors when current history is not an append-only extension of previous."""
    if previous is None:
        return []
    old_rows = previous.get("observations") or []
    new_rows = current.get("observations") or []
    if previous.get("model_id") != current.get("model_id"):
        return ["model_id 被改写"]
    if len(new_rows) < len(old_rows):
        return [f"历史从 {len(old_rows)} 条缩短到 {len(new_rows)} 条"]
    errors = []
    for index, old in enumerate(old_rows):
        if canonical(old) != canonical(new_rows[index]):
            errors.append(f"第 {index + 1} 条历史被改写（id={old.get('id')}）。只允许在末尾追加")
    return errors
