"""Chinese changelog and short commentary drafts."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ai_model_ledger.diff import Change

COMMENTARY_LIMIT = 280


class CommentaryError(ValueError):
    pass


def _trim_decimal(value: str) -> str:
    number = Decimal(value)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _unit(currency: str) -> str:
    return "元" if currency == "CNY" else "美元"


def _money_pair(model: dict[str, Any]) -> str:
    billing = model["billing"]
    headline = billing["headline"]
    unit = _unit(billing["currency"])
    text = (
        f"输入 {_trim_decimal(headline['input_per_1m'])} {unit}、"
        f"输出 {_trim_decimal(headline['output_per_1m'])} {unit}/百万 tokens"
    )
    cache = headline.get("cache_hit_input_per_1m")
    if cache:
        text += f"，缓存命中输入 {_trim_decimal(cache)} {unit}"
    return text


def _opinion(model: dict[str, Any]) -> str:
    billing = model["billing"]
    if billing.get("scheduled"):
        scheduled = billing["scheduled"]
        return (
            f"核验日仍执行现价，页面写明 {scheduled['effective_on']} 起输入 "
            f"{_trim_decimal(scheduled['input_per_1m'])}、输出 {_trim_decimal(scheduled['output_per_1m'])}。"
        )
    if model.get("status") == "deprecated":
        return "官方已标弃用，价目表仍保留此价，新项目不该把它当默认。"
    if len(billing.get("tiers") or []) > 1:
        return "表上这个数只是入口档，其余档位没有被折成平均数。"
    cny_output = Decimal(model["conversion"]["cny_output_per_1m"])
    if cny_output < Decimal("5"):
        return "按人民币看，输出单价已经落在日常调用区间。"
    if cny_output >= Decimal("100"):
        if billing["currency"] == "CNY":
            return "输出端按人民币标价已经是旗舰价，不是轻量档。"
        return "折成人民币后，输出端仍是旗舰价，不是尝鲜价。"
    if billing["currency"] == "USD":
        return "账单是美元。人民币数字只按中间价折算，不能拿去对账。"
    return "这是官方标价，不是渠道价，也没有把缓存命中算进输入单价。"


def draft_commentary(change: Change) -> str:
    if change.kind == "removed":
        model = change.before or {}
        text = (
            f"{model.get('display_name_zh', change.model_id)} 已从本账本移除。"
            "移除不等于厂商下线，除非该条备注写了官方退役说明。"
        )
    elif change.kind == "price_changed":
        text = _price_change_text(change)
    elif change.kind == "metadata_changed":
        model = change.after or {}
        text = (
            f"{model['display_name_zh']}（{change.model_id}）的上下文或状态有变动，标价未改。"
            "仍只引用官方页。"
        )
    else:
        model = change.after or {}
        text = (
            f"{model['display_name_zh']}（{change.model_id}）建档：{_money_pair(model)}。"
            f"口径：{model['billing']['headline']['label_zh']}。"
            f"{_opinion(model)}"
        )
    text = _fit(text)
    if len(text) > COMMENTARY_LIMIT:
        raise CommentaryError(f"{change.model_id} 的短评仍超过 {COMMENTARY_LIMIT} 字")
    return text


def _price_change_text(change: Change) -> str:
    old = change.before or {}
    new = change.after or {}
    old_h = old["billing"]["headline"]
    new_h = new["billing"]["headline"]
    unit = _unit(new["billing"]["currency"])
    old_in = Decimal(old_h["input_per_1m"])
    new_in = Decimal(new_h["input_per_1m"])
    old_out = Decimal(old_h["output_per_1m"])
    new_out = Decimal(new_h["output_per_1m"])
    if new_in < old_in and new_out <= old_out or new_out < old_out and new_in <= old_in:
        verb = "下调"
    elif new_in > old_in and new_out >= old_out or new_out > old_out and new_in >= old_in:
        verb = "上调"
    else:
        verb = "调整"
    return (
        f"{new['display_name_zh']}（{change.model_id}）相对上一份快照{verb}："
        f"输入 {_trim_decimal(old_h['input_per_1m'])}→{_trim_decimal(new_h['input_per_1m'])} {unit}，"
        f"输出 {_trim_decimal(old_h['output_per_1m'])}→{_trim_decimal(new_h['output_per_1m'])} {unit}"
        f"/百万 tokens（{new_h['label_zh']}）。只比较官方标价。"
    )


def _fit(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= COMMENTARY_LIMIT:
        return text
    parts = [part for part in text.split("。") if part]
    while len(parts) > 1 and len("。".join(parts) + "。") > COMMENTARY_LIMIT:
        parts.pop()
    fitted = "。".join(parts) + "。"
    return fitted


STATUS_ZH = {
    "active": "在售",
    "deprecated": "已弃用",
    "retiring": "即将下线",
    "preview": "预览",
}


def render_changelog(
    *,
    snapshot_date: str,
    baseline_label: str,
    fx: dict[str, Any],
    changes: list[Change],
    vendors: list[dict[str, Any]] | None = None,
    histories: dict[str, dict[str, Any]] | None = None,
) -> str:
    added = [change for change in changes if change.kind == "added"]
    priced = [change for change in changes if change.kind == "price_changed"]
    meta = [change for change in changes if change.kind == "metadata_changed"]
    removed = [change for change in changes if change.kind == "removed"]
    lines = [
        f"# {snapshot_date} 变动说明",
        "",
        f"对照基准：{baseline_label}",
        (
            f"折算汇率：1 美元 = {fx['rate']} 人民币"
            f"（{fx['rate_date']} 银行间外汇市场人民币汇率中间价）。"
            "折算额不是账单金额。"
        ),
        f"本页变动：新增 {len(added)}，价格变化 {len(priced)}，上下文或状态变化 {len(meta)}，移除 {len(removed)}。",
        "",
        "价格均抄自各条来源页，不使用渠道转载。分档模型只在这里列出入口档，全部分档在模型文件里。",
        "",
        "## 首次建档",
        "",
    ]
    names = {item["id"]: item["name_zh"] for item in (vendors or [])}
    lines.extend(_section_or_empty(added, lambda change: _added_block(change, names)))
    lines.extend(["## 价格变化", ""])
    lines.extend(_section_or_empty(priced, _price_block))
    lines.extend(["## 上下文或状态", ""])
    lines.extend(_section_or_empty(meta, _meta_block))
    lines.extend(["## 移除", ""])
    lines.extend(_section_or_empty(removed, _removed_block))
    lines.extend(["## 建档时已核到的更早官方价格", ""])
    prior = _prior_price_blocks(histories or {})
    lines.extend(prior or ["无。没有从官方旧公告里核到、且能与现行单价分开的更早标价。", ""])
    return "\n".join(lines).rstrip() + "\n"


def _prior_price_blocks(histories: dict[str, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for model_id in sorted(histories):
        observations = histories[model_id].get("observations") or []
        earlier = observations[:-1]
        if not earlier:
            continue
        lines.append(f"### `{model_id}`")
        lines.append("")
        for row in earlier:
            headline = row["billing"]["headline"]
            unit = _unit(row["billing"]["currency"])
            when = row.get("effective_on") or row["observed_at"]
            lines.append(
                f"- {when}：输入 {_trim_decimal(headline['input_per_1m'])} {unit}、"
                f"输出 {_trim_decimal(headline['output_per_1m'])} {unit}/百万 tokens"
                f"（{headline['label_zh']}）。"
            )
            lines.append(f"  来源：{row['source_url']}")
            lines.append(f"  说明：{row['note_zh']}")
        lines.append("")
    return lines


def _section_or_empty(changes: list[Change], render) -> list[str]:
    if not changes:
        return ["无。", ""]
    lines: list[str] = []
    for change in changes:
        lines.extend(render(change))
    return lines


def _added_block(change: Change, names: dict[str, str]) -> list[str]:
    model = change.after or {}
    headline = model["billing"]["headline"]
    context = model["context"].get("window_label") or model["context"].get("window_tokens")
    vendor = names.get(model["vendor"], model["vendor"])
    status = STATUS_ZH.get(model["status"], model["status"])
    return [
        f"### {model['display_name_zh']}（`{model['id']}`）",
        "",
        f"- 厂商：{vendor}",
        f"- 部署：{model['deployment_zh']}",
        f"- 入口价（{headline['label_zh']}）：{_money_pair(model)}",
        f"- 上下文：{context}",
        f"- 状态：{status}",
        f"- 来源：{model['source']['url']}",
        f"- 核验：{model['verified_at']}",
        "",
    ]


def _price_block(change: Change) -> list[str]:
    old = change.before or {}
    new = change.after or {}
    return [
        f"### {new['display_name_zh']}（`{new['id']}`）",
        "",
        f"- 旧入口价：{_money_pair(old)}",
        f"- 新入口价：{_money_pair(new)}",
        f"- 来源：{new['source']['url']}",
        f"- 核验：{new['verified_at']}",
        "",
    ]


def _meta_block(change: Change) -> list[str]:
    new = change.after or {}
    return [
        f"### {new['display_name_zh']}（`{new['id']}`）",
        "",
        "- 标价未变。上下文、发布信息或状态与上一份快照不同，详见该模型文件。",
        "",
    ]


def _removed_block(change: Change) -> list[str]:
    old = change.before or {}
    return [
        f"### {old.get('display_name_zh', change.model_id)}（`{change.model_id}`）",
        "",
        "- 当前目录已无此文件。历史记录仍保留。",
        "",
    ]


def render_commentary(snapshot_date: str, changes: list[Change]) -> str:
    lines = [
        f"# {snapshot_date} 短评草稿",
        "",
        "每条不超过 280 个字符（按 Unicode 码位计）。只使用本账本已核验的价格和档位，不引用跑分，也不把折算额说成账单。",
        "中日韩字符在 X 上通常按 2 计，草稿尽量短于 140 字，以便直接发出；硬上限仍是 280。",
        "",
    ]
    if not changes:
        lines.extend(["本对照没有变动。", ""])
        return "\n".join(lines)
    for change in changes:
        text = draft_commentary(change)
        lines.extend(
            [
                f"## {change.model_id}",
                "",
                text,
                "",
                f"字符数：{len(text)}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
