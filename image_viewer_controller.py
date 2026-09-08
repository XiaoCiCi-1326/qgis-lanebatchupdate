# -*- coding: utf-8 -*-
"""惯导照片查看控制器 - 完全重写版本

核心改进：
1. 窗口复用：viewer_dialog 只创建一次，切换时调用 load_image() 而非重新创建
2. 全局快捷键：QShortcut 绑定到主窗口，在任何情况下都生效
3. 真正的停靠面板：QDockWidget + QLabel 放到 QGIS 右侧
4. 图标加载修复：使用 QIcon(path) 并确保路径正确
5. 完全移除旧工具栏按钮：只保留一个下拉 QToolButton
"""
from __future__ import annotations

import json
import os

from qgis.PyQt.QtCore import QObject, QSettings, Qt
from qgis.PyQt.QtGui import QIcon, QKeySequence, QPixmap
from qgis.PyQt.QtWidgets import (
    QAction, QMessageBox, QToolButton, QMenu, QShortcut,
    QDockWidget, QLabel, QVBoxLayout, QWidget, QPushButton, QHBoxLayout,
    QSizePolicy
)
from qgis.core import Qgis, QgsCoordinateTransform, QgsProject, QgsVectorLayer

from .image_viewer_dialog import ImageViewerDialog, _ImageCanvas
from .image_viewer_pairing_dialog import ImageViewerPairingDialog


PAIRS_KEY = "lane_batch_update/image_viewer/pairs"
PAIRS_VERSION = 1


