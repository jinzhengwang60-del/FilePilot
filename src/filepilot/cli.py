from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .demo import create_demo
from .planner import classification_plan
from .safety import SafetyError
from .scanner import scan_folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FilePilot 本地文件扫描与只读整理预览")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("scan", "plan"):
        subparser = commands.add_parser(command, help="只读扫描" if command == "scan" else "只读分类预览")
        subparser.add_argument("folder", type=Path)
        subparser.add_argument("--no-recursive", action="store_true")
        subparser.add_argument("--include-hidden", action="store_true")
        subparser.add_argument("--json", action="store_true", help="将结果输出为 JSON；不会自动保存或上传")
        if command == "plan":
            subparser.add_argument("--target", type=Path, help="默认使用扫描目录中的 FilePilot_整理")
    demo = commands.add_parser("demo", help="在新目录创建程序生成的演示文件")
    demo.add_argument("--output", type=Path, default=Path("demo-files"))
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if args.command == "demo":
            print(f"演示文件夹：{create_demo(args.output)}")
            return 0
        result = scan_folder(args.folder, recursive=not args.no_recursive, include_hidden=args.include_hidden)
        if args.command == "plan":
            plan = classification_plan(result, {file.path for file in result.files}, args.target or result.root / "FilePilot_整理")
            payload = {"read_only": True, "root": str(plan.root), "kind": plan.kind,
                       "moves": [{"source": str(item.file.path), "destination": str(item.destination), "reason": item.reason} for item in plan.items]}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("只读预览，未移动文件：")
                for item in plan.items:
                    print(f"{item.file.relative} → {item.destination}")
        else:
            payload = {"read_only": True, "root": str(result.root), "file_count": len(result.files),
                       "total_bytes": result.total_bytes, "extra_bytes": result.extra_bytes, "hashed_count": result.hashed_count,
                       "files": [{"relative": file.relative, "size": file.size, "category": file.category, "sha256": file.digest} for file in result.files],
                       "duplicates": [{"sha256": group.digest, "files": [file.relative for file in group.files]} for group in result.duplicates],
                       "issues": [{"path": str(issue.path), "reason": issue.reason} for issue in result.issues]}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"只读扫描：{len(result.files)} 个文件，{len(result.duplicates)} 组重复，{len(result.issues)} 项跳过。")
                for group in result.duplicates:
                    print("内容相同：" + " / ".join(file.relative for file in group.files))
        return 0
    except (OSError, SafetyError) as exc:
        print(f"无法处理：{exc}", file=sys.stderr)
        return 2
