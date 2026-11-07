"""Decimal money and the stated USD/CNY central-parity conversion."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

MONEY_PATTERN_KEYS = (
    "_per_1m",
)
RATE_KEYS = frozenset({"rate", "discount_rate"})


class MoneyError(ValueError):
    pass


def parse_money(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str):
        raise MoneyError(f"{field} 必须写成带引号的十进制字符串，不能是 YAML 数字")
    try:
        number = Decimal(value)
    except Exception as exc:  # noqa: BLE001 - Decimal raises several types
        raise MoneyError(f"{field} 不是十进制数字：{value}") from exc
    if number.is_nan() or number.is_infinite() or number < 0:
        raise MoneyError(f"{field} 不能为负或非有限数")
    exponent = number.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -6:
        raise MoneyError(f"{field} 最多保留 6 位小数")
    return number


def quantize(value: Decimal, places: int = 6) -> Decimal:
    quantum = Decimal(10) ** -places
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def format_money(value: Decimal, places: int = 6) -> str:
    """Fixed-point string with exactly `places` digits, no exponent."""
    return format(quantize(value, places), "f")


def convert(amount: Decimal, currency: str, rate: Decimal, places: int = 6) -> tuple[Decimal, Decimal]:
    """Return (cny, usd) for an amount denominated in currency."""
    if currency == "CNY":
        cny = quantize(amount, places)
        usd = quantize(amount / rate, places)
    elif currency == "USD":
        usd = quantize(amount, places)
        cny = quantize(amount * rate, places)
    else:
        raise MoneyError(f"不支持的账单币种：{currency}")
    return cny, usd


def is_money_key(key: str) -> bool:
    return key in RATE_KEYS or key.endswith("_per_1m")
