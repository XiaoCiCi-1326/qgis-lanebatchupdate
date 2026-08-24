# -*- coding: utf-8 -*-
"""为 QGIS 当前已加载的栅格图层批量压缩 TIF 文件，减少体积、加快加载速度。

压缩原理：
- 未压缩 TIF：原始像素数据，体积大、读写慢
- LZW 压缩：无损压缩，减少 50-70% 体积，加载更快
- DEFLATE 压缩：无损压缩，效果类似 LZW，兼容性更好

工作流程：
1. 点击工具栏按钮
2. 自动扫描当前 QGIS 已加载的栅格图层
3. 对未压缩的 TIF 逐个压缩（保留原文件，生成 _compressed.tif）
4. 完成后手动替换原图层
"""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QMessageBox,
    QProgressDialog,
)
from qgis.core import Qgis, QgsProject, QgsRasterLayer


def _try_gdal():
    try:
        from osgeo import gdal  # type: ignore
        return gdal
    except Exception:
        try:
            import gdal  # type: ignore
            return gdal
        except Exception:
            return None


def _get_compression(tif_path):
    """获取 TIF 的压缩方式（None=未压缩）"""
    gdal = _try_gdal()
    if gdal is None:
        return None
    try:
        ds = gdal.Open(tif_path, gdal.GA_ReadOnly)
        if ds is None:
            return None
        band = ds.GetRasterBand(1)
        if band is None:
            return None
        # 获取压缩方式
        compression = band.GetMetadata_Dict().get("COMPRESSION", "NONE")
        ds = None
        return compression if compression != "NONE" else None
    except Exception:
        return None


def _compress_tif(src_path, dst_path, compression="LZW"):
    """压缩 TIF 文件（LZW 或 DEFLATE）"""
    gdal = _try_gdal()
    if gdal is None:
        return False, "未找到 GDAL Python 绑定"
    try:
        # 转换选项：压缩 + 切片 + 保留地理信息
        options = gdal.TranslateOptions(
            format="GTiff",
            creationOptions=[
                f"COMPRESS={compression}",
                "TILED=YES",
                "PREDICTOR=2",  # 提高压缩率
                "COPY_SRC_OVERVIEWS=YES"  # 保留金字塔
            ]
        )
        ds = gdal.Translate(dst_path, src_path, options=options)
        if ds is None:
            return False, "gdal.Translate 返回 None"
        ds = None
        return True, "已压缩"
    except Exception as exc:
        return False, f"压缩失败：{exc}"


def _raster_source_path(layer):
    """提取栅格图层的磁盘路径（仅文件型）"""
    if not isinstance(layer, QgsRasterLayer):
        return None
    src = layer.source()
    if not src:
        return None
    if src.lower().startswith("memory:") or src.lower().startswith("netcdf:"):
        return None
    lower = src.lower()
    if not (lower.endswith(".tif") or lower.endswith(".tiff")):
        provider = layer.providerType() or ""
        if provider.lower() not in ("gdal", ""):
            return None
        return None
    if "|" in src:
        src = src.split("|")[0]
    return os.path.normpath(src)


