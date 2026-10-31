#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一条命令改插件版本号。

AstrBot 插件市场对同一个插件的版本号是永久占用的：提交过（哪怕后来撤回、
删除、审核没过）的版本号都不能再用，撞号时发布页会报
「该版本号已经使用过；即使版本已删除或撤回，也不能重复使用」。

用法：
    python bump_version.py              # 自动把补丁位 +1，例如 1.3.0 -> 1.3.1
    python bump_version.py 1.4.0        # 指定版本号
    python bump_version.py 1.4.0 -n "本版修了什么"   # 顺带写一条 CHANGELOG
    python bump_version.py --show       # 只看当前版本号

改的文件：metadata.yaml、README.md、CHANGELOG.md。
脚本只用标准库，放在插件仓库根目录跑。
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
METADATA = ROOT / "metadata.yaml"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"

VERSION_RE = re.compile(r'^version:\s*"([^"]+)"\s*$', re.M)


def read_version() -> str:
    if not METADATA.exists():
        sys.exit(f"找不到 {METADATA.name}，请在插件仓库根目录运行。")
    text = METADATA.read_text(encoding="utf-8")
    m = VERSION_RE.search(text)
    if not m:
        sys.exit('metadata.yaml 里没有找到 version: "x.y.z" 这一行。')
    return m.group(1)


def bump_patch(version: str) -> str:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if not m:
        sys.exit(f"当前版本号 {version!r} 不是 x.y.z 形式，请手动指定新版本号。")
    major, minor, patch = (int(x) for x in m.groups())
    return f"{major}.{minor}.{patch + 1}"


def write_metadata(version: str) -> None:
    text = METADATA.read_text(encoding="utf-8")
    new = VERSION_RE.sub(f'version: "{version}"', text, count=1)
    if new == text:
        sys.exit("metadata.yaml 的 version 没被改到，检查一下格式。")
    METADATA.write_text(new, encoding="utf-8", newline="\n")


def write_readme(version: str) -> bool:
    if not README.exists():
        return False
    text = README.read_text(encoding="utf-8")
    new = re.sub(r"版本\s*`\d+\.\d+\.\d+`", f"版本 `{version}`", text, count=1)
    if new == text:
        return False
    README.write_text(new, encoding="utf-8", newline="\n")
    return True


def write_changelog(version: str, note: str | None) -> bool:
    if not CHANGELOG.exists():
        return False
    text = CHANGELOG.read_text(encoding="utf-8")
    if re.search(rf"^##\s+{re.escape(version)}\s*$", text, re.M):
        return False
    today = datetime.date.today().isoformat()
    body = note.strip() if note else f"版本号更新到 `{version}`。"
    section = f"## {version}\n\n- {body}（{today}）\n"
    # 插在第一个 "## " 小标题之前，也就是最新一条的正上方
    m = re.search(r"^##\s+\S", text, re.M)
    if m:
        text = text[: m.start()] + section + "\n" + text[m.start():]
    else:
        text = text.rstrip("\n") + "\n\n" + section
    CHANGELOG.write_text(text, encoding="utf-8", newline="\n")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="改插件版本号（market 版号不可复用）")
    parser.add_argument("version", nargs="?", help="新版本号，例如 1.4.0；省略则补丁位 +1")
    parser.add_argument("-n", "--note", help="写进 CHANGELOG 的一句话说明")
    parser.add_argument("--show", action="store_true", help="只打印当前版本号")
    args = parser.parse_args()

    current = read_version()
    if args.show:
        print(current)
        return

    target = args.version or bump_patch(current)
    if not re.fullmatch(r"\d+\.\d+\.\d+", target):
        sys.exit(f"{target!r} 不是 x.y.z 形式。")

    write_metadata(target)
    readme_changed = write_readme(target)
    changelog_changed = write_changelog(target, args.note)

    print(f"版本号：{current} -> {target}")
    print(f"  metadata.yaml  已更新")
    print(f"  README.md      {'已更新' if readme_changed else '无需改动'}")
    print(f"  CHANGELOG.md   {'已更新' if changelog_changed else '已有该版本小节'}")
    print("\n提交并推送：")
    print(f'  git add -A && git commit -m "chore: release {target}" && git push')
    print("如果插件市场还报「该版本号已经使用过」，直接再跑一次本脚本换个号重新推送。")


if __name__ == "__main__":
    main()
