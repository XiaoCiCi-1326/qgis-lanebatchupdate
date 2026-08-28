# -*- coding: utf-8 -*-
"""
文件名搜索工具
功能：选中 .shp 图层中的要素，用 Windows 资源管理器自动搜索这些要素的 file_name 字段值对应的文件
"""
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtGui import QIcon
from qgis.core import Qgis
import os
import subprocess
import tempfile


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

        search_query = " OR ".join(f'"{name}"' for name in file_names)

        ps_script = f'''
$folder = "{folder.replace(chr(92), chr(92)*2)}"
$searchQuery = @"
{search_query}
"@

Start-Process explorer.exe -ArgumentList "search-ms:query=$searchQuery&crumb=location:$folder"
'''

        try:
            temp_ps = tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False, encoding='utf-8')
            temp_ps.write(ps_script)
            temp_ps.close()

            subprocess.Popen(
                ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', temp_ps.name],
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            try:
                os.unlink(temp_ps.name)
            except:
                pass

            self.iface.messageBar().pushMessage(
                "文件名搜索",
                f"已在资源管理器中自动搜索 {len(file_names)} 个文件名",
                Qgis.Info,
                duration=5
            )
        except Exception as e:
            try:
                subprocess.Popen(['explorer.exe', folder])
                self.iface.messageBar().pushMessage(
                    "文件名搜索",
                    f"已打开文件夹 {os.path.basename(folder)}（自动搜索失败，请手动搜索）",
                    Qgis.Warning,
                    duration=5
                )
            except Exception as e2:
                QMessageBox.critical(None, "错误", f"无法打开资源管理器：{str(e2)}")
