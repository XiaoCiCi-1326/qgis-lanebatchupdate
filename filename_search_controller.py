# -*- coding: utf-8 -*-
"""
文件名搜索工具
功能：选中 .shp 图层中的要素，自动搜索这些要素的 file_name 字段值对应的文件并在资源管理器中选中
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
        """提取文件名中的关键数字模式，如 -164_-212"""
        match = re.search(r'[-_\d]+', filename)
        if match:
            return match.group(0)
        return filename

    def _search_files_in_folder(self, folder, file_names):
        """在文件夹中模糊搜索文件"""
        found_files = []
        
        search_patterns = []
        for name in file_names:
            key = self._extract_key_pattern(name)
            search_patterns.append(key.lower())
        
        for root, dirs, files in os.walk(folder):
            for file in files:
                file_lower = file.lower()
                for pattern in search_patterns:
                    if pattern in file_lower:
                        full_path = os.path.join(root, file)
                        if full_path not in found_files:
                            found_files.append(full_path)
                        break
        
        return found_files

    def search_files(self):
        """获取选中要素的 file_name 字段值，自动搜索文件"""
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

        self.iface.messageBar().pushMessage(
            "文件名搜索",
            f"正在模糊搜索 {len(file_names)} 个文件...",
            Qgis.Info,
            duration=3
        )

        found_files = self._search_files_in_folder(folder, file_names)

        if found_files:
            if len(found_files) == 1:
                try:
                    subprocess.Popen(['explorer.exe', '/select,', found_files[0]])
                    self.iface.messageBar().pushMessage(
                        "文件名搜索",
                        f"找到 1 个文件并已在资源管理器中选中",
                        Qgis.Success,
                        duration=5
                    )
                except Exception as e:
                    QMessageBox.critical(None, "错误", f"无法打开资源管理器：{str(e)}")
            else:
                try:
                    result_folder = os.path.dirname(found_files[0])
                    subprocess.Popen(['explorer.exe', '/select,', found_files[0]])
                    
                    msg = f"找到 {len(found_files)} 个文件\n\n"
                    msg += "已在资源管理器中打开第一个文件所在位置：\n\n"
                    for i, f in enumerate(found_files[:10], 1):
                        msg += f"{i}. {os.path.basename(f)}\n"
                    if len(found_files) > 10:
                        msg += f"\n... 还有 {len(found_files) - 10} 个文件"
                    
                    QMessageBox.information(None, "搜索结果", msg)
                except Exception as e:
                    QMessageBox.critical(None, "错误", f"无法打开资源管理器：{str(e)}")
        else:
            msg = f"在文件夹中未找到匹配的文件\n\n"
            msg += f"搜索位置: {folder}\n\n"
            msg += "搜索的文件名:\n"
            for name in file_names[:10]:
                msg += f"- {name}\n"
            if len(file_names) > 10:
                msg += f"... 还有 {len(file_names) - 10} 个"
            
            QMessageBox.warning(None, "未找到文件", msg)
