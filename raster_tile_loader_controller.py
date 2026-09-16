# -*- coding: utf-8 -*-
"""Load selected MAP_TILE rasters into a folder-named group hierarchy."""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QApplication, QAbstractItemView, QFileDialog, QMessageBox, QProgressDialog
from qgis.core import Qgis, QgsCoordinateTransform, QgsGeometry, QgsProject, QgsRasterLayer, QgsVectorLayer


class RasterTileLoaderController:
    """Imports tiles intersecting the selected MAP_TILE polygon into type groups."""

    RASTER_KINDS = ("intensity", "density")
    ROOT_DIR_KEY = "LaneBatchUpdate/rasterTileLoaderRootDir"

    def __init__(self, iface, plugin_dir):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.action = None
        self.settings = QSettings()

    def initGui(self, actions_master):
        icon_path = os.path.join(self.plugin_dir, "icon_raster_tile_loader.svg")
        self.action = QAction(QIcon(icon_path), "加载 MAP_TILE 栅格", self.iface.mainWindow())
        self.action.setToolTip("按选中的 MAP_TILE 自动加载 intensity 和 density 栅格")
        self.action.triggered.connect(self.run)
        self.iface.addPluginToVectorMenu("车道处理工具", self.action)
        actions_master.append(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removeVectorToolBarIcon(self.action)
            self.iface.removePluginMenu("车道处理工具", self.action)
            self.action = None

    def _selected_tile_geometry(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer) or layer.name() != "MAP_TILE":
            return None, "请先激活 MAP_TILE 图层。"
        if layer.geometryType() != 2:
            return None, "MAP_TILE 必须是面图层。"
        selected = layer.selectedFeatures()
        if len(selected) != 1:
            return None, "请在 MAP_TILE 图层中只选中一个要素。"
        geometry = selected[0].geometry()
        if geometry is None or geometry.isEmpty():
            return None, "选中的 MAP_TILE 要素没有有效的面几何。"
        return (geometry, layer.crs()), None

    @staticmethod
    def _tif_files(directory):
        matches = []
        for root, _, files in os.walk(directory):
            for filename in files:
                if filename.lower().endswith((".tif", ".tiff")):
                    matches.append(os.path.join(root, filename))
        return sorted(matches)

    @staticmethod
    def _find_or_create_group(root_name, child_name):
        """Return root_name/child_name, creating only the missing nodes."""
        root = QgsProject.instance().layerTreeRoot()
        parent = root.findGroup(root_name)
        if parent is None:
            parent = root.addGroup(root_name)
        child = parent.findGroup(child_name)
        return child if child is not None else parent.addGroup(child_name)

    def _choose_root_dirs(self):
        """Open one Qt folder chooser that permits Ctrl/Shift multi-selection."""
        start_dir = str(self.settings.value(self.ROOT_DIR_KEY, "") or "")
        if not os.path.isdir(start_dir):
            start_dir = os.path.expanduser("~")

        dialog = QFileDialog(
            self.iface.mainWindow(), "选择包含 intensity 和 density 的目录", start_dir
        )
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.DontResolveSymlinks, True)
        dialog.setLabelText(QFileDialog.LookIn, "查找位置")
        dialog.setLabelText(QFileDialog.FileName, "目录")
        dialog.setLabelText(QFileDialog.FileType, "目录类型")
        dialog.setLabelText(QFileDialog.Accept, "选择文件夹")
        dialog.setLabelText(QFileDialog.Reject, "取消")
        for view in dialog.findChildren(QAbstractItemView):
            view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        if dialog.exec_() != QFileDialog.Accepted:
            return []
        return [os.path.normpath(path) for path in dialog.selectedFiles()]

    @staticmethod
    def _is_already_loaded(path):
        normalized = os.path.normcase(os.path.normpath(path))
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer):
                source = layer.source().split("|", 1)[0]
                if os.path.normcase(os.path.normpath(source)) == normalized:
                    return True
        return False

    @staticmethod
    def _intersects_tile(tile_geometry, tile_crs, raster):
        raster_extent = raster.extent()
        if raster_extent.isEmpty():
            return False
        geometry = tile_geometry
        if tile_crs != raster.crs():
            geometry = QgsGeometry(tile_geometry)
            geometry.transform(QgsCoordinateTransform(tile_crs, raster.crs(), QgsProject.instance()))
        return geometry.intersects(raster_extent)

    def run(self):
        tile, error = self._selected_tile_geometry()
        if error:
            QMessageBox.warning(self.iface.mainWindow(), "加载 MAP_TILE 栅格", error)
            return
        tile_geometry, tile_crs = tile

        root_dirs = self._choose_root_dirs()
        if not root_dirs:
            return

        directory_data = []
        invalid_directories = []
        for root_dir in root_dirs:
            folders = {kind: os.path.join(root_dir, kind) for kind in self.RASTER_KINDS}
            missing = [kind for kind, folder in folders.items() if not os.path.isdir(folder)]
            if missing:
                invalid_directories.append("{}（缺少 {}）".format(root_dir, "、".join(missing)))
                continue
            group_name = os.path.basename(os.path.normpath(root_dir)) or root_dir
            files_by_kind = {kind: self._tif_files(folder) for kind, folder in folders.items()}
            directory_data.append((root_dir, group_name, files_by_kind))

        if not directory_data:
            QMessageBox.warning(
                self.iface.mainWindow(), "目录不完整",
                "没有可导入的目录。每个目录都必须包含 intensity 和 density 子目录。\n\n"
                + "\n".join(invalid_directories),
            )
            return
        self.settings.setValue(self.ROOT_DIR_KEY, directory_data[-1][0])

        total = sum(
            len(paths) for _, _, files_by_kind in directory_data for paths in files_by_kind.values()
        )
        if total == 0:
            QMessageBox.information(self.iface.mainWindow(), "未找到栅格", "所选目录的 intensity 和 density 中均未找到 .tif 或 .tiff 文件。")
            return

        progress = QProgressDialog("正在查找与 MAP_TILE 相交的栅格...", "取消", 0, total, self.iface.mainWindow())
        progress.setWindowTitle("批量加载 MAP_TILE 栅格")
        progress.setMinimumDuration(0)
        progress.setValue(0)

        summaries = {}
        step = 0
        cancelled = False
        for _, group_name, files_by_kind in directory_data:
            summary = {kind: {"loaded": 0, "skipped": 0, "invalid": 0, "outside": 0} for kind in self.RASTER_KINDS}
            summaries[group_name] = summary
            for kind, paths in files_by_kind.items():
                group = self._find_or_create_group(group_name, kind)
                for path in paths:
                    if progress.wasCanceled():
                        cancelled = True
                        break
                    step += 1
                    progress.setValue(step - 1)
                    progress.setLabelText("({}/{}) {}/{}".format(step, total, group_name, os.path.basename(path)))
                    QApplication.processEvents()
                    if self._is_already_loaded(path):
                        summary[kind]["skipped"] += 1
                        continue
                    raster = QgsRasterLayer(path, os.path.splitext(os.path.basename(path))[0], "gdal")
                    if not raster.isValid():
                        summary[kind]["invalid"] += 1
                        continue
                    try:
                        intersects = self._intersects_tile(tile_geometry, tile_crs, raster)
                    except Exception:
                        raster = None
                        summary[kind]["invalid"] += 1
                        continue
                    if not intersects:
                        raster = None
                        summary[kind]["outside"] += 1
                        continue
                    QgsProject.instance().addMapLayer(raster, False)
                    group.addLayer(raster)
                    summary[kind]["loaded"] += 1
                if cancelled:
                    break
            if cancelled:
                break
        progress.setValue(total)

        lines = []
        for group_name, summary in summaries.items():
            loaded = sum(result["loaded"] for result in summary.values())
            skipped = sum(result["skipped"] for result in summary.values())
            outside = sum(result["outside"] for result in summary.values())
            invalid = sum(result["invalid"] for result in summary.values())
            lines.append("{}：导入 {}，已存在 {}，不相交 {}，无效 {}".format(
                group_name, loaded, skipped, outside, invalid
            ))
        if invalid_directories:
            lines.append("未处理目录：\n" + "\n".join(invalid_directories))
        if cancelled:
            lines.append("已取消，已完成的导入会保留。")
        QMessageBox.information(self.iface.mainWindow(), "批量加载 MAP_TILE 栅格", "\n".join(lines))
        loaded = sum(result["loaded"] for summary in summaries.values() for result in summary.values())
        if loaded:
            self.iface.messageBar().pushMessage(
                "车道工具", "已按 MAP_TILE 从 {} 个目录导入 {} 个栅格。".format(len(summaries), loaded),
                Qgis.Info, duration=6,
            )
