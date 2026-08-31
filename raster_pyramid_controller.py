# -*- coding: utf-8 -*-
"""为 QGIS 当前已加载的栅格图层批量生成金字塔（overview），加速画布操作。

无需选择文件夹，直接读取 QGIS 当前工程的栅格图层，
过滤出有 .tif/.tiff 源文件的，逐个生成 .ovr 金字塔。
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


def _has_pyramid(tif_path):
    """检查 TIF 是否已有金字塔（内部或外部）"""
    gdal = _try_gdal()
    if gdal is None:
        return False
    try:
        ds = gdal.Open(tif_path, gdal.GA_ReadOnly)
        if ds is None:
            return False
        band = ds.GetRasterBand(1)
        if band is None:
            return False
        # 有 overview 就算有金字塔
        has_ovr = band.GetOverviewCount() > 0
        ds = None
        return has_ovr
    except Exception:
        return False


def _build_overview(tif_path, resampling="BILINEAR"):
    gdal = _try_gdal()
    if gdal is None:
        return False, "未找到 GDAL Python 绑定，请确认 QGIS 安装完整。"
    levels = [2, 4, 8, 16]
    try:
        # 以可写模式打开，生成内部金字塔（而非外部 .ovr）
        ds = gdal.Open(tif_path, gdal.GA_Update)
        if ds is None:
            return False, "GDAL 无法打开该文件（可能已损坏、被占用或只读）"
        try:
            ds.BuildOverviews(resampling, levels)
        except Exception as exc:
            return False, f"BuildOverviews 失败：{exc}"
        finally:
            try:
                ds = None
            except Exception:
                pass
        return True, "已生成金字塔"
    except Exception as exc:
        return False, f"异常：{exc}"


def _raster_source_path(layer):
    """提取栅格图层的磁盘路径（仅文件型），跳过内存/服务型。"""
    if not isinstance(layer, QgsRasterLayer):
        return None
    src = layer.source()
    if not src:
        return None
    # 跳过内存图层（source 以 "memory:" 开头）
    if src.lower().startswith("memory:") or src.lower().startswith("netcdf:"):
        return None
    # 跳过非文件型（包含 ?: 等但无扩展名或非 TIF）
    lower = src.lower()
    if not (lower.endswith(".tif") or lower.endswith(".tiff")):
        # 可能是服务型，取 provider type
        provider = layer.providerType() or ""
        if provider.lower() not in ("gdal", ""):
            return None
        # gdal provider 但无 .tif 扩展，跳过
        return None
    # 去掉 QGIS 的 "|layername=" 后缀
    if "|" in src:
        src = src.split("|")[0]
    return os.path.normpath(src)


class RasterPyramidController:
    """为 QGIS 当前已加载的栅格图层批量生成金字塔。

    使用方法：
      点击工具栏「当前栅格生成金字塔」按钮
      → 自动列出当前工程中所有栅格图层
      → 对有 .tif/.tiff 源文件的逐个生成 .ovr
      → 完成后再加载画布流畅度提升 5-10 倍
    """

    def __init__(self, iface=None, plugin_dir=None):
        self.iface = iface
        self.plugin_dir = plugin_dir or os.path.dirname(__file__)
        self.action = None

    # ------------------------------------------------------------------
    # GUI 注册 / 卸载
    # ------------------------------------------------------------------
    def initGui(self, actions_master):
        icon_path = os.path.join(self.plugin_dir, "icon_raster_pyramid.svg")
        self.action = QAction(QIcon(icon_path), "TIF 生成金字塔", self.iface.mainWindow())
        self.action.setToolTip(
            "为 QGIS 当前已加载的栅格图层生成金字塔，"
            "提升移动画布与缩放流畅度"
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToVectorMenu("车道处理工具", self.action)
        actions_master.append(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removeVectorToolBarIcon(self.action)
            self.iface.removePluginMenu("车道处理工具", self.action)
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
                "未找到 GDAL Python 绑定，无法生成金字塔。\n"
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

        # 3. 分类：已建金字塔 / 待处理
        to_process = []
        already_done = []
        for layer, path in layers:
            if _has_pyramid(path):
                already_done.append((layer, path))
            else:
                to_process.append((layer, path))

        # 4. 确认弹窗
        already_count = len(already_done)
        skip_count = len(skip_reasons)
        process_count = len(to_process)

        detail_lines = [f"当前工程栅格图层共 {len(layers)} 个："]
        if already_count:
            detail_lines.append(f"  已建金字塔：{already_count} 个（跳过）")
        if skip_count:
            detail_lines.append(f"  非文件型/不存在：{skip_count} 个（跳过）")
        if process_count:
            detail_lines.append(f"  待生成金字塔：{process_count} 个")
        else:
            detail_lines.append(f"  待生成金字塔：0 个（全部已建）")

        if process_count == 0:
            QMessageBox.information(
                self.iface.mainWindow(),
                "TIF 金字塔生成",
                "\n".join(detail_lines) + "\n\n无需处理。",
            )
            return

        confirm = QMessageBox.question(
            self.iface.mainWindow(),
            "TIF 金字塔生成",
            "\n".join(detail_lines) + "\n\n"
            f"将对 {process_count} 个栅格图层生成金字塔。\n"
            "是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if confirm != QMessageBox.Yes:
            return

        # 5. 进度对话框
        progress = QProgressDialog(
            "正在生成金字塔…", "取消", 0, process_count, self.iface.mainWindow()
        )
        progress.setWindowTitle("TIF 金字塔生成")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        success_count = 0
        failed = []
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

            ok, msg = _build_overview(path)
            if ok:
                success_count += 1
            else:
                failed.append((layer.name(), msg))

            QApplication.processEvents()

        progress.setValue(process_count)

        # 6. 报告
        summary = [
            f"总栅格图层：{len(layers)} 个",
            f"跳过（非文件/不存在）：{skip_count} 个",
            f"已建金字塔：{already_count} 个",
            f"成功生成：{success_count} 个",
            f"失败：{len(failed)} 个",
        ]
        if cancelled:
            summary.append("⚠ 用户取消（部分成功）")

        if failed:
            summary.append("\n失败明细（前 10 条）：")
            for name, msg in failed[:10]:
                summary.append(f"  • {name}: {msg}")
            if len(failed) > 10:
                summary.append(f"  ... 共 {len(failed)} 条失败")

        QMessageBox.information(
            self.iface.mainWindow(),
            "TIF 金字塔生成",
            "\n".join(summary),
        )

        if success_count > 0:
            self.iface.messageBar().pushMessage(
                "车道工具",
                f"已为 {success_count} 个栅格图层生成金字塔。"
                "建议重新加载这些图层（卸载后重新拖入）以生效。",
                Qgis.Info,
                duration=8,
            )
