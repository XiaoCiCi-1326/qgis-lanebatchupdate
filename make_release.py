# -*- coding: utf-8 -*-
"""打包 lanebatchupdate 发布版（仅运行所需文件）。"""
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PLUGIN_DIR.parent
BACKUP_DIR = PROJECT_ROOT / "备份"
BACKUP_EXCLUDE = {".git", "__pycache__"}

RELEASE_FILES = (
    "__init__.py",
    "lanebatchupdate.py",
    "metadata.txt",
    "icon.png",
    "icon_speed.png",
    "icon_road2.png",
    "icon_virtual.png",
    "icon_reconstruct_prep.png",
    "icon_reconstruct_full.png",
    "icon_reconstruct_open.png",
    "icon_lane_fix.png",
    "lane_fix_excel.py",
    "lane_fix_engine.py",
    "lane_fix_controller.py",
    "reconstruct_config.py",
    "reconstruct_controller.py",
    "reconstruct_feedback.py",
    "reconstruct_processing.py",
    "reconstruct_workflow.py",
    "reconstruct_algorithms.json.example",
    "安装说明.txt",
)

INSTALL_README = """Lane 批量刷值工具 — 安装说明
================================
版本见 metadata.txt

【环境】
- QGIS 3.x（建议 3.28+，已在 3.32 测试）
- 刷值功能：加载 LANE、LANE_NODE（转向刷值建议加 INTERSECTION）
- 一键重构：另需安装 Z Attribute、Z Tools，工具栏步骤 6~9 按钮可见

【安装】
1. 将整个 lanebatchupdate 文件夹复制到：
   Windows:
     C:\\Users\\<用户名>\\AppData\\Roaming\\QGIS\\QGIS3\\profiles\\default\\python\\plugins\\lanebatchupdate\\
   Linux:
     ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/lanebatchupdate/
2. 打开 QGIS → 插件 → 管理并安装插件 → 已安装
3. 勾选「Lane 批量刷值工具」
4. 重启 QGIS 或重新加载插件

【工具栏按钮】
- 限速刷值 / ROAD_TYPE=2 / 转向个数刷值
- 准备三份数据 / 一键重构(全程)

【可选配置】
若一键重构找不到 Z Tools 按钮，可复制 reconstruct_algorithms.json.example
为 reconstruct_algorithms.json 并填写 Processing 算法 ID（一般留空即可）。

【日志】
运行日志写入插件目录下 log/ 文件夹。

【项目】
https://github.com/XiaoCiCi-1326/qgis-lanebatchupdate

【联系】
制作人：石天赐
2774480158@qq.com
"""


def read_version():
    meta = PLUGIN_DIR / "metadata.txt"
    for line in meta.read_text(encoding="utf-8").splitlines():
        if line.startswith("version="):
            return line.split("=", 1)[1].strip()
    return "unknown"


def backup_current_version():
    """备份当前版本到 备份 目录"""
    version = read_version()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"lanebatchupdate_v{version}_{stamp}"
    backup_path = BACKUP_DIR / backup_name

    if not BACKUP_DIR.exists():
        BACKUP_DIR.mkdir(parents=True)

    shutil.copytree(
        PLUGIN_DIR,
        backup_path,
        ignore=shutil.ignore_patterns(*BACKUP_EXCLUDE),
        dirs_exist_ok=False
    )
    print(f"备份已创建: {backup_path}")
    return backup_path


def main():
    print("=" * 50)
    print("开始发布流程...")
    print("=" * 50)

    print("\n[1/3] 备份当前版本...")
    backup_path = backup_current_version()

    print("\n[2/3] 打包发布文件...")
    version = read_version()
    stamp = datetime.now().strftime("%Y%m%d")
    out_name = f"lanebatchupdate_v{version}_{stamp}"
    release_dir = PROJECT_ROOT / "release" / out_name
    zip_path = PROJECT_ROOT / "release" / f"{out_name}.zip"
    plugin_out = release_dir / "lanebatchupdate"

    if release_dir.exists():
        shutil.rmtree(release_dir)
    plugin_out.mkdir(parents=True)

    install_path = PLUGIN_DIR / "_install_readme_tmp.txt"
    install_path.write_text(INSTALL_README, encoding="utf-8")

    copied = []
    missing = []
    for name in RELEASE_FILES:
        src = PLUGIN_DIR / ("安装说明.txt" if name == "安装说明.txt" else name)
        if name == "安装说明.txt":
            src = install_path
        if not src.is_file():
            missing.append(name)
            continue
        dst = plugin_out / (name if name != "安装说明.txt" else "安装说明.txt")
        shutil.copy2(src, dst)
        copied.append(name)

    install_path.unlink(missing_ok=True)

    if missing:
        raise SystemExit(f"缺少文件: {missing}")

    print(f"\n[3/3] 创建 ZIP 包...")

    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(release_dir):
            for fname in files:
                full = Path(root) / fname
                arc = full.relative_to(release_dir.parent)
                zf.write(full, arc.as_posix())

    print("\n" + "=" * 50)
    print("发布完成！")
    print("=" * 50)
    print(f"备份: {backup_path}")
    print(f"发布文件夹: {release_dir}")
    print(f"ZIP 包: {zip_path}")
    print(f"版本: {version}")
    print(f"文件数: {len(copied)}")
    for name in copied:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
