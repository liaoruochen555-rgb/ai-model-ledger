"""Load ledger YAML and normalize dates to ISO strings."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT_MARKERS = ("pyproject.toml", "data", "schema")


class LoadError(ValueError):
    pass


def find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").is_file() and (candidate / "data").is_dir():
            return candidate
    raise LoadError("找不到账本根目录（需要 pyproject.toml 和 data/）")


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        raise LoadError("不要使用带时间的日期时间，只写日期")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def load_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoadError(f"无法读取 {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LoadError(f"{path} 不是合法 YAML：{exc}") from exc
    if data is None:
        raise LoadError(f"{path} 是空文件")
    return _normalize(data)


def load_fx(root: Path) -> dict[str, Any]:
    path = root / "data" / "fx" / "usd-cny.yaml"
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise LoadError("汇率文件必须是映射")
    data["_path"] = str(path)
    return data


def load_vendors(root: Path) -> list[dict[str, Any]]:
    data = load_yaml(root / "data" / "vendors.yaml")
    if not isinstance(data, list):
        raise LoadError("data/vendors.yaml 必须是列表")
    return data


def iter_model_paths(root: Path) -> list[Path]:
    directory = root / "data" / "models"
    if not directory.is_dir():
        raise LoadError("缺少 data/models/")
    return sorted(path for path in directory.glob("*.yaml") if path.is_file())


def load_models(root: Path) -> list[dict[str, Any]]:
    models = []
    for path in iter_model_paths(root):
        data = load_yaml(path)
        if not isinstance(data, dict):
            raise LoadError(f"{path.name} 必须是映射")
        data["_path"] = str(path.relative_to(root))
        models.append(data)
    return models


def load_history(root: Path, model_id: str) -> dict[str, Any] | None:
    path = root / "data" / "history" / f"{model_id}.yaml"
    if not path.is_file():
        return None
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise LoadError(f"{path.name} 必须是映射")
    data["_path"] = str(path.relative_to(root))
    return data


def schema_path(root: Path, name: str) -> Path:
    return root / "schema" / name