class ImageViewerController(QObject):
    """照片查看控制器"""

    IMG_FIELD_CANDIDATES = ("IMG", "Image_Name", "PHOTO", "IMAGE", "图片名", "文件名")

    def __init__(self, iface, plugin_dir):
        super().__init__()
        self.iface = iface
        self.plugin_dir = plugin_dir

        # 工具栏按钮（只有一个下拉按钮）
        self.toolbar_button = None
        self.toolbar_action = None

        # 子菜单 actions
        self.pairing_action = None
        self.view_action = None
        self.prev_action = None
        self.next_action = None
        self.dock_action = None
        self._dock_prev_shortcut = None
        self._dock_next_shortcut = None

        # 配对状态
        self.pairs = []
        self.layer_pairs = {}
        self.view_mode = False

        # 导航状态
        self.current_layer = None
        self.current_fid = None
        self.all_fids = []
        self.current_image_path = None

        # 窗口/面板（复用，不重复创建）
        self.pairing_dialog = None
        self.viewer_dialog = None
        self.dock_widget = None
        self.dock_label = None
        self.dock_btn_follow_map = None

        # 显示模式：'window' 或 'dock'
        self.display_mode = 'window'
        self.follow_map_enabled = False

        # 信号连接
        self._layer_connections = {}
        self._load_pairs()

    # ---------- 初始化 ----------
    def initGui(self, actions_master):
        """创建下拉工具栏按钮"""
        parent = self.iface.mainWindow()

        # 创建 5 个 action
        self.pairing_action = QAction(
            self._load_icon("icon_image_pairing.svg"),
            "图层照片配对",
            parent,
        )
        self.pairing_action.triggered.connect(self.open_pairing_dialog)

        self.view_action = QAction(
            self._load_icon("icon_image_viewer.svg"),
            "照片查看模式",
            parent,
        )
        self.view_action.setCheckable(True)
        self.view_action.triggered.connect(self._toggle_view_mode)

        self.prev_action = QAction(
            self._load_icon("icon_image_prev.svg"),
            "上一张 (,)",
            parent,
        )
        self.prev_action.triggered.connect(self.show_prev)

        self.next_action = QAction(
            self._load_icon("icon_image_next.svg"),
            "下一张 (.)",
            parent,
        )
        self.next_action.triggered.connect(self.show_next)

        self.dock_action = QAction(
            self._load_icon("icon_image_dock.svg"),
            "停靠面板模式",
            parent,
        )
        self.dock_action.triggered.connect(self._toggle_dock_mode)

        # 添加到菜单
        for act in [self.pairing_action, self.view_action, self.prev_action,
                    self.next_action, self.dock_action]:
            self.iface.addPluginToVectorMenu("车道处理工具", act)
            actions_master.append(act)

        # 停靠面板没有独立窗口承载快捷键，因此绑定到 QGIS 主窗口。
        self._dock_prev_shortcut = QShortcut(QKeySequence(","), parent)
        self._dock_next_shortcut = QShortcut(QKeySequence("."), parent)
        for shortcut in (self._dock_prev_shortcut, self._dock_next_shortcut):
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.setEnabled(False)
        self._dock_prev_shortcut.activated.connect(self.show_prev)
        self._dock_next_shortcut.activated.connect(self.show_next)

    def add_toolbar_button(self):
        """添加到工具栏（单个下拉按钮）"""
        if self.toolbar_button:
            return

        parent = self.iface.mainWindow()
        toolbar = self.iface.vectorToolBar()
        if toolbar is None:
            return

        # 创建下拉按钮
        self.toolbar_button = QToolButton(parent)
        self.toolbar_button.setIcon(self._load_icon("icon_image_viewer.svg"))
        self.toolbar_button.setToolTip("照片查看器")
        self.toolbar_button.setPopupMode(QToolButton.InstantPopup)

        # 创建下拉菜单
        menu = QMenu(parent)
        menu.addAction(self.pairing_action)
        menu.addAction(self.view_action)
        menu.addSeparator()
        menu.addAction(self.prev_action)
        menu.addAction(self.next_action)
        menu.addSeparator()
        menu.addAction(self.dock_action)

        self.toolbar_button.setMenu(menu)

        # 添加到工具栏
        self.toolbar_action = toolbar.addWidget(self.toolbar_button)

    def remove_toolbar_button(self):
        """从工具栏移除"""
        if self.toolbar_action:
            toolbar = self.iface.vectorToolBar()
            if toolbar is not None:
                toolbar.removeAction(self.toolbar_action)
            self.toolbar_action = None
        if self.toolbar_button:
            self.toolbar_button.deleteLater()
            self.toolbar_button = None

    def unload(self):
        """卸载"""
        # 移除工具栏按钮
        self.remove_toolbar_button()

        # 断开信号
        self._disconnect_all_layers()

        # 移除菜单
        parent = self.iface.mainWindow()
        for act in [self.pairing_action, self.view_action, self.prev_action,
                    self.next_action, self.dock_action]:
            if act:
                self.iface.removePluginVectorMenu("车道处理工具", act)

        # 关闭窗口/面板
        if self.viewer_dialog:
            self.viewer_dialog.close()
            self.viewer_dialog = None
        if self.pairing_dialog:
            self.pairing_dialog.close()
            self.pairing_dialog = None
        if self.dock_widget:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget = None
        for shortcut in (self._dock_prev_shortcut, self._dock_next_shortcut):
            if shortcut:
                shortcut.deleteLater()
        self._dock_prev_shortcut = None
        self._dock_next_shortcut = None

    def _load_icon(self, filename):
        """加载图标"""
        path = os.path.join(self.plugin_dir, filename)
        if os.path.exists(path):
            return QIcon(path)
        return QIcon()

    # ---------- 配对管理 ----------
    def open_pairing_dialog(self):
        """打开配对对话框"""
        if not self.pairing_dialog:
            self.pairing_dialog = ImageViewerPairingDialog(
                self.iface,
                self.pairs,
                self._on_pairs_saved,
            )
        else:
            self.pairing_dialog.refresh_from_project()

        self.pairing_dialog.show()
        self.pairing_dialog.raise_()
        self.pairing_dialog.activateWindow()

    def _on_pairs_saved(self, pairs):
        """保存配对"""
        self.pairs = pairs
        self._build_layer_pairs()
        self._save_pairs()
        self._reconnect_layers()
        QMessageBox.information(
            self.iface.mainWindow(),
            "配对保存",
            f"已保存 {len(self.pairs)} 个图层照片配对",
        )

    def _load_pairs(self):
        """从 QSettings 加载配对"""
        settings = QSettings()
        raw = settings.value(PAIRS_KEY, "")
        if not raw:
            return
        try:
            data = json.loads(raw)
            if data.get("version") == PAIRS_VERSION:
                self.pairs = data.get("pairs", [])
                self._build_layer_pairs()
        except:
            pass

    def _save_pairs(self):
        """保存配对到 QSettings"""
        settings = QSettings()
        data = {"version": PAIRS_VERSION, "pairs": self.pairs}
        settings.setValue(PAIRS_KEY, json.dumps(data, ensure_ascii=False))

    def _build_layer_pairs(self):
        """构建 layer_id -> {img_dir, img_field} 映射"""
        self.layer_pairs = {}
        for p in self.pairs:
            lid = p.get("layer_id")
            if lid:
                self.layer_pairs[lid] = {
                    "img_dir": p.get("img_dir", ""),
                    "img_field": p.get("img_field", "IMG"),
                }

    # ---------- 查看模式 ----------
    def _toggle_view_mode(self):
        """切换查看模式"""
        self.view_mode = self.view_action.isChecked()
        if self.view_mode:
            self._reconnect_layers()
            self.iface.messageBar().pushMessage(
                "照片查看模式",
                "已开启：选中要素会自动显示照片",
                Qgis.Info,
                3,
            )
        else:
            self._disconnect_all_layers()
            self.iface.messageBar().pushMessage(
                "照片查看模式",
                "已关闭",
                Qgis.Info,
                2,
            )

    def _reconnect_layers(self):
        """重新连接所有已配对图层的 selectionChanged 信号"""
        self._disconnect_all_layers()
        if not self.view_mode:
            return

        for layer_id in self.layer_pairs.keys():
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer and isinstance(layer, QgsVectorLayer):
                conn = layer.selectionChanged.connect(
                    lambda selected, deselected, clear, lyr=layer: self._on_selection_changed(lyr)
                )
                self._layer_connections[layer_id] = conn

    def _disconnect_all_layers(self):
        """断开所有图层信号"""
        for layer_id, conn in self._layer_connections.items():
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer:
                try:
                    layer.selectionChanged.disconnect(conn)
                except:
                    pass
        self._layer_connections.clear()

    def _on_selection_changed(self, layer):
        """选中要素时触发"""
        if not self.view_mode:
            return

        selected_fids = layer.selectedFeatureIds()
        if not selected_fids:
            return

        # 更新导航状态
        self.current_layer = layer
        self.all_fids = sorted([f.id() for f in layer.getFeatures()])
        self.current_fid = selected_fids[0]  # 只显示第一个

        # 显示照片，并在开启画布跟随时定位选中要素。
        self._show_photo(layer, self.current_fid)
        self._follow_feature_on_map(layer, self.current_fid)

    def _follow_feature_on_map(self, layer, fid):
        """仅移动地图中心到照片要素，保持当前画布比例尺。"""
        if not self.follow_map_enabled:
            return
        feature = layer.getFeature(fid)
        if not feature.isValid() or feature.geometry().isEmpty():
            return
        canvas = self.iface.mapCanvas()
        center = feature.geometry().boundingBox().center()
        if layer.crs() != canvas.mapSettings().destinationCrs():
            transform = QgsCoordinateTransform(
                layer.crs(), canvas.mapSettings().destinationCrs(), QgsProject.instance()
            )
            center = transform.transform(center)
        canvas.setCenter(center)
        canvas.refresh()

    def _set_follow_map_enabled(self, enabled):
        """更新两个显示模式共用的画布跟随开关。"""
        self.follow_map_enabled = enabled
        if self.viewer_dialog:
            self.viewer_dialog.set_follow_map_enabled(enabled)
        if self.dock_btn_follow_map:
            self.dock_btn_follow_map.blockSignals(True)
            self.dock_btn_follow_map.setChecked(enabled)
            self.dock_btn_follow_map.blockSignals(False)
        if enabled and self.current_layer and self.current_fid is not None:
            self._follow_feature_on_map(self.current_layer, self.current_fid)

    # ---------- 照片显示 ----------
    def _show_photo(self, layer, fid):
        """显示照片（复用窗口/面板）"""
        if layer.id() not in self.layer_pairs:
            return

        pair = self.layer_pairs[layer.id()]
        img_dir = pair["img_dir"]
        img_field = pair["img_field"]

        feat = layer.getFeature(fid)
        if not feat.isValid():
            return

        img_name = feat.attribute(img_field)
        if not img_name:
            return

        # 补齐扩展名
        if not os.path.splitext(str(img_name))[1]:
            img_name = str(img_name) + ".jpg"

        img_path = os.path.join(img_dir, str(img_name))
        if not os.path.exists(img_path):
            return

        # 根据模式显示
        self.current_image_path = img_path
        if self.display_mode == 'dock':
            self._show_in_dock(img_path)
        else:
            self._show_in_window(img_path)

    def _show_in_window(self, img_path):
        """独立窗口显示（复用）"""
        if not self.viewer_dialog:
            self.viewer_dialog = ImageViewerDialog(None)  # 独立窗口
            self.viewer_dialog.set_navigation_callbacks(self.show_prev, self.show_next)
            self.viewer_dialog.switch_to_dock_mode.connect(self._switch_to_dock_mode)
            self.viewer_dialog.follow_map_changed.connect(self._set_follow_map_enabled)
            self.viewer_dialog.set_follow_map_enabled(self.follow_map_enabled)

        was_visible = self.viewer_dialog.isVisible()
        self.viewer_dialog.load_image(img_path)
        if not was_visible:
            # 仅首次显示时激活窗口；切换照片时不改变窗口状态，避免 Windows 闪烁。
            self.viewer_dialog.show()
            self.viewer_dialog.raise_()
            self.viewer_dialog.activateWindow()

    def _switch_to_dock_mode(self):
        """从独立窗口切换到面板模式"""
        if self.display_mode != 'dock':
            self._toggle_dock_mode()

    def _show_in_dock(self, img_path):
        """停靠面板显示（支持滚轮缩放和拖动）"""
        if not self.dock_widget:
            self._create_dock_widget()

        pixmap = QPixmap(img_path)
        if not pixmap.isNull():
            self.dock_widget.show()
            # 使用 ImageCanvas 显示图片，并根据面板尺寸自动适应
            self.dock_canvas.set_pixmap(pixmap, 1.0)
            # 适应窗口大小
            self.dock_canvas.fit_to_window()
            self.dock_widget.show()

    def _create_dock_widget(self):
        """创建停靠面板"""
        self.dock_widget = QDockWidget("照片查看", self.iface.mainWindow())
        self.dock_widget.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)

        # 创建内容 widget
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)

        # 图片显示区域 - 使用 ImageCanvas 支持滚轮缩放和拖动
        self.dock_canvas = _ImageCanvas()
        self.dock_canvas.setMinimumSize(200, 200)
        self.dock_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.dock_canvas.setStyleSheet("background: #1E293B; border: 1px solid #4c9b91;")
        layout.addWidget(self.dock_canvas, 1)

        # 缩放信息和切换按钮行
        info_row = QHBoxLayout()
        self.dock_scale_label = QLabel("100%")
        self.dock_scale_label.setMinimumWidth(50)
        self.dock_scale_label.setAlignment(Qt.AlignCenter)
        self.dock_scale_label.setStyleSheet(
            "color: #F8FAFC; background: #0F172A; padding: 4px; border-radius: 4px;"
        )
        self.dock_canvas.scale_changed.connect(
            lambda scale: self.dock_scale_label.setText(f"{int(scale * 100)}%")
        )
        info_row.addWidget(self.dock_scale_label)

        self.dock_btn_fit = QPushButton("适应窗口")
        self.dock_btn_fit.setStyleSheet(
            "QPushButton { background: #0F172A; color: #F8FAFC; "
            "border: 1px solid #4c9b91; padding: 4px 8px; border-radius: 4px; }"
            "QPushButton:hover { background: #286b62; }"
        )
        self.dock_btn_fit.clicked.connect(self._on_dock_fit_clicked)
        info_row.addWidget(self.dock_btn_fit)

        self.dock_btn_follow_map = QPushButton("画布跟随")
        self.dock_btn_follow_map.setToolTip("跟随当前照片要素移动地图，保持当前比例尺")
        self.dock_btn_follow_map.setCheckable(True)
        self.dock_btn_follow_map.setChecked(self.follow_map_enabled)
        self.dock_btn_follow_map.setStyleSheet(
            "QPushButton { background: #0F172A; color: #F8FAFC; "
            "border: 1px solid #4c9b91; padding: 4px 8px; border-radius: 4px; }"
            "QPushButton:hover { background: #286b62; }"
            "QPushButton:checked { background: #4c9b91; border-color: #7DD3C0; }"
        )
        self.dock_btn_follow_map.toggled.connect(self._set_follow_map_enabled)
        info_row.addWidget(self.dock_btn_follow_map)

        info_row.addStretch(1)

        # 切换到独立窗口按钮
        self.dock_btn_switch_window = QPushButton("🪟 独立窗口")
        self.dock_btn_switch_window.setToolTip("切换到独立窗口模式")
        self.dock_btn_switch_window.setStyleSheet(
            "QPushButton { background: #0F172A; color: #F8FAFC; "
            "border: 1px solid #4c9b91; padding: 4px 8px; border-radius: 4px; }"
            "QPushButton:hover { background: #286b62; }"
        )
        self.dock_btn_switch_window.clicked.connect(self._switch_to_window_mode)
        info_row.addWidget(self.dock_btn_switch_window)

        layout.addLayout(info_row)

        # 导航按钮
        btn_layout = QHBoxLayout()
        prev_btn = QPushButton("◀ 上一张 (,)")
        prev_btn.setStyleSheet(
            "QPushButton { background: #0F172A; color: #F8FAFC; "
            "border: 1px solid #4c9b91; padding: 6px 12px; border-radius: 4px; }"
            "QPushButton:hover { background: #286b62; }"
        )
        prev_btn.clicked.connect(self.show_prev)
        next_btn = QPushButton("下一张 (.) ▶")
        next_btn.setStyleSheet(
            "QPushButton { background: #0F172A; color: #F8FAFC; "
            "border: 1px solid #4c9b91; padding: 6px 12px; border-radius: 4px; }"
            "QPushButton:hover { background: #286b62; }"
        )
        next_btn.clicked.connect(self.show_next)
        btn_layout.addWidget(prev_btn)
        btn_layout.addWidget(next_btn)
        layout.addLayout(btn_layout)

        self.dock_widget.setWidget(content)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)

    def _on_dock_fit_clicked(self):
        """面板适应窗口按钮"""
        self.dock_canvas.fit_to_window()
        self.dock_scale_label.setText(f"{int(self.dock_canvas._scale * 100)}%")

    def _switch_to_window_mode(self):
        """从面板模式切换到独立窗口模式"""
        if self.display_mode != 'window':
            self._toggle_dock_mode()

    def _set_dock_shortcuts_enabled(self, enabled):
        for shortcut in (self._dock_prev_shortcut, self._dock_next_shortcut):
            if shortcut:
                shortcut.setEnabled(enabled)

    def _toggle_dock_mode(self):
        """在独立窗口和停靠面板之间直接切换当前照片。"""
        if self.display_mode == 'window':
            self.display_mode = 'dock'
            self._set_dock_shortcuts_enabled(True)
            if self.viewer_dialog:
                self.viewer_dialog.hide()
            if self.current_image_path:
                self._show_in_dock(self.current_image_path)
        else:
            self.display_mode = 'window'
            self._set_dock_shortcuts_enabled(False)
            if self.dock_widget:
                self.dock_widget.hide()
            if self.current_image_path:
                self._show_in_window(self.current_image_path)

    # ---------- 导航 ----------
    def show_prev(self):
        """上一张（在整个图层中跳转）"""
        if not self.current_layer or not self.all_fids or self.current_fid is None:
            return

        if self.current_fid not in self.all_fids:
            return

        idx = self.all_fids.index(self.current_fid)
        new_idx = (idx - 1) % len(self.all_fids)
        self.current_fid = self.all_fids[new_idx]

        # 选中并显示
        self.current_layer.selectByIds([self.current_fid])
        self._show_photo(self.current_layer, self.current_fid)

    def show_next(self):
        """下一张（在整个图层中跳转）"""
        if not self.current_layer or not self.all_fids or self.current_fid is None:
            return

        if self.current_fid not in self.all_fids:
            return

        idx = self.all_fids.index(self.current_fid)
        new_idx = (idx + 1) % len(self.all_fids)
        self.current_fid = self.all_fids[new_idx]

        # 选中并显示
        self.current_layer.selectByIds([self.current_fid])
        self._show_photo(self.current_layer, self.current_fid)
