"""Write the immutable snapshot, changelog, and static site."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ai_model_ledger.changelog import render_changelog, render_commentary
from ai_model_ledger.diff import (
    build_snapshot,
    diff_catalogs,
    dump_snapshot,
    previous_snapshot,
    public,
    read_snapshot,
    snapshot_paths,
)
from ai_model_ledger.history import render_history
from ai_model_ledger.load import iter_model_paths, load_history, load_models


class PublishError(RuntimeError):
    pass


def write_missing_histories(root: Path) -> list[Path]:
    written = []
    history_dir = root / "data" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    for model in load_models(root):
        path = history_dir / f"{model['id']}.yaml"
        if path.exists():
            continue
        path.write_text(render_history(model), encoding="utf-8")
        written.append(path)
    return written


def load_histories(root: Path) -> dict[str, dict[str, Any]]:
    histories = {}
    for path in iter_model_paths(root):
        history = load_history(root, path.stem)
        if history:
            histories[path.stem] = public(history)
    return histories


def sync_snapshot_and_changelog(root: Path) -> dict[str, Any]:
    document = build_snapshot(root)
    day = document["snapshot_date"]
    snapshot_dir = root / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = snapshot_dir / f"{day}.json"
    payload = dump_snapshot(document)
    if snapshot_file.exists():
        existing = snapshot_file.read_text(encoding="utf-8")
        if existing != payload:
            raise PublishError(
                f"{snapshot_file.name} 已存在且内容不同。快照不可覆盖，请使用新的核验日期另存"
            )
    else:
        snapshot_file.write_text(payload, encoding="utf-8")

    previous = previous_snapshot(root, day)
    baseline_models = previous["models"] if previous else None
    baseline_label = (
        f"快照 {previous['snapshot_date']}" if previous else "无（首次建档，对照空台账）"
    )
    changes = diff_catalogs(baseline_models, document["models"])
    changelog_dir = root / "changelog"
    changelog_dir.mkdir(parents=True, exist_ok=True)
    changelog_path = changelog_dir / f"{day}.md"
    commentary_path = changelog_dir / f"{day}.commentary.md"
    changelog_path.write_text(
        render_changelog(
            snapshot_date=day,
            baseline_label=baseline_label,
            fx=document["fx"],
            changes=changes,
            vendors=document["vendors"],
            histories=load_histories(root),
        ),
        encoding="utf-8",
    )
    commentary_path.write_text(render_commentary(day, changes), encoding="utf-8")
    return {
        "snapshot": snapshot_file,
        "changelog": changelog_path,
        "commentary": commentary_path,
        "changes": len(changes),
    }


def check_published(root: Path) -> list[str]:
    """Fail when committed snapshot or changelog drift from current data."""
    errors: list[str] = []
    document = build_snapshot(root)
    day = document["snapshot_date"]
    payload = dump_snapshot(document)
    snapshot_file = root / "snapshots" / f"{day}.json"
    if not snapshot_file.is_file():
        errors.append(f"缺少快照 snapshots/{day}.json")
    elif snapshot_file.read_text(encoding="utf-8") != payload:
        errors.append(f"快照 snapshots/{day}.json 与当前数据不一致，且不允许改写旧快照")
    for path in snapshot_paths(root):
        if path.stem > day:
            errors.append(f"快照 {path.name} 的日期晚于当前核验日 {day}")
    previous = previous_snapshot(root, day)
    baseline_models = previous["models"] if previous else None
    baseline_label = (
        f"快照 {previous['snapshot_date']}" if previous else "无（首次建档，对照空台账）"
    )
    changes = diff_catalogs(baseline_models, document["models"])
    expected_changelog = render_changelog(
        snapshot_date=day,
        baseline_label=baseline_label,
        fx=document["fx"],
        changes=changes,
        vendors=document["vendors"],
        histories=load_histories(root),
    )
    expected_commentary = render_commentary(day, changes)
    changelog_path = root / "changelog" / f"{day}.md"
    commentary_path = root / "changelog" / f"{day}.commentary.md"
    if not changelog_path.is_file() or changelog_path.read_text(encoding="utf-8") != expected_changelog:
        errors.append(f"changelog/{day}.md 不是由当前数据与上一份快照生成的")
    if not commentary_path.is_file() or commentary_path.read_text(encoding="utf-8") != expected_commentary:
        errors.append(f"changelog/{day}.commentary.md 不是由当前变动生成的")
    return errors


def _markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    body: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            close_list()
            continue
        if line.startswith("### "):
            close_list()
            body.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            close_list()
            body.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            close_list()
            body.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(line[2:])}</li>")
        else:
            close_list()
            body.append(f"<p>{_inline(line)}</p>")
    close_list()
    return "\n".join(body)


def _inline(text: str) -> str:
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    result = []
    index = 0
    while index < len(escaped):
        if escaped.startswith("`", index):
            end = escaped.find("`", index + 1)
            if end != -1:
                result.append("<code>" + escaped[index + 1 : end] + "</code>")
                index = end + 1
                continue
        if escaped.startswith("[", index):
            close = escaped.find("]", index)
            if close != -1 and escaped[close : close + 2] == "](":
                url_end = escaped.find(")", close)
                if url_end != -1:
                    label = escaped[index + 1 : close]
                    url = escaped[close + 2 : url_end]
                    result.append(f'<a href="{url}">{label}</a>')
                    index = url_end + 1
                    continue
        result.append(escaped[index])
        index += 1
    return "".join(result)


def build_site(root: Path, out: Path) -> Path:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(root / "web", out)
    document = build_snapshot(root)
    day = document["snapshot_date"]
    models = []
    for model in document["models"]:
        history = load_history(root, model["id"])
        item = dict(model)
        item["history"] = public(history)["observations"] if history else []
        models.append(item)
    payload = {
        "ledger": "ai-model-ledger",
        "schema_version": 1,
        "snapshot_date": day,
        "fx": document["fx"],
        "vendors": document["vendors"],
        "models": models,
    }
    (out / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    methodology = (root / "docs" / "methodology.md").read_text(encoding="utf-8")
    page = (root / "web" / "page.html").read_text(encoding="utf-8")
    (out / "methodology.html").write_text(
        page.replace("{{title}}", "口径说明").replace("{{body}}", _markdown_to_html(methodology)),
        encoding="utf-8",
    )
    omitted = (root / "docs" / "omitted.md").read_text(encoding="utf-8")
    (out / "omitted.html").write_text(
        page.replace("{{title}}", "未收录与未采信").replace("{{body}}", _markdown_to_html(omitted)),
        encoding="utf-8",
    )
    (out / ".nojekyll").write_text("", encoding="utf-8")
    template = out / "page.html"
    if template.exists():
        template.unlink()
    return out


def load_committed_snapshot(path: Path) -> dict[str, Any]:
    return read_snapshot(path)
