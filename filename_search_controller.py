# -*- coding: utf-8 -*-
"""
文件名搜索工具
功能：选中 .shp 图层中的要素，在 Windows 资源管理器中自动搜索这些 file_name 字段值对应的文件
"""
from qgis.PyQt.QtWidgets import QAction, QMenu, QMessageBox, QToolButton
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.core import Qgis
import os
import re
import shutil
import subprocess
from datetime import datetime


class FileNameSearchController:
    def __init__(self, iface, plugin_dir):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.search_action = None
        self.copy_action = None
        self.toolbar_button = None

    def initGui(self, actions):
        search_icon_path = os.path.join(self.plugin_dir, "icon_filename_search.svg")
        copy_icon_path = os.path.join(self.plugin_dir, "icon_filename_copy.svg")
        parent = self.iface.mainWindow()
        self.search_action = QAction(QIcon(search_icon_path), "搜索文件", parent)
        self.search_action.triggered.connect(self.search_files)
        self.copy_action = QAction(QIcon(copy_icon_path), "复制搜索结果到新文件夹", parent)
        self.copy_action.triggered.connect(self.copy_search_results)
        actions.append(self.search_action)

        self.toolbar_button = QToolButton(parent)
        self.toolbar_button.setDefaultAction(self.search_action)
        menu = QMenu(self.toolbar_button)
        menu.addAction(self.copy_action)
        self.toolbar_button.setMenu(menu)
        self.toolbar_button.setPopupMode(QToolButton.MenuButtonPopup)

        self.iface.addPluginToVectorMenu("车道处理工具", self.search_action)
        self.iface.addPluginToVectorMenu("车道处理工具", self.copy_action)

    def add_toolbar_button(self):
        toolbar = self.iface.vectorToolBar()
        if toolbar is not None and self.toolbar_button is not None:
            if self.toolbar_button.parent() is not toolbar:
                self.toolbar_button.setParent(toolbar)
            if toolbar.widgetForAction(self.toolbar_button.defaultAction()) is None:
                toolbar.addWidget(self.toolbar_button)

    def remove_toolbar_button(self):
        toolbar = self.iface.vectorToolBar()
        if toolbar is not None and self.toolbar_button is not None:
            toolbar.removeWidget(self.toolbar_button)

    def unload(self):
        self.remove_toolbar_button()
        for action in (self.search_action, self.copy_action):
            if action is not None:
                try:
                    self.iface.removePluginVectorMenu("车道处理工具", action)
                except (AttributeError, RuntimeError):
                    pass
        self.search_action = None
        self.copy_action = None
        self.toolbar_button = None

    def _get_layer_folder(self, layer):
        """获取图层所在的文件夹路径"""
        layer_source = layer.source()
        if "|" in layer_source:
            shp_path = layer_source.split("|")[0]
        else:
            shp_path = layer_source
        return os.path.normpath(os.path.dirname(shp_path))

    def _extract_grid_name(self, filename):
        """从 file_name 提取坐标并生成 grid_ 前缀的搜索名。"""
        match = re.search(r'-?\d+_-?\d+', filename)
        if match:
            return f"grid_{match.group(0)}"
        return None

    def _open_explorer_search(self, folder, search_query):
        """在资源管理器中打开搜索窗口"""
        try:
            if os.name != 'nt':
                return False
            
            # 规范化路径（Windows 格式）
            normalized_path = os.path.normpath(folder)
            
            # 构建 search-ms URL，与 js2jd 转换控制器使用相同的搜索方式
            # 格式: search-ms:query=<搜索条件>&crumb=location:<路径>
            search_url = f'search-ms:query={search_query}&crumb=location:{normalized_path}'
            
            # 使用 os.startfile 打开（与 js2jd_convert_controller 相同方法）
            os.startfile(search_url)
            return True
            
        except Exception as e:
            return False

    def _get_selected_file_names(self):
        layer = self.iface.activeLayer()
        if layer is None:
            QMessageBox.critical(None, "错误", "请先选择一个图层")
            return None, None, None

        selected_features = layer.selectedFeatures()
        if not selected_features:
            QMessageBox.critical(None, "错误", "请先在图层中选中要素")
            return None, None, None

        field_names = {field.name().upper() for field in layer.fields()}
        if "FILE_NAME" not in field_names:
            QMessageBox.critical(None, "字段缺失", "当前图层缺少 'FILE_NAME' 字段")
            return None, None, None

        file_name_field = next(
            field.name() for field in layer.fields() if field.name().upper() == "FILE_NAME"
        )
        file_names = []
        for feature in selected_features:
            value = feature[file_name_field]
            if value is not None and str(value).strip():
                file_names.append(str(value).strip())

        if not file_names:
            QMessageBox.warning(None, "无数据", "选中的要素没有有效的 file_name 值")
            return None, None, None

        folder = self._get_layer_folder(layer)
        if not os.path.isdir(folder):
            QMessageBox.critical(None, "错误", f"无法找到文件夹：{folder}")
            return None, None, None
        return layer, file_names, folder

    def _get_search_patterns(self, file_names):
        patterns = []
        for name in file_names:
            grid_name = self._extract_grid_name(name)
            if grid_name and grid_name not in patterns:
                patterns.append(grid_name)
        if not patterns:
            QMessageBox.warning(None, "无可搜索名称", "file_name 中未找到坐标格式，例如 -218_-14。")
            return None
        return patterns

    def _find_matching_files(self, folder, patterns):
        matches = []
        seen = set()
        for root, dirs, names in os.walk(folder):
            dirs[:] = [name for name in dirs if not name.startswith("搜索结果_")]
            for name in names:
                file_path = os.path.join(root, name)
                normalized_name = name.lower()
                if any(pattern.lower() in normalized_name for pattern in patterns):
                    normalized_path = os.path.normcase(os.path.normpath(file_path))
                    if normalized_path not in seen:
                        seen.add(normalized_path)
                        matches.append(file_path)
        return matches

    def copy_search_results(self):
        """搜索选中文件并复制到图层同级的新文件夹。"""
        _, file_names, folder = self._get_selected_file_names()
        if not file_names:
            return
        patterns = self._get_search_patterns(file_names)
        if not patterns:
            return

        matches = self._find_matching_files(folder, patterns)
        if not matches:
            QMessageBox.information(
                None,
                "未找到文件",
                "没有找到匹配文件。\n搜索条件：%s" % " OR ".join(patterns),
            )
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = os.path.join(folder, "搜索结果_%s" % stamp)
        try:
            os.makedirs(destination)
            copied = 0
            for source in matches:
                target = os.path.join(destination, os.path.basename(source))
                if os.path.exists(target):
                    stem, extension = os.path.splitext(os.path.basename(source))
                    index = 2
                    while os.path.exists(target):
                        target = os.path.join(destination, "%s_%d%s" % (stem, index, extension))
                        index += 1
                shutil.copy2(source, target)
                copied += 1
            subprocess.Popen(["explorer.exe", destination])
        except (OSError, IOError) as exc:
            QMessageBox.critical(None, "复制失败", "无法创建或写入目标文件夹：%s" % exc)
            return

        self.iface.messageBar().pushMessage(
            "复制搜索结果",
            "已复制 %d 个文件到：%s" % (copied, destination),
            Qgis.Success,
            duration=8,
        )

    def search_files(self):
        """获取选中要素的 file_name 字段值，在资源管理器中自动搜索。"""
        _, file_names, folder = self._get_selected_file_names()
        if not file_names:
            return
        search_patterns = self._get_search_patterns(file_names)
        if not search_patterns:
            return

        search_query = " OR ".join(search_patterns)
        success = self._open_explorer_search(folder, search_query)

        if success:
            self.iface.messageBar().pushMessage(
                "文件名搜索",
                "已在资源管理器中搜索 %d 个文件" % len(file_names),
                Qgis.Success,
                duration=5,
            )
        else:
            try:
                subprocess.Popen(["explorer.exe", folder])
                self.iface.messageBar().pushMessage(
                    "文件名搜索",
                    "已打开文件夹，请手动搜索：%s" % search_query,
                    Qgis.Warning,
                    duration=8,
                )
            except OSError as exc:
                QMessageBox.critical(None, "错误", "无法打开资源管理器：%s" % exc)
