# -*- coding: utf-8 -*-
"""
文件名搜索工具
功能：选中 .shp 图层中的要素，用 Windows 资源管理器搜索这些要素的 file_name 字段值对应的文件
"""
from qgis.PyQt.QtWidgets import QMessageBox, QApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import Qgis
import os
import subprocess


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

    def search_files(self):
        """获取选中要素的 file_name 字段值，用资源管理器搜索"""
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

        search_text = " ".join(file_names)
        QApplication.clipboard().setText(search_text)

        try:
            subprocess.Popen(['explorer.exe', folder])
            
            msg = f"已打开文件夹并复制 {len(file_names)} 个文件名到剪贴板\n\n"
            msg += "操作步骤：\n"
            msg += "1. 在资源管理器右上角搜索框点击\n"
            msg += "2. 按 Ctrl+V 粘贴文件名\n"
            msg += "3. 按回车搜索\n\n"
            msg += f"文件名: {search_text[:100]}" + ("..." if len(search_text) > 100 else "")
            
            QMessageBox.information(
                None,
                "文件名搜索",
                msg
            )
        except Exception as e:
            QMessageBox.critical(None, "错误", f"无法打开资源管理器：{str(e)}")
