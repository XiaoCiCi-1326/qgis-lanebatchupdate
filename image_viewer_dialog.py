# -*- coding: utf-8 -*-
"""惯导照片查看窗口 - 简化版

核心改进：
1. 移除 controller 依赖，只提供 load_image() 方法
2. 窗口复用：始终只有一个实例，切换照片时调用 load_image()
3. 支持滚轮缩放、拖动
4. 位置记忆（QSettings）
"""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import QPoint, QSettings, Qt, pyqtSignal
from qgis.PyQt.QtGui import QKeySequence, QMouseEvent, QPainter, QPixmap, QWheelEvent
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QShortcut,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QApplication,
)


GEOMETRY_KEY = "lane_batch_update/image_viewer/geometry"


class _ImageCanvas(QWidget):
    """自绘图片画布：支持无滚动条的拖动与鼠标锚点缩放。"""

    scale_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._scaled_pixmap = QPixmap()
        self._scale = 1.0
        self._offset = QPoint()
        self._drag_pos = None
        self._placeholder_text = "未加载图片"
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)

    def set_pixmap(self, pixmap, scale=1.0):
        self._pixmap = pixmap
        self._placeholder_text = ""
        self._set_scale(scale)
        self._center_image()

    def set_placeholder(self, text):
        self._pixmap = QPixmap()
        self._scaled_pixmap = QPixmap()
        self._placeholder_text = text
        self._offset = QPoint()
        self.update()

    def reset_scale(self):
        self._set_scale(1.0)
        self._center_image()

    def _fit_scale(self, max_size=None):
        if self._pixmap.isNull():
            return 1.0
        size = max_size or self.size()
        available_width = max(1, size.width() - 20)
        available_height = max(1, size.height() - 20)
        return min(available_width / self._pixmap.width(), available_height / self._pixmap.height(), 1.0)

    def fit_to_window(self, max_size=None):
        self._set_scale(self._fit_scale(max_size))
        self._center_image()

    def _set_scale(self, scale, repaint=True):
        self._scale = max(0.05, min(scale, 10.0))
        if not self._pixmap.isNull():
            width = max(1, int(self._pixmap.width() * self._scale))
            height = max(1, int(self._pixmap.height() * self._scale))
            self._scaled_pixmap = self._pixmap.scaled(
                width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        if repaint:
            self.scale_changed.emit(self._scale)
            self.update()

    def _center_image(self):
        if not self._scaled_pixmap.isNull():
            self._offset = QPoint(
                (self.width() - self._scaled_pixmap.width()) // 2,
                (self.height() - self._scaled_pixmap.height()) // 2,
            )
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        if self._scaled_pixmap.isNull():
            painter.setPen(Qt.white)
            painter.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self._placeholder_text)
        else:
            painter.drawPixmap(self._offset, self._scaled_pixmap)

    def resizeEvent(self, event):
        if not self._scaled_pixmap.isNull() and self._drag_pos is None:
            self._center_image()
        super().resizeEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and not self._pixmap.isNull():
            self._drag_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos is not None:
            current = event.pos()
            self._offset += current - self._drag_pos
            self._drag_pos = current
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._drag_pos = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        if self._pixmap.isNull():
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        anchor = event.pos()
        image_x = (anchor.x() - self._offset.x()) / self._scale
        image_y = (anchor.y() - self._offset.y()) / self._scale
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._set_scale(self._scale * factor, repaint=False)
        self._offset = QPoint(
            int(anchor.x() - image_x * self._scale),
            int(anchor.y() - image_y * self._scale),
        )
        self.scale_changed.emit(self._scale)
        self.update()
        event.accept()