class RasterCompressController:
    """为 QGIS 当前已加载的栅格图层批量压缩 TIF 文件。

    使用方法：
      点击工具栏「TIF 压缩」按钮
      → 自动列出未压缩的 TIF
      → 逐个压缩为 _compressed.tif（LZW 无损压缩）
      → 手动替换原图层（卸载旧图层，加载新 _compressed.tif）
    """

    def __init__(self, iface=None, plugin_dir=None):
        self.iface = iface
        self.plugin_dir = plugin_dir or os.path.dirname(__file__)
        self.action = None

    # ------------------------------------------------------------------
    # GUI 注册 / 卸载
    # ------------------------------------------------------------------
    def initGui(self, actions_master):
        icon_path = os.path.join(self.plugin_dir, "icon_raster_compress.svg")
        self.action = QAction(QIcon(icon_path), "TIF 压缩", self.iface.mainWindow())
        self.action.setToolTip(
            "将 QGIS 当前已加载的栅格图层压缩为 LZW 格式，"
            "减少 50-70% 体积，加快加载和渲染速度"
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToVectorMenu("车道处理工具", self.action)
        actions_master.append(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removeVectorToolBarIcon(self.action)
            self.iface.removePluginFromVectorMenu("车道处理工具", self.action)
            self.action = None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def run(self):
        # 1. 检查 GDAL
        gdal = _try_gdal()
        if gdal is None:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "GDAL 不可用",
                "未找到 GDAL Python 绑定，无法压缩 TIF。\n"
                "请确认 QGIS 安装包含 GDAL。",
            )
            return

        # 2. 收集当前栅格图层
        layers = []
        skip_reasons = {}
        for layer in reversed(list(QgsProject.instance().mapLayers().values())):
            path = _raster_source_path(layer)
            if path is None:
                skip_reasons[layer.name()] = "非文件型栅格（跳过）"
                continue
            if not os.path.isfile(path):
                skip_reasons[layer.name()] = "文件不存在（跳过）"
                continue
            layers.append((layer, path))

        if not layers:
            QMessageBox.information(
                self.iface.mainWindow(),
                "无栅格图层",
                "当前工程没有已加载的文件型栅格图层。",
            )
            return

        # 3. 分类：已压缩 / 待处理
        to_process = []
        already_compressed = []
        for layer, path in layers:
            comp = _get_compression(path)
            if comp:
                already_compressed.append((layer, path, comp))
            else:
                to_process.append((layer, path))

        # 4. 确认弹窗
        already_count = len(already_compressed)
        skip_count = len(skip_reasons)
        process_count = len(to_process)

        detail_lines = [f"当前工程栅格图层共 {len(layers)} 个："]
        if already_count:
            detail_lines.append(f"  已压缩：{already_count} 个（跳过）")
        if skip_count:
            detail_lines.append(f"  非文件型/不存在：{skip_count} 个（跳过）")
        if process_count:
            detail_lines.append(f"  待压缩：{process_count} 个")
        else:
            detail_lines.append(f"  待压缩：0 个（全部已压缩）")

        if process_count == 0:
            QMessageBox.information(
                self.iface.mainWindow(),
                "TIF 压缩",
                "\n".join(detail_lines) + "\n\n无需处理。",
            )
            return

        confirm = QMessageBox.question(
            self.iface.mainWindow(),
            "TIF 压缩",
            "\n".join(detail_lines) + "\n\n"
            f"将对 {process_count} 个栅格图层压缩为 LZW 格式。\n"
            "压缩方式：LZW（无损）+ 切片化 + 保留金字塔\n"
            "生成文件名：原文件名_compressed.tif\n"
            "预计体积减少：50-70%\n\n"
            "是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if confirm != QMessageBox.Yes:
            return

        # 5. 进度对话框
        progress = QProgressDialog(
            "正在压缩 TIF…", "取消", 0, process_count, self.iface.mainWindow()
        )
        progress.setWindowTitle("TIF 压缩")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        success_count = 0
        failed = []
        compressed_files = []
        cancelled = False

        for idx, (layer, path) in enumerate(to_process, 1):
            if progress.wasCanceled():
                cancelled = True
                break

            label = layer.name()
            if len(label) > 45:
                label = label[:42] + "..."
            progress.setLabelText(f"({idx}/{process_count}) {label}")
            progress.setValue(idx - 1)

            # 生成目标路径：原文件名_compressed.tif
            base, ext = os.path.splitext(path)
            dst_path = f"{base}_compressed{ext}"

            ok, msg = _compress_tif(path, dst_path, compression="LZW")
            if ok:
                success_count += 1
                # 计算压缩率
                try:
                    src_size = os.path.getsize(path)
                    dst_size = os.path.getsize(dst_path)
                    ratio = (1 - dst_size / src_size) * 100 if src_size > 0 else 0
                    compressed_files.append((layer.name(), dst_path, ratio))
                except Exception:
                    compressed_files.append((layer.name(), dst_path, 0))
            else:
                failed.append((layer.name(), msg))

            QApplication.processEvents()

        progress.setValue(process_count)

        # 6. 报告
        summary = [
            f"总栅格图层：{len(layers)} 个",
            f"跳过（非文件/不存在）：{skip_count} 个",
            f"已压缩：{already_count} 个",
            f"成功压缩：{success_count} 个",
            f"失败：{len(failed)} 个",
        ]
        if cancelled:
            summary.append("⚠ 用户取消（部分成功）")

        if compressed_files:
            summary.append("\n压缩结果（请手动替换原图层）：")
            for name, dst, ratio in compressed_files[:5]:
                summary.append(f"  • {name} → {os.path.basename(dst)} (减少 {ratio:.1f}%)")
            if len(compressed_files) > 5:
                summary.append(f"  ... 共 {len(compressed_files)} 个文件")

        if failed:
            summary.append("\n失败明细（前 5 条）：")
            for name, msg in failed[:5]:
                summary.append(f"  • {name}: {msg}")
            if len(failed) > 5:
                summary.append(f"  ... 共 {len(failed)} 条失败")

        QMessageBox.information(
            self.iface.mainWindow(),
            "TIF 压缩",
            "\n".join(summary),
        )

        if success_count > 0:
            self.iface.messageBar().pushMessage(
                "车道工具",
                f"已压缩 {success_count} 个 TIF 文件。"
                "建议：卸载原图层，加载新的 _compressed.tif 文件。",
                Qgis.Info,
                duration=10,
            )
