# -*- coding: utf-8 -*-
"""
文件名搜索工具
功能：选中 .shp 图层中的要素，在 Windows 资源管理器中自动搜索这些 file_name 字段值对应的文件
"""
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtGui import QIcon
from qgis.core import Qgis
import os
import subprocess
import re


class FileNameSearchController:
    def __init__(self, iface, plugin_dir):
        self.iface = iface
        self.plugin_dir = plugin_dir

    def initGui(self, actions):
        from qgis.PyQt.QtWidgets import QAction
        icon_path = os.path.join(self.plugin_dir, "icon_filename_search.svg")
        action = QAction(QIcon(icon_path), "搜索文件", self.iface.mainWindow())
        action.triggered.connect(self.search_files)
        self.iface.addPluginToVectorMenu("车道处理工具", action)
        actions.append(action)

    def unload(self):
        pass

    def _get_layer_folder(self, layer):
        """获取图层所在的文件夹路径"""
        layer_source = layer.source()
        if "|" in layer_source:
            shp_path = layer_source.split("|")[0]
        else:
            shp_path = layer_source
        return os.path.normpath(os.path.dirname(shp_path))

    def _extract_key_pattern(self, filename):
        """提取文件名中的关键数字模式，如 -168_-211"""
        match = re.search(r'-?\d+_-?\d+', filename)
        if match:
            return match.group(0)
        return filename

    def _open_explorer_search(self, folder, search_query):
        """在资源管理器中打开搜索窗口"""
        try:
            if os.name != 'nt':
                return False
            
            # 规范化路径（Windows 格式）
            normalized_path = os.path.normpath(folder)
            
            # 构建 search-ms URL
            # 格式: search-ms:query=<搜索>&crumb=location:<路径>
            search_url = f'search-ms:query={search_query}&crumb=location:{normalized_path}'
            
            # 使用 os.startfile 打开（与 js2jd_convert_controller 相同方法）
            os.startfile(search_url)
            return True
            
        except Exception as e:
            return False

    def search_files(self):
        """获取选中要素的 file_name 字段值，在资源管理器中自动搜索"""
        layer = self.iface.activeLayer()
        if layer is None:
            QMessageBox.critical(None, "错误", "请先选择一个图层")
            return

        selected_features = layer.selectedFeatures()
        if not selected_features:
            QMessageBox.critical(None, "错误", "请先在图层中选中要素")
            return

        field_names = {field.name().upper() for field in layer.fields()}
        if "FILE_NAME" not in field_names:
            QMessageBox.critical(None, "字段缺失", "当前图层缺少 'FILE_NAME' 字段")
            return

        file_name_field = next(f.name() for f in layer.fields() if f.name().upper() == "FILE_NAME")

        file_names = []
        for feat in selected_features:
            value = feat[file_name_field]
            if value is not None and str(value).strip():
                file_names.append(str(value).strip())

        if not file_names:
            QMessageBox.warning(None, "无数据", "选中的要素没有有效的 file_name 值")
            return

        folder = self._get_layer_folder(layer)

        if not os.path.exists(folder):
            QMessageBox.critical(None, "错误", f"无法找到文件夹：{folder}")
            return

        search_patterns = []
        for name in file_names:
            key = self._extract_key_pattern(name)
            search_patterns.append(key)

        if len(search_patterns) == 1:
            search_query = search_patterns[0]
        else:
            search_query = " OR ".join(search_patterns)

        success = self._open_explorer_search(folder, search_query)

        if success:
            self.iface.messageBar().pushMessage(
                "文件名搜索",
                f"已在资源管理器中搜索 {len(file_names)} 个文件",
                Qgis.Success,
                duration=5
            )
        else:
            try:
                subprocess.Popen(['explorer.exe', folder])
                self.iface.messageBar().pushMessage(
                    "文件名搜索",
                    f"已打开文件夹，请手动搜索：{search_query}",
                    Qgis.Warning,
                    duration=8
                )
            except Exception as e:
                QMessageBox.critical(None, "错误", f"无法打开资源管理器：{str(e)}")
