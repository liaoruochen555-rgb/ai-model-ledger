from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ai_model_ledger.changelog import COMMENTARY_LIMIT, draft_commentary
from ai_model_ledger.diff import Change, diff_catalogs
from ai_model_ledger.history import extension_errors
from ai_model_ledger.load import find_root, load_models
from ai_model_ledger.money import MoneyError, convert, parse_money
from ai_model_ledger.publish import build_site, check_published
from ai_model_ledger.validate import price_fingerprint, validate_catalog

ROOT = find_root(Path(__file__))
RATE = Decimal("6.7168")


def test_fx_rounding_matches_documented_examples():
    cny, usd = convert(Decimal("1"), "CNY", RATE)
    assert usd == Decimal("0.148880")
    assert cny == Decimal("1.000000")
    cny, usd = convert(Decimal("10"), "USD", RATE)
    assert cny == Decimal("67.168000")
    assert usd == Decimal("10.000000")


def test_money_rejects_bare_yaml_numbers():
    with pytest.raises(MoneyError):
        parse_money(1.5, "input_per_1m")
    with pytest.raises(MoneyError):
        parse_money("-1", "input_per_1m")


def test_real_catalog_validates_and_matches_published_files():
    errors = validate_catalog(ROOT, today=date(2026, 11, 7))
    assert errors == []
    assert check_published(ROOT) == []
    models = load_models(ROOT)
    vendors = {model["vendor"] for model in models}
    assert vendors == {
        "deepseek",
        "qwen",
        "moonshot",
        "zhipu",
        "openai",
        "anthropic",
        "google",
        "xai",
    }
    assert all(model["source"]["url"].startswith("https://") for model in models)
    assert all(model["verified_at"] == "2026-11-07" for model in models)


def test_commentary_drafts_stay_within_limit_and_name_the_model():
    from ai_model_ledger.diff import build_snapshot, diff_catalogs as diff

    document = build_snapshot(ROOT)
    changes = diff(None, document["models"])
    assert len(changes) == len(document["models"])
    for change in changes:
        text = draft_commentary(change)
        assert len(text) <= COMMENTARY_LIMIT
        assert change.model_id in text
        assert "http" not in text
        assert "据说" not in text


def test_price_drop_is_described_as_a_drop():
    before = {
        "id": "example-model",
        "display_name_zh": "示例模型",
        "billing": {"currency": "CNY", "headline": {"label_zh": "标准价", "input_per_1m": "2", "output_per_1m": "8"}},
        "conversion": {"cny_output_per_1m": "8"},
        "status": "active",
    }
    after = {
        "id": "example-model",
        "display_name_zh": "示例模型",
        "billing": {"currency": "CNY", "headline": {"label_zh": "标准价", "input_per_1m": "1", "output_per_1m": "4"}},
        "conversion": {"cny_output_per_1m": "4"},
        "status": "active",
    }
    change = Change("price_changed", "example-model", before, after)
    text = draft_commentary(change)
    assert "下调" in text
    assert len(text) <= COMMENTARY_LIMIT
    assert diff_catalogs([before], [after])[0].kind == "price_changed"
    assert price_fingerprint(before) != price_fingerprint(after)


def test_history_rejects_rewrites_and_allows_appends():
    previous = {
        "model_id": "example-model",
        "observations": [{"id": "a", "observed_at": "2026-11-07", "input_per_1m": "1"}],
    }
    edited = {
        "model_id": "example-model",
        "observations": [{"id": "a", "observed_at": "2026-11-07", "input_per_1m": "2"}],
    }
    appended = {
        "model_id": "example-model",
        "observations": [
            {"id": "a", "observed_at": "2026-11-07", "input_per_1m": "1.0"},
            {"id": "b", "observed_at": "2026-11-08", "input_per_1m": "2"},
        ],
    }
    assert extension_errors(previous, edited)
    assert extension_errors(previous, appended) == []
    shortened = {"model_id": "example-model", "observations": []}
    assert extension_errors(previous, shortened)


def test_unchanged_catalog_produces_no_diff():
    models = load_models(ROOT)
    assert diff_catalogs(models, models) == []


def test_site_build_contains_every_model(tmp_path: Path):
    out = tmp_path / "site"
    build_site(ROOT, out)
    data = (out / "data.json").read_text(encoding="utf-8")
    assert "deepseek-flash" in data
    assert "6.7168" in data
    assert (out / "index.html").is_file()
    assert (out / "methodology.html").is_file()
    assert (out / "omitted.html").is_file()
    assert "汇率中间价" in (out / "methodology.html").read_text(encoding="utf-8")
    assert not (out / "page.html").exists()
