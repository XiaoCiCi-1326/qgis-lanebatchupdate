# -*- coding: utf-8 -*-
"""一键完成：打包 -> commit -> push"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)


def run(cmd, check=True):
    print(f"\n>>> {cmd}")
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result


# 1. 打包
print("=" * 60)
print("1/3 打包 release")
print("=" * 60)
run("python make_release.py")

# 列出 release 文件
print("\nrelease 目录:")
release_dir = ROOT / "release"
if release_dir.exists():
    for f in sorted(release_dir.iterdir()):
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name}  ({size_kb:.1f} KB)")

# 2. commit
print("\n" + "=" * 60)
print("2/3 git add + commit")
print("=" * 60)
run("git add -A")
status = run("git status --short", check=False)
print("待提交变更:\n" + (status.stdout or "  (无)"))

# 从 metadata.txt 读版本号
metadata = (ROOT / "metadata.txt").read_text(encoding="utf-8")
version = "unknown"
for line in metadata.splitlines():
    if line.startswith("version="):
        version = line.split("=", 1)[1].strip()
        break

commit_msg = f"v{version}: 修嵌套commit失败 + 加策略6(同link RBDY复用)"
print(f"\n提交信息: {commit_msg}")

# 跳过如果没有变更
if not status.stdout.strip():
    print("\n没有变更，跳过 commit")
else:
    run(f'git commit -m "{commit_msg}"')

# 3. push
print("\n" + "=" * 60)
print("3/3 git push")
print("=" * 60)
branch = run("git rev-parse --abbrev-ref HEAD", check=False).stdout.strip() or "main"
print(f"当前分支: {branch}")
run(f"git push origin {branch}")

print("\n" + "=" * 60)
print(f"完成！v{version} 已发布到 git + release/")
print("=" * 60)