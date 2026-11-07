"""Schema and ledger rules. Prices that do not match the stated FX rate fail."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from ai_model_ledger.load import (
    load_fx,
    load_history,
    load_models,
    load_vendors,
    load_yaml,
    schema_path,
)
from ai_model_ledger.money import MoneyError, convert, is_money_key, parse_money

REQUIRED_VENDORS = (
    "deepseek",
    "qwen",
    "moonshot",
    "zhipu",
    "openai",
    "anthropic",
    "google",
    "xai",
)

HEADLINE_MONEY_KEYS = (
    "input_per_1m",
    "output_per_1m",
    "cache_hit_input_per_1m",
    "cache_write_5m_per_1m",
    "cache_write_1h_per_1m",
    "cache_write_30m_per_1m",
    "cache_write_12h_per_1m",
)


class LedgerError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _validator(root: Path, schema_name: str) -> Draft202012Validator:
    schema = json.loads(schema_path(root, schema_name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _schema_errors(validator: Draft202012Validator, data: dict[str, Any], label: str) -> list[str]:
    errors = []
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        path = "/".join(str(part) for part in error.path) or "(root)"
        errors.append(f"{label}: {path} {error.message}")
    return errors


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise MoneyError(f"{field} 不是 ISO 日期：{value}") from exc


def _walk_money(node: Any, path: str, errors: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else key
            if is_money_key(key) and value is not None:
                try:
                    parse_money(value, child)
                except MoneyError as exc:
                    errors.append(str(exc))
            else:
                _walk_money(value, child, errors)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_money(value, f"{path}[{index}]", errors)


def canonical(value: Any) -> Any:
    """Stable structure for comparisons. Decimal strings ignore trailing zeros."""
    if isinstance(value, dict):
        result = {}
        for key in sorted(value):
            if key.startswith("_"):
                continue
            result[key] = canonical(value[key])
        return result
    if isinstance(value, list):
        return [canonical(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if text and all(part.isdigit() for part in text.replace(".", "", 1).split(".")) and text.count(".") <= 1:
            number = Decimal(text)
            rendered = format(number, "f")
            if "." in rendered:
                rendered = rendered.rstrip("0").rstrip(".")
            return rendered or "0"
        return value
    return value


def price_fingerprint(model: dict[str, Any]) -> Any:
    billing = model.get("billing") or {}
    return canonical(
        {
            "currency": billing.get("currency"),
            "headline": billing.get("headline"),
            "tiers": billing.get("tiers"),
            "scheduled": billing.get("scheduled"),
            "promotion": billing.get("promotion"),
            "alternate_lists": billing.get("alternate_lists"),
        }
    )


def _check_headline_matches_tier(model: dict[str, Any], label: str) -> list[str]:
    billing = model["billing"]
    tiers = billing.get("tiers") or []
    if not tiers:
        return []
    headlines = [tier for tier in tiers if tier.get("is_headline") is True]
    if len(headlines) != 1:
        return [f"{label}: 分档里必须且只能有一档 is_headline: true"]
    tier = headlines[0]
    headline = billing["headline"]
    errors = []
    if tier.get("id") != headline.get("id"):
        errors.append(f"{label}: headline.id 与分档 id 不一致")
    for key in HEADLINE_MONEY_KEYS:
        if tier.get(key) != headline.get(key):
            errors.append(f"{label}: headline.{key} 与标为 headline 的分档不一致")
    if tier.get("label_zh") != headline.get("label_zh"):
        errors.append(f"{label}: headline 标签与分档标签不一致")
    return errors


def _check_promotion(model: dict[str, Any], label: str) -> list[str]:
    promotion = (model.get("billing") or {}).get("promotion")
    if not promotion:
        return []
    rate = parse_money(promotion["discount_rate"], f"{label}.promotion.discount_rate")
    errors = []
    for tier in model["billing"].get("tiers") or [model["billing"]["headline"]]:
        for side in ("input", "output"):
            list_key = f"list_{side}_per_1m"
            live_key = f"{side}_per_1m"
            if list_key not in tier:
                continue
            expected = parse_money(tier[list_key], list_key) * rate
            actual = parse_money(tier[live_key], live_key)
            from ai_model_ledger.money import quantize

            if quantize(expected) != quantize(actual):
                errors.append(
                    f"{label}: {tier.get('id', 'headline')} 的{side}折后价不等于原价乘折扣"
                )
    return errors


def _check_conversion(model: dict[str, Any], fx: dict[str, Any], label: str) -> list[str]:
    if model["conversion"]["fx_id"] != fx["id"]:
        return [f"{label}: conversion.fx_id 必须是 {fx['id']}"]
    places = int(fx["rounding"]["decimal_places"])
    rate = parse_money(fx["rate"], "fx.rate")
    headline = model["billing"]["headline"]
    currency = model["billing"]["currency"]
    errors = []
    for side, key in (("input", "input_per_1m"), ("output", "output_per_1m")):
        amount = parse_money(headline[key], f"{label}.{key}")
        cny, usd = convert(amount, currency, rate, places)
        got_cny = parse_money(model["conversion"][f"cny_{side}_per_1m"], "cny")
        got_usd = parse_money(model["conversion"][f"usd_{side}_per_1m"], "usd")
        if got_cny != cny or got_usd != usd:
            errors.append(
                f"{label}: {side} 折算应为人民币 {format(cny, 'f')}、美元 {format(usd, 'f')}，"
                f"文件里是 {format(got_cny, 'f')} / {format(got_usd, 'f')}"
            )
    return errors


def _check_dates(model: dict[str, Any], today: date, label: str) -> list[str]:
    errors = []
    verified = _parse_date(model["verified_at"], f"{label}.verified_at")
    retrieved = _parse_date(model["source"]["retrieved_at"], f"{label}.retrieved_at")
    if verified > today:
        errors.append(f"{label}: verified_at 晚于校验日 {today.isoformat()}")
    if retrieved > verified:
        errors.append(f"{label}: retrieved_at 晚于 verified_at")
    release = model.get("release")
    if release and release.get("date"):
        release_date = _parse_date(release["date"] + ("-01" if release["precision"] == "month" else ""), f"{label}.release")
        if release["precision"] == "day" and release_date > verified:
            errors.append(f"{label}: 发布日期晚于核验日")
    fx_note = model["conversion"]["fx_id"]
    return errors + ([] if fx_note else [])


def _check_history_match(root: Path, model: dict[str, Any]) -> list[str]:
    history = load_history(root, model["id"])
    label = model["id"]
    if history is None:
        return [f"{label}: 缺少 data/history/{label}.yaml"]
    schema_errors = _schema_errors(_validator(root, "history.schema.json"), _public(history), label)
    if schema_errors:
        return schema_errors
    if history["model_id"] != model["id"]:
        return [f"{label}: 历史文件的 model_id 与模型不一致"]
    observations = history["observations"]
    seen = set()
    errors = []
    previous = ""
    for index, observation in enumerate(observations):
        if observation["id"] in seen:
            errors.append(f"{label}: 历史 id 重复 {observation['id']}")
        seen.add(observation["id"])
        if observation["observed_at"] < previous:
            errors.append(f"{label}: 历史不是按 observed_at 递增")
        previous = observation["observed_at"]
        if index == 0 and observation["kind"] not in {"initial", "historical"}:
            errors.append(f"{label}: 第一条历史必须是 initial 或 historical")
    for observation in observations:
        effective = observation.get("effective_on")
        retrieved = observation.get("retrieved_at")
        if effective and effective > observation["observed_at"] and not retrieved:
            errors.append(f"{label}: effective_on 晚于 observed_at，又没有另写检索日")
        if retrieved and effective and effective > retrieved:
            errors.append(f"{label}: 生效日晚于检索日")
        if retrieved and retrieved > model["verified_at"]:
            errors.append(f"{label}: 历史检索日晚于模型核验日")
    last = observations[-1]
    current = canonical({"billing": model["billing"], "conversion": model["conversion"]})
    recorded = canonical({"billing": last["billing"], "conversion": last["conversion"]})
    if current != recorded:
        errors.append(f"{label}: 最新一条历史与当前价格不一致。改价必须追加记录，不能改旧记录")
    return errors


def _public(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not key.startswith("_")}


def validate_catalog(root: Path, today: date | None = None) -> list[str]:
    clock = today or date.today()
    errors: list[str] = []
    try:
        fx = load_fx(root)
        vendors = load_vendors(root)
        models = load_models(root)
    except Exception as exc:  # noqa: BLE001 - surface loader failures as ledger errors
        return [str(exc)]

    errors.extend(_schema_errors(_validator(root, "fx.schema.json"), _public(fx), "fx"))
    vendor_ids = [item.get("id") for item in vendors]
    if len(vendor_ids) != len(set(vendor_ids)):
        errors.append("vendors.yaml 存在重复 id")
    known = {item["id"]: item for item in vendors if "id" in item}

    model_validator = _validator(root, "model.schema.json")
    seen_ids: set[str] = set()
    present_vendors: set[str] = set()
    for model in models:
        label = model.get("_path", model.get("id", "model"))
        errors.extend(_schema_errors(model_validator, _public(model), label))
        model_id = model.get("id")
        if not model_id:
            continue
        path = Path(model["_path"])
        if path.stem != model_id:
            errors.append(f"{label}: 文件名必须等于 id")
        if model_id in seen_ids:
            errors.append(f"{label}: id 重复")
        seen_ids.add(model_id)
        if model.get("api_model_id") != model_id:
            errors.append(f"{label}: v0.1 要求 id 与 api_model_id 相同")
        vendor = model.get("vendor")
        if vendor not in known:
            errors.append(f"{label}: 未知厂商 {vendor}")
        else:
            present_vendors.add(vendor)
        if model.get("source", {}).get("url", "").startswith("http://"):
            errors.append(f"{label}: 模型标价来源必须是 https")
        try:
            _walk_money(model.get("billing"), f"{label}.billing", errors)
            _walk_money(model.get("conversion"), f"{label}.conversion", errors)
            if "billing" in model and "conversion" in model and "headline" in model["billing"]:
                errors.extend(_check_headline_matches_tier(model, label))
                errors.extend(_check_promotion(model, label))
                errors.extend(_check_conversion(model, fx, label))
        except MoneyError as exc:
            errors.append(f"{label}: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
        try:
            if "verified_at" in model and "source" in model:
                errors.extend(_check_dates(model, clock, label))
                if "rate_date" in fx and "verified_at" in model:
                    rate_date = _parse_date(fx["rate_date"], "fx.rate_date")
                    verified = _parse_date(model["verified_at"], "verified_at")
                    if rate_date > verified:
                        errors.append(f"{label}: 汇率日期晚于核验日")
        except MoneyError as exc:
            errors.append(f"{label}: {exc}")
        errors.extend(_check_history_match(root, model))

    missing = [vendor for vendor in REQUIRED_VENDORS if vendor not in present_vendors]
    if missing:
        errors.append("缺少厂商条目：" + "、".join(missing))
    if not models:
        errors.append("data/models 为空")
    return errors


def assert_valid(root: Path, today: date | None = None) -> None:
    errors = validate_catalog(root, today=today)
    if errors:
        raise LedgerError(errors)
