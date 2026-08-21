# -*- coding: utf-8 -*-
"""惯导图层地图跟随：选择/前后切换要素时保持比例尺并移动地图。"""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import Qgis, QgsCoordinateTransform, QgsProject, QgsVectorLayer


class InertialFollowController(QObject):
    """让当前惯导图层的选择变化驱动地图中心移动。"""

    def __init__(self, iface, plugin_dir):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.action = None
        self.layer = None
        self.feature_ids = []
        self._changing_selection = False

    def initGui(self, actions_master):
        icon_path = os.path.join(self.plugin_dir, "icon_inertial_follow.svg")
        self.action = QAction(QIcon(icon_path), "惯导地图跟随", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip("跟随惯导要素选择移动地图，保持当前比例尺；, / . 切换前后要素")
        self.action.triggered.connect(self.toggle)
        # 不直接添加到工具栏，由主文件根据 toolbar_mode 控制
        # self.iface.addVectorToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu("车道处理工具", self.action)
        actions_master.append(self.action)

    def unload(self):
        self._disconnect_layer()
        canvas = self.iface.mapCanvas()
        canvas.removeEventFilter(self)
        self.iface.mainWindow().removeEventFilter(self)
        if self.action is not None:
            self.iface.removeVectorToolBarIcon(self.action)
            self.iface.removePluginFromVectorMenu("车道处理工具", self.action)
        self.action = None
        self.layer = None
        self.feature_ids = []

    def toggle(self, checked):
        if checked:
            if not self._connect_active_layer():
                self.action.blockSignals(True)
                self.action.setChecked(False)
                self.action.blockSignals(False)
                return
            self.iface.mapCanvas().installEventFilter(self)
            self.iface.mainWindow().installEventFilter(self)
            self._follow_selected()
            self.iface.messageBar().pushMessage(
                "车道工具",
                "惯导地图跟随已开启：选择要素或使用 , / . 切换惯导",
                level=Qgis.Info,
                duration=5,
            )
        else:
            self.iface.mapCanvas().removeEventFilter(self)
            self.iface.mainWindow().removeEventFilter(self)
            self._disconnect_layer()
            self.iface.messageBar().pushMessage("车道工具", "惯导地图跟随已关闭", duration=3)

    def _connect_active_layer(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            QMessageBox.warning(self.iface.mainWindow(), "图层类型不支持", "请先激活惯导矢量图层。")
            return False
        if layer.featureCount() == 0:
            QMessageBox.warning(self.iface.mainWindow(), "图层为空", "当前惯导图层没有可跟随的要素。")
            return False

        self._disconnect_layer()
        self.layer = layer
        self.feature_ids = [feature.id() for feature in layer.getFeatures()]
        layer.selectionChanged.connect(self._on_selection_changed)
        return True

    def _disconnect_layer(self):
        if self.layer is not None:
            try:
                self.layer.selectionChanged.disconnect(self._on_selection_changed)
            except (TypeError, RuntimeError):
                pass
        self.layer = None
        self.feature_ids = []

    def _on_selection_changed(self, selected, deselected, clear_and_select):
        if not self._changing_selection:
            self._follow_selected()

    def _follow_selected(self):
        if self.layer is None:
            return
        selected = self.layer.selectedFeatureIds()
        if not selected:
            return
        feature = self.layer.getFeature(selected[-1])
        if not feature.isValid() or feature.geometry().isEmpty():
            return
        # setCenter 只改变中心，不改变当前画布比例尺。
        center = feature.geometry().boundingBox().center()
        canvas = self.iface.mapCanvas()
        if self.layer.crs() != canvas.mapSettings().destinationCrs():
            transform = QgsCoordinateTransform(
                self.layer.crs(), canvas.mapSettings().destinationCrs(), QgsProject.instance()
            )
            center = transform.transform(center)
        canvas.setCenter(center)
        canvas.refresh()

    def _move_selection(self, step):
        if self.layer is None or not self.feature_ids:
            return
        selected = self.layer.selectedFeatureIds()
        current_id = selected[-1] if selected else self.feature_ids[0]
        try:
            current_index = self.feature_ids.index(current_id)
        except ValueError:
            current_index = 0
        next_index = (current_index + step) % len(self.feature_ids)
        next_id = self.feature_ids[next_index]

        self._changing_selection = True
        try:
            self.layer.selectByIds([next_id])
        finally:
            self._changing_selection = False
        self._follow_selected()

    def eventFilter(self, watched, event):
        if watched in (self.iface.mapCanvas(), self.iface.mainWindow()) and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Comma:
                self._move_selection(-1)
                return True
            if event.key() == Qt.Key_Period:
                self._move_selection(1)
                return True
        return super().eventFilter(watched, event)
