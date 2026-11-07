"""Command line for validation, diffs, changelog, and the static site."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ai_model_ledger.history import extension_errors
from ai_model_ledger.load import find_root, load_history
from ai_model_ledger.publish import (
    PublishError,
    build_site,
    check_published,
    sync_snapshot_and_changelog,
    write_missing_histories,
)
from ai_model_ledger.validate import validate_catalog


def _root(value: str | None) -> Path:
    return Path(value).resolve() if value else find_root()


def _print_errors(errors: list[str]) -> int:
    for error in errors:
        print(error, file=sys.stderr)
    print(f"共 {len(errors)} 个问题", file=sys.stderr)
    return 1


def command_validate(args: argparse.Namespace) -> int:
    errors = validate_catalog(_root(args.root))
    if errors:
        return _print_errors(errors)
    print("校验通过")
    return 0


def command_sync(args: argparse.Namespace) -> int:
    root = _root(args.root)
    created = write_missing_histories(root)
    for path in created:
        print(f"写入历史 {path.relative_to(root)}")
    errors = validate_catalog(root)
    if errors:
        return _print_errors(errors)
    try:
        result = sync_snapshot_and_changelog(root)
    except PublishError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"快照 {result['snapshot'].relative_to(root)}")
    print(f"变动说明 {result['changelog'].relative_to(root)}（{result['changes']} 条）")
    print(f"短评 {result['commentary'].relative_to(root)}")
    return 0


def command_check(args: argparse.Namespace) -> int:
    root = _root(args.root)
    errors = validate_catalog(root)
    errors.extend(check_published(root))
    if errors:
        return _print_errors(errors)
    print("校验通过，快照与变动说明已对齐")
    return 0


def command_build(args: argparse.Namespace) -> int:
    root = _root(args.root)
    errors = validate_catalog(root)
    if errors:
        return _print_errors(errors)
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    build_site(root, out)
    print(f"站点已生成：{out}")
    return 0


def command_check_history(args: argparse.Namespace) -> int:
    root = _root(args.root)
    errors = _git_history_errors(root, args.against)
    if errors:
        return _print_errors(errors)
    print(f"相对 {args.against}，历史文件只增不改")
    return 0


def _git_history_errors(root: Path, ref: str) -> list[str]:
    current_dir = root / "data" / "history"
    errors = []
    if not current_dir.is_dir():
        return ["缺少 data/history/"]
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "data/history"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if listed.returncode != 0:
        return [f"无法读取 {ref} 的历史文件：{listed.stderr.strip()}"]
    for relative in [line for line in listed.stdout.splitlines() if line.endswith(".yaml")]:
        show = subprocess.run(
            ["git", "show", f"{ref}:{relative}"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if show.returncode != 0:
            errors.append(f"无法读取 {ref}:{relative}")
            continue
        previous = load_yaml_text(show.stdout, relative)
        path = root / relative
        if not path.is_file():
            errors.append(f"{relative} 在 {ref} 中存在，当前被删除")
            continue
        current = load_history(root, path.stem)
        errors.extend(f"{relative}: {item}" for item in extension_errors(previous, current or {}))
    return errors


def load_yaml_text(text: str, label: str):
    from io import StringIO

    import yaml

    data = yaml.safe_load(StringIO(text))
    if not isinstance(data, dict):
        raise ValueError(f"{label} 不是映射")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-model-ledger", description="大模型 API 价格账本")
    parser.add_argument("--root", help="账本根目录，默认自动查找")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="校验模型、汇率、折算和历史")
    validate.set_defaults(func=command_validate)

    sync = sub.add_parser("sync", help="补齐缺失的初始历史，并写入快照与中文变动说明")
    sync.set_defaults(func=command_sync)

    check = sub.add_parser("check", help="校验数据，并确认快照与变动说明未被手改后失真")
    check.set_defaults(func=command_check)

    build = sub.add_parser("build", help="生成静态站点")
    build.add_argument("--out", default="site", help="输出目录，默认 site/")
    build.set_defaults(func=command_build)

    history = sub.add_parser("check-history", help="确认相对某个 git 引用，历史只追加")
    history.add_argument("--against", required=True, help="基线引用，例如 origin/main")
    history.set_defaults(func=command_check_history)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
