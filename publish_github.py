# -*- coding: utf-8 -*-
"""
推送到 GitHub 并（可选）打 Release 标签。

用法:
  python publish_github.py              # 仅 push 当前 main
  python publish_github.py --release    # 打包 zip + 提交 + 打 tag + push（大更新用）

Release 说明:
  push 后若用了 --release，到 GitHub 仓库 → Releases → Draft a new release，
  选择刚推送的 tag，上传 release/ 下生成的 zip 作为附件。
  或安装 GitHub CLI 后: gh release create v1.0.x release/*.zip --title "v1.0.x"
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
REPO_URL = "https://github.com/XiaoCiCi-1326/qgis-lanebatchupdate"


def read_version() -> str:
    for line in (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("version="):
            return line.split("=", 1)[1].strip()
    return "unknown"


def run(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=PLUGIN_DIR,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def ensure_changelog(version: str) -> None:
    tag = f"v{version}"
    cl = PLUGIN_DIR / "CHANGELOG.md"
    text = cl.read_text(encoding="utf-8") if cl.is_file() else "# 更新日志\n"
    if f"## {tag}" in text or f"## v{version}" in text:
        return
    block = f"\n## v{version}\n- （请补充本版更新说明）\n"
    if "# 更新日志" in text:
        text = text.replace("# 更新日志\n", f"# 更新日志\n{block}", 1)
    else:
        text = f"# 更新日志\n{block}\n" + text
    cl.write_text(text, encoding="utf-8")
    print(f"已在 CHANGELOG.md 追加 {tag} 占位条目，请编辑后重新运行。")


def main():
    parser = argparse.ArgumentParser(description="推送 lanebatchupdate 到 GitHub")
    parser.add_argument(
        "--release",
        action="store_true",
        help="大更新：make_release 打包、提交、打 tag v{version}、push tags",
    )
    parser.add_argument(
        "--message",
        "-m",
        default="",
        help="提交说明（默认使用版本号）",
    )
    args = parser.parse_args()

    version = read_version()
    tag = f"v{version}"
    msg = args.message.strip() or f"{tag}: 更新插件"

    if args.release:
        ensure_changelog(version)
        run([sys.executable, str(PLUGIN_DIR / "make_release.py")])

    status = run(["git", "status", "--porcelain"], check=True)
    if status.stdout.strip():
        run(["git", "add", "-A"])
        run(["git", "commit", "-m", msg])
    else:
        print("无未提交改动，跳过 commit")

    run(["git", "push", "origin", "main"])

    if args.release:
        run(["git", "tag", "-f", tag])
        run(["git", "push", "origin", tag, "--force"])
        zip_glob = list((PLUGIN_DIR.parent / "release").glob(f"lanebatchupdate_v{version}_*.zip"))
        print("\n=== 发布完成（代码已 push）===")
        print(f"仓库: {REPO_URL}")
        print(f"标签: {tag}")
        if zip_glob:
            print(f"ZIP: {zip_glob[-1]}")
        print("\n请到 GitHub → Releases → New release：")
        print(f"  1. 选择 tag {tag}")
        print("  2. 上传上述 ZIP 作为附件")
        print(f"  3. 发布页: {REPO_URL}/releases/new")
    else:
        print(f"\n已 push 到 {REPO_URL}")


if __name__ == "__main__":
    main()