class ImageViewerDialog(QDialog):
    """照片查看窗口 - 独立窗口"""

    # 信号：切换到面板模式
    switch_to_dock_mode = pyqtSignal()

    def __init__(self, parent=None):
        # parent=None 使窗口独立
        super().__init__(parent)
        self.current_image_path = None
        self._previous_callback = None
        self._next_callback = None
        self._shortcuts_enabled = False
        self._is_always_on_top = False

        self.setWindowTitle("惯导照片查看")
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.resize(900, 700)
        self._setup_ui()
        self._restore_geometry()
        self._prev_shortcut = QShortcut(QKeySequence(","), self)
        self._next_shortcut = QShortcut(QKeySequence("."), self)
        self._prev_shortcut.setContext(Qt.WindowShortcut)
        self._next_shortcut.setContext(Qt.WindowShortcut)
        self._prev_shortcut.setEnabled(False)
        self._next_shortcut.setEnabled(False)
        self._prev_shortcut.activated.connect(self._show_previous)
        self._next_shortcut.activated.connect(self._show_next)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 顶部信息条
        info_row = QHBoxLayout()
        self.info_label = QLabel("未加载图片")
        self.info_label.setStyleSheet(
            "color: #F8FAFC; background: #0F172A; padding: 6px; border-radius: 4px;"
        )
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_row.addWidget(self.info_label, 1)

        self.scale_label = QLabel("100%")
        self.scale_label.setMinimumWidth(60)
        self.scale_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.scale_label.setStyleSheet(
            "color: #F8FAFC; background: #0F172A; padding: 6px; border-radius: 4px;"
        )
        info_row.addWidget(self.scale_label)
        layout.addLayout(info_row)

        # 中间图片区
        self.image_canvas = _ImageCanvas(self)
        self.image_canvas.scale_changed.connect(self._update_scale_label)
        layout.addWidget(self.image_canvas, 1)

        # 底部按钮
        btn_row = QHBoxLayout()
        self.btn_fit = QPushButton("适应窗口")
        self.btn_actual = QPushButton("原始大小")

        # 置顶按钮
        self.btn_pin = QPushButton("📌 置顶")
        self.btn_pin.setToolTip("窗口置顶显示")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setStyleSheet(
            "QPushButton { background: #0F172A; color: #F8FAFC; "
            "border: 1px solid #4c9b91; padding: 6px 12px; border-radius: 4px; }"
            "QPushButton:hover { background: #286b62; }"
            "QPushButton:checked { background: #4c9b91; border-color: #7DD3C0; }"
        )
        self.btn_pin.clicked.connect(self._toggle_always_on_top)

        # 切换到面板模式按钮
        self.btn_switch_dock = QPushButton("📋 面板模式")
        self.btn_switch_dock.setToolTip("切换到停靠面板模式")
        self.btn_switch_dock.setStyleSheet(
            "QPushButton { background: #0F172A; color: #F8FAFC; "
            "border: 1px solid #4c9b91; padding: 6px 12px; border-radius: 4px; }"
            "QPushButton:hover { background: #286b62; }"
        )
        self.btn_switch_dock.clicked.connect(self._on_switch_to_dock)

        self.btn_close = QPushButton("关闭")

        for b in (self.btn_fit, self.btn_actual, self.btn_pin, self.btn_switch_dock):
            b.setStyleSheet(
                "QPushButton { background: #0F172A; color: #F8FAFC; "
                "border: 1px solid #4c9b91; padding: 6px 12px; border-radius: 4px; }"
                "QPushButton:hover { background: #286b62; }"
            )
            btn_row.addWidget(b)

        btn_row.addStretch(1)

        self.btn_close.setStyleSheet(
            "QPushButton { background: #d45151; color: #fff; "
            "border: none; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background: #c13b3b; }"
        )
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        self.btn_fit.clicked.connect(self._on_fit_clicked)
        self.btn_actual.clicked.connect(self._on_actual_clicked)
        self.btn_close.clicked.connect(self.close)

        # 主窗口样式
        self.setStyleSheet("QDialog { background: #0B0E14; }")

    def _toggle_always_on_top(self, checked):
        """切换窗口置顶状态"""
        self._is_always_on_top = checked
        if checked:
            self.setWindowFlags(
                self.windowFlags() | Qt.WindowStaysOnTopHint
            )
            self.btn_pin.setText("📌 取消置顶")
        else:
            self.setWindowFlags(
                self.windowFlags() & ~Qt.WindowStaysOnTopHint
            )
            self.btn_pin.setText("📌 置顶")
        self.show()

    def _on_switch_to_dock(self):
        """切换到面板模式"""
        self.switch_to_dock_mode.emit()

    def set_navigation_callbacks(self, previous_callback, next_callback):
        """设置仅供独立照片窗口使用的导航回调。"""
        self._previous_callback = previous_callback
        self._next_callback = next_callback

    def enterEvent(self, event):
        self._set_shortcuts_enabled(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_shortcuts_enabled(False)
        super().leaveEvent(event)

    def _set_shortcuts_enabled(self, enabled):
        self._shortcuts_enabled = enabled
        self._prev_shortcut.setEnabled(enabled)
        self._next_shortcut.setEnabled(enabled)

    def _show_previous(self):
        if self._shortcuts_enabled and callable(self._previous_callback):
            self._previous_callback()

    def _show_next(self):
        if self._shortcuts_enabled and callable(self._next_callback):
            self._next_callback()

    def _update_scale_label(self, scale):
        self.scale_label.setText(f"{int(scale * 100)}%")

    # ---------- 对外接口 ----------
    def load_image(self, image_path):
        """加载图片（复用窗口的核心方法）"""
        self.current_image_path = image_path

        if not image_path or not os.path.isfile(image_path):
            self._show_placeholder(f"图片不存在:\n{image_path or '(空路径)'}")
            return

        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self._show_placeholder(f"图片加载失败:\n{image_path}")
            return

        # 根据当前画布尺寸一次性设置图片，避免中间状态触发布局闪烁。
        scale = self.image_canvas._fit_scale(self.image_canvas.size())
        self.image_canvas.set_pixmap(pixmap, scale)

        # 更新标题和信息
        filename = os.path.basename(image_path)
        self.setWindowTitle(f"惯导照片查看 - {filename}")
        self.info_label.setText(f"{image_path}  [{pixmap.width()}x{pixmap.height()}]")

    # ---------- 内部 ----------
    def _show_placeholder(self, text):
        self.image_canvas.set_placeholder(text)
        self.info_label.setText("未加载图片")
        self.scale_label.setText("—")

    def _on_fit_clicked(self):
        self.image_canvas.fit_to_window(self.image_canvas.size())
        scale = self.image_canvas._scale
        self.scale_label.setText(f"{int(scale * 100)}%")

    def _on_actual_clicked(self):
        self.image_canvas.reset_scale()
        self.scale_label.setText("100%")

    # ---------- 窗口记忆 ----------
    def closeEvent(self, event):
        self._save_geometry()
        super().closeEvent(event)

    def _save_geometry(self):
        s = QSettings()
        s.setValue(GEOMETRY_KEY, self.saveGeometry())

    def _restore_geometry(self):
        s = QSettings()
        geom = s.value(GEOMETRY_KEY)
        if geom:
            try:
                self.restoreGeometry(geom)
            except Exception:
                pass
