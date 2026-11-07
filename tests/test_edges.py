"""Edge cases for the validator, history, and snapshot immutability."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from ai_model_ledger.changelog import render_changelog
from ai_model_ledger.load import find_root, load_history
from ai_model_ledger.publish import PublishError, sync_snapshot_and_changelog, write_missing_histories
from ai_model_ledger.validate import validate_catalog

REAL = find_root(Path(__file__))
VENDORS = (
    ("deepseek", "cn"),
    ("qwen", "cn"),
    ("moonshot", "cn"),
    ("zhipu", "cn"),
    ("openai", "global"),
    ("anthropic", "global"),
    ("google", "global"),
    ("xai", "global"),
)


def _fx_copy(root: Path) -> None:
    target = root / "data" / "fx"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(REAL / "data" / "fx" / "usd-cny.yaml", target / "usd-cny.yaml")


def _vendors(root: Path) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    payload = [
        {"id": vendor, "name_zh": vendor, "name_en": vendor, "home_region": region, "order": index}
        for index, (vendor, region) in enumerate(VENDORS)
    ]
    (root / "data" / "vendors.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _model(vendor: str, region: str, model_id: str) -> dict:
    return {
        "schema_version": 1,
        "id": model_id,
        "vendor": vendor,
        "api_model_id": model_id,
        "display_name_zh": f"测试 {model_id}",
        "region": region,
        "status": "active",
        "deployment_zh": "测试部署，不是厂商环境",
        "modalities": {"input": ["text"], "output": ["text"]},
        "context": {
            "window_label": "1M",
            "source_url": "https://example.com/pricing",
            "note_zh": "夹具里的上下文。",
        },
        "billing": {
            "unit": "per_1m_tokens",
            "currency": "CNY",
            "price_covers_zh": "夹具标准价，不能当成厂商报价。",
            "headline": {
                "id": "std",
                "label_zh": "标准价",
                "input_per_1m": "1",
                "output_per_1m": "2",
            },
        },
        "conversion": {
            "fx_id": "usd-cny-2026-11-06",
            "cny_input_per_1m": "1",
            "cny_output_per_1m": "2",
            "usd_input_per_1m": "0.148880",
            "usd_output_per_1m": "0.297761",
        },
        "source": {
            "url": "https://example.com/pricing",
            "title_zh": "测试定价页",
            "section_zh": "测试表的标准价那一行，只给校验器用。",
            "retrieved_at": "2026-11-07",
        },
        "verified_at": "2026-11-07",
        "notes_zh": "这是测试夹具，不代表任何厂商的真实价格。",
    }


def _write_model(root: Path, model: dict) -> Path:
    directory = root / "data" / "models"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{model['id']}.yaml"
    path.write_text(yaml.safe_dump(model, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def make_ledger(tmp_path: Path) -> Path:
    root = tmp_path / "ledger"
    shutil.copytree(REAL / "schema", root / "schema")
    _fx_copy(root)
    _vendors(root)
    for vendor, region in VENDORS:
        _write_model(root, _model(vendor, region, f"{vendor}-std"))
    write_missing_histories(root)
    errors = validate_catalog(root, today=date(2026, 11, 7))
    assert errors == [], errors
    return root


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _save(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_fixture_ledger_is_valid(tmp_path: Path):
    assert validate_catalog(make_ledger(tmp_path), today=date(2026, 11, 7)) == []


def test_rejects_wrong_fx_math(tmp_path: Path):
    root = make_ledger(tmp_path)
    path = root / "data" / "models" / "deepseek-std.yaml"
    model = _load(path)
    model["conversion"]["cny_output_per_1m"] = "9"
    _save(path, model)
    errors = validate_catalog(root, today=date(2026, 11, 7))
    assert any("折算" in error for error in errors)


def test_rejects_http_price_source_and_missing_section(tmp_path: Path):
    root = make_ledger(tmp_path)
    path = root / "data" / "models" / "qwen-std.yaml"
    model = _load(path)
    model["source"]["url"] = "http://example.com/pricing"
    del model["source"]["section_zh"]
    _save(path, model)
    errors = "\n".join(validate_catalog(root, today=date(2026, 11, 7)))
    assert "https" in errors
    assert "section_zh" in errors


def test_rejects_future_verification_and_too_many_decimals(tmp_path: Path):
    root = make_ledger(tmp_path)
    path = root / "data" / "models" / "openai-std.yaml"
    model = _load(path)
    model["verified_at"] = "2099-01-01"
    model["source"]["retrieved_at"] = "2099-01-01"
    model["billing"]["headline"]["input_per_1m"] = "1.1234567"
    _save(path, model)
    errors = "\n".join(validate_catalog(root, today=date(2026, 11, 7)))
    assert "晚于校验日" in errors
    assert "6 位小数" in errors


def test_rejects_headline_that_disagrees_with_its_tier(tmp_path: Path):
    root = make_ledger(tmp_path)
    path = root / "data" / "models" / "zhipu-std.yaml"
    model = _load(path)
    model["billing"]["tiers"] = [
        {
            "id": "std",
            "label_zh": "标准价",
            "input_per_1m": "9",
            "output_per_1m": "2",
            "is_headline": True,
        }
    ]
    _save(path, model)
    errors = "\n".join(validate_catalog(root, today=date(2026, 11, 7)))
    assert "headline.input_per_1m" in errors


def test_rejects_promotion_that_does_not_multiply(tmp_path: Path):
    root = make_ledger(tmp_path)
    path = root / "data" / "models" / "moonshot-std.yaml"
    model = _load(path)
    model["billing"]["promotion"] = {
        "label_zh": "测试折扣",
        "discount_rate": "0.5",
        "ends_on": None,
        "note_zh": "夹具里的折扣，数字故意对不上。",
    }
    model["billing"]["tiers"] = [
        {
            "id": "std",
            "label_zh": "标准价",
            "input_per_1m": "1",
            "output_per_1m": "2",
            "list_input_per_1m": "1",
            "list_output_per_1m": "2",
            "is_headline": True,
        }
    ]
    _save(path, model)
    errors = "\n".join(validate_catalog(root, today=date(2026, 11, 7)))
    assert "折后价" in errors


def test_snapshot_refuses_to_overwrite_a_different_file(tmp_path: Path):
    root = make_ledger(tmp_path)
    sync_snapshot_and_changelog(root)
    path = root / "data" / "models" / "google-std.yaml"
    model = _load(path)
    model["notes_zh"] = model["notes_zh"] + "多写了一句，快照仍不许改。"
    _save(path, model)
    with pytest.raises(PublishError, match="不可覆盖"):
        sync_snapshot_and_changelog(root)


def test_openai_standard_ladder_includes_live_mid_tiers():
    from ai_model_ledger.load import load_models

    models = [model for model in load_models(REAL) if model["vendor"] == "openai"]
    ids = {model["id"] for model in models}
    required = {
        "gpt-6-astra",
        "gpt-6.1-sol",
        "gpt-6.1-terra",
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    }
    assert required <= ids
    by_id = {model["id"]: model for model in models}
    assert by_id["gpt-5"]["status"] == "deprecated"
    assert by_id["gpt-4.1"]["status"] == "deprecated"
    living = [model for model in models if model["status"] == "active"]
    retired = [model for model in models if model["status"] == "deprecated"]
    assert len(living) > len(retired)
    # 6.1 Sol is the current mid flagship: cheaper than Astra, cache hit is 5% not the older Sol's 10%.
    assert by_id["gpt-6.1-sol"]["billing"]["headline"]["input_per_1m"] == "2"
    assert by_id["gpt-6.1-sol"]["billing"]["headline"]["cache_hit_input_per_1m"] == "0.10"
    assert by_id["gpt-6-sol"]["billing"]["headline"]["cache_hit_input_per_1m"] == "0.20"
    assert "2026-11-30" in by_id["gpt-5.6-sol"]["notes_zh"]
    assert "scheduled" not in by_id["gpt-5.6-sol"]["billing"]


def test_real_catalog_has_price_spread_cache_and_cited_sections():
    from ai_model_ledger.load import load_models

    models = load_models(REAL)
    by_vendor: dict[str, list] = {}
    no_cache = {
        "qwen3.8-max",
        "qwen3.7-plus",
        "qwen-plus-2025-12-01",
        "qwen-flash-2025-07-28",
    }
    for model in models:
        assert "表" in model["source"]["section_zh"]
        by_vendor.setdefault(model["vendor"], []).append(Decimal_output(model))
        if model["id"] not in no_cache:
            assert model["billing"]["headline"].get("cache_hit_input_per_1m"), model["id"]
    for vendor, prices in by_vendor.items():
        if vendor == "deepseek":
            assert prices == [Decimal_output(next(m for m in models if m["id"] == "deepseek-flash"))]
            continue
        assert min(prices) < max(prices), vendor
    history = load_history(REAL, "qwen-max")
    first, last = history["observations"]
    assert first["billing"]["headline"]["input_per_1m"] == "20"
    assert first["billing"]["headline"]["output_per_1m"] == "60"
    assert "0.02 元/千" in first["note_zh"]
    assert last["billing"]["headline"]["input_per_1m"] == "2.4"
    assert first["source_url"].startswith("https://help.aliyun.com/")
    text = render_changelog(
        snapshot_date="2026-11-07",
        baseline_label="无",
        fx={"rate": "6.7168", "rate_date": "2026-11-06"},
        changes=[],
        histories={"qwen-max": history},
    )
    assert "qwen-max" in text
    assert "20" in text


def Decimal_output(model: dict):
    from decimal import Decimal

    return Decimal(model["conversion"]["cny_output_per_1m"])
