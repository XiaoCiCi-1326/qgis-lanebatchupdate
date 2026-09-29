# -*- coding: utf-8 -*-
"""发布 GitHub Release：自动从 metadata.txt 读版本号 + release/ 下的 zip"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT
PLUGIN_DIR = ROOT / "lanebatchupdate"
os.chdir(ROOT)


def run(cmd, check=True):
    print(f"\n>>> {cmd}")
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    # 不打印 stdout/stderr，避免 gbk 编码错误
    if check and result.returncode != 0:
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}", file=sys.stderr)
        sys.exit(f"命令失败 (exit {result.returncode}): {cmd}")
    return result


# 1. 读版本号
metadata = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
version = "unknown"
for line in metadata.splitlines():
    if line.startswith("version="):
        version = line.split("=", 1)[1].strip()
        break

print(f"版本: v{version}")

# 2. 找 zip（make_release.py 输出到 ../release/，先找 ../release/ 再找 ./release/）
release_dir = ROOT.parent / "release"
if not release_dir.exists():
    release_dir = ROOT / "release"
zips = sorted(release_dir.glob(f"*v{version}*.zip")) if release_dir.exists() else []
if not zips:
    print(f"\n在 release/ 没找到 v{version} 的 zip，请先跑：python make_release.py")
    sys.exit(1)
zip_path = zips[-1]
print(f"压缩包: {zip_path.name}  ({zip_path.stat().st_size / 1024:.1f} KB)")

# 3. 检查 gh CLI
gh_check = run("gh --version", check=False)
if gh_check.returncode != 0:
    print("\n未检测到 gh CLI，请安装 GitHub CLI 后重试:")
    print("  winget install --id GitHub.cli")
    print("或者手动去 https://github.com/XiaoCiCi-1326/qgis-lanebatchupdate/releases/new 发布")
    sys.exit(1)

# 4. 检查 gh 认证（不打印 stdout，避免 gbk 编码错误）
auth = subprocess.run("gh auth status", shell=True, capture_output=True)
if auth.returncode != 0:
    print("\ngh 未认证，请先运行: gh auth login")
    sys.exit(1)
print("gh 已认证")

# 5. 发布 release（删除旧的同名 tag 再发，避免 "already exists"）
tag = f"v{version}"
title = f"Lane 批量刷值工具 v{version}"
# 读取 CHANGELOG.md 顶部第一个 `## v<version>` 段作为 Release notes
changelog_path = PROJECT_ROOT / "CHANGELOG.md"
notes = f"## v{version}\n\n（请编辑 publish_release.py 自动读取 CHANGELOG.md 或在此补充本次更新说明）"
try:
    cl_text = changelog_path.read_text(encoding="utf-8")
    m = re.search(
        rf"##\s*v?{re.escape(version)}\s*\n(.*?)(?=\n##\s*v?\d|\Z)",
        cl_text,
        re.DOTALL,
    )
    if m:
        body = m.group(1).strip()
        if body:
            notes = f"## v{version}\n\n{body}"
except Exception as e:
    print(f"读取 CHANGELOG.md 失败: {e}")

print(f"\n准备发布: {tag}")
print(f"标题: {title}")
print(f"\n---\n{notes}\n---")

# 删除已存在的 release 和 tag（幂等发布）
run(f"gh release delete {tag} --yes", check=False)
run(f"git tag -d {tag}", check=False)
run(f"git push origin :refs/tags/{tag}", check=False)

# 创建 release
# notes 里含换行 / 中文，直接拼到 shell 字符串里会被 cmd.exe 截断；
# 改写成临时文件 + --notes-file，避免 shell 转义问题。
import tempfile
notes_file = PROJECT_ROOT / f".release_notes_{tag}.md"
notes_file.write_text(notes + "\n", encoding="utf-8")
try:
    cmd = (
        f'gh release create {tag} "{zip_path}" '
        f'--title "{title}" '
        f'--notes-file "{notes_file}"'
    )
    run(cmd)
finally:
    try:
        notes_file.unlink()
    except OSError:
        pass

print("\n" + "=" * 60)
print(f"完成！Release 已发布：")
print(f"https://github.com/XiaoCiCi-1326/qgis-lanebatchupdate/releases/tag/{tag}")
print("=" * 60)