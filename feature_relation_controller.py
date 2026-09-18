# -*- coding: utf-8 -*-
"""
要素关联管理器
支持 LANE 图层字段关联到其他图层要素的高亮、选择、赋值
"""
import os
from qgis.PyQt.QtCore import QObject, pyqtSignal, Qt, QSettings, QTimer
from qgis.PyQt.QtWidgets import (
    QAction, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QDialogButtonBox,
    QCheckBox, QGroupBox, QColorDialog, QGridLayout, QMenu, QToolButton,
    QRadioButton, QFrame, QSpinBox, QScrollArea, QWidget
)
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.core import (
    QgsProject,
    QgsFeatureRequest,
    QgsExpression,
    QgsVectorLayer,
)

# 默认颜色配置（模块级常量）
DEFAULT_FIELD_COLORS = {
    'BDY_LEFT': QColor(255, 0, 0, 200),   # 红色
    'BDY_RIGHT': QColor(0, 255, 0, 200),  # 绿色
    'RBDY_L': QColor(255, 128, 0, 200),   # 橙色
    'RBDY_R': QColor(0, 255, 255, 200),   # 青色
    'LEFT_FWD': QColor(255, 255, 0, 200), # 黄色
    'RIGHT_FWD': QColor(255, 0, 255, 200),# 紫色
    'LEFT_RVS': QColor(128, 255, 0, 200), # 黄绿色
    'RIGHT_RVS': QColor(128, 0, 255, 200),# 紫蓝色
    'SIGNALS': QColor(0, 128, 255, 200),  # 天蓝色
}


class FeatureRelationController(QObject):
    """要素关联控制器"""
    
    # 字段到图层的映射规则
    FIELD_LAYER_MAP = {
        'BDY_LEFT': 'BOUNDARY',
        'BDY_RIGHT': 'BOUNDARY',
        'RBDY_L': 'BOUNDARY',
        'RBDY_R': 'BOUNDARY',
        'LEFT_FWD': 'LANE',
        'RIGHT_FWD': 'LANE',
        'LEFT_RVS': 'LANE',
        'RIGHT_RVS': 'LANE',
        'SIGNALS': 'SIGNAL',
    }
    
    status_changed = pyqtSignal(str)
    
    def __init__(self, iface, plugin_dir=None):
        super().__init__()
        self.iface = iface
        self.plugin_dir = plugin_dir or os.path.dirname(__file__)
        self.project = QgsProject.instance()
        self.auto_mode_enabled = False
        self.auto_mode_config = None  # 存储自动模式的配置
        self.lane_layer_connection = None
        self.actions = []
        self.auto_mode_action = None
        self.toolbar_button = None
        self.toolbar_action = None
        self._is_processing = False  # 递归锁，防止无限循环
        
        # 加载保存的配置
        self._load_config()
    
    def initGui(self, actions_master):
        # 创建工具栏按钮
        self._create_toolbar_button()
        
        # 将工具按钮添加到工具栏
        toolbar = self.iface.vectorToolBar()
        if toolbar:
            self.toolbar_action = toolbar.addWidget(self.toolbar_button)
        
        # 只将 QAction 添加到 actions_master，不添加 QToolButton
        # self.actions.append(tool_button)  # 移除这行
        # actions_master.append(tool_button)  # 移除这行
        
        # 关联赋值按钮（保持不变）
        assign_icon_path = os.path.join(self.plugin_dir, "icon_relation_assign.svg")
        self.assign_action = QAction(QIcon(assign_icon_path), u"关联赋值", self.iface.mainWindow())
        self.assign_action.triggered.connect(self.assign_relation)
        self.iface.addPluginToVectorMenu(u"车道处理工具", self.assign_action)
        self.actions.append(self.assign_action)
        actions_master.append(self.assign_action)
    
    def _create_toolbar_button(self):
        """创建工具栏按钮"""
        # 创建关联高亮&选择的下拉菜单按钮
        icon_path = os.path.join(self.plugin_dir, "icon_relation_highlight.svg")
        
        # 创建工具按钮（支持下拉菜单）
        tool_button = QToolButton()
        tool_button.setIcon(QIcon(icon_path))
        tool_button.setText(u"关联高亮&选择")
        tool_button.setToolTip(u"关联高亮&选择")
        tool_button.setPopupMode(QToolButton.MenuButtonPopup)
        
        # 创建下拉菜单
        menu = QMenu()
        
        # 第一项：自动关联模式（开启/关闭）
        auto_icon_path = os.path.join(self.plugin_dir, "icon_auto_relation.svg")
        self.auto_mode_action = QAction(QIcon(auto_icon_path), u"自动关联模式 (关闭)", self.iface.mainWindow())
        self.auto_mode_action.triggered.connect(self.toggle_auto_mode)
        menu.addAction(self.auto_mode_action)
        
        # 第二项：打开配置面板
        config_icon_path = os.path.join(self.plugin_dir, "icon_relation_config.svg")
        config_action = QAction(QIcon(config_icon_path), u"关联配置", self.iface.mainWindow())
        config_action.triggered.connect(self.open_config_dialog)
        menu.addAction(config_action)
        
        tool_button.setMenu(menu)
        tool_button.setDefaultAction(self.auto_mode_action)
        
        # 保存按钮引用
        self.toolbar_button = tool_button
    
    def unload(self):
        # 断开自动模式连接
        if self.lane_layer_connection:
            try:
                lane_layer = self._get_lane_layer()
                if lane_layer:
                    lane_layer.selectionChanged.disconnect(self.on_lane_selection_changed)
            except:
                pass
            self.lane_layer_connection = None
        
        # 移除工具按钮
        self.remove_toolbar_button()
        
        for action in self.actions:
            try:
                self.iface.removePluginMenu(u"车道处理工具", action)
            except:
                pass
        self.actions = []
    
    def add_toolbar_button(self):
        """添加工具按钮到工具栏"""
        # 如果按钮不存在，重新创建
        if not self.toolbar_button:
            self._create_toolbar_button()
        
        if self.toolbar_button and not self.toolbar_action:
            toolbar = self.iface.vectorToolBar()
            if toolbar:
                self.toolbar_action = toolbar.addWidget(self.toolbar_button)
    
    def remove_toolbar_button(self):
        """从工具栏移除工具按钮"""
        toolbar = self.iface.vectorToolBar()
        if toolbar and self.toolbar_action:
            try:
                toolbar.removeAction(self.toolbar_action)
            except (AttributeError, RuntimeError):
                pass
            self.toolbar_action = None
        
        if self.toolbar_button:
            try:
                self.toolbar_button.deleteLater()
            except (AttributeError, RuntimeError):
                pass
            self.toolbar_button = None
    
    def _save_config(self, config):
        """保存配置到 QSettings"""
        settings = QSettings()
        settings.beginGroup("LaneBatchUpdate/FeatureRelation")
        
        # 保存选中的字段
        if 'enabled_fields' in config:
            settings.setValue("enabled_fields", list(config['enabled_fields']))
        
        # 保存颜色配置
        if 'field_colors' in config:
            for field_name, color in config['field_colors'].items():
                settings.setValue("color_{}".format(field_name), color.name())
        
        # 保存高亮持续时间
        if 'highlight_duration' in config:
            settings.setValue("highlight_duration", config['highlight_duration'])
        
        settings.endGroup()
    
    def _load_config(self):
        """从 QSettings 加载配置"""
        settings = QSettings()
        settings.beginGroup("LaneBatchUpdate/FeatureRelation")
        
        # 加载选中的字段
        enabled_fields = settings.value("enabled_fields", None)
        
        # 加载颜色配置
        field_colors = DEFAULT_FIELD_COLORS.copy()
        for field_name in field_colors.keys():
            color_name = settings.value("color_{}".format(field_name), None)
            if color_name:
                field_colors[field_name] = QColor(color_name)
        
        # 加载高亮持续时间（默认 1000 毫秒）
        highlight_duration = settings.value("highlight_duration", 1000, type=int)
        
        settings.endGroup()
        
        # 构建配置
        if enabled_fields:
            self.auto_mode_config = {
                'enabled_fields': set(enabled_fields),
                'field_colors': field_colors,
                'highlight_duration': highlight_duration
            }
    
    def _get_lane_layer(self):
        for layer in self.project.mapLayers().values():
            if layer.name().upper() == 'LANE':
                return layer
        return None
    
    def _get_target_layer(self, layer_name):
        for layer in self.project.mapLayers().values():
            if layer.name().upper() == layer_name.upper():
                return layer
        return None
    
    def _parse_ids(self, field_value):
        if not field_value or str(field_value).strip().upper() in ('NULL', 'NONE', ''):
            return []
        value_str = str(field_value).strip()
        if not value_str:
            return []
        return [id_str.strip() for id_str in value_str.split('|') if id_str.strip()]
    
    def _get_related_features(self, lane_feature):
        related = {}
        field_names = {f.name().upper(): f.name() for f in lane_feature.fields()}
        
        for field_name_upper, layer_name in self.FIELD_LAYER_MAP.items():
            field_name = field_names.get(field_name_upper)
            if not field_name:
                continue
            
            field_value = lane_feature.attribute(field_name)
            if not field_value or str(field_value).strip().upper() in ('NULL', 'NONE', ''):
                continue
            
            ids = self._parse_ids(field_value)
            if not ids:
                continue
            
            target_layer = self._get_target_layer(layer_name)
            if not target_layer:
                continue
            
            for feature_id in ids:
                expression = '"ID" = \'\''.format(feature_id)
                request = QgsFeatureRequest(QgsExpression(expression))
                
                for feature in target_layer.getFeatures(request):
                    if layer_name not in related:
                        related[layer_name] = []
                    related[layer_name].append((feature.id(), field_name))
                    break
        
        return related
    
    def toggle_auto_mode(self):
        """切换自动关联模式"""
        self.auto_mode_enabled = not self.auto_mode_enabled
        
        if self.auto_mode_enabled:
            # 开启自动模式
            auto_icon_path = os.path.join(self.plugin_dir, "icon_auto_relation.svg")
            self.auto_mode_action.setIcon(QIcon(auto_icon_path))
            self.auto_mode_action.setText(u"自动关联模式 (开启)")
            
            # 连接 LANE 图层的选择变化信号
            lane_layer = self._get_lane_layer()
            if lane_layer:
                if not self.lane_layer_connection:
                    lane_layer.selectionChanged.connect(self.on_lane_selection_changed)
                    self.lane_layer_connection = True
                self.status_changed.emit("✅ 自动关联模式已开启")
            else:
                QMessageBox.warning(None, "错误", "未找到 LANE 图层")
                self.auto_mode_enabled = False
                self.auto_mode_action.setText(u"自动关联模式 (关闭)")
        else:
            # 关闭自动模式
            auto_icon_path = os.path.join(self.plugin_dir, "icon_auto_relation.svg")
            self.auto_mode_action.setIcon(QIcon(auto_icon_path))
            self.auto_mode_action.setText(u"自动关联模式 (关闭)")
            
            # 断开连接
            lane_layer = self._get_lane_layer()
            if lane_layer and self.lane_layer_connection:
                try:
                    lane_layer.selectionChanged.disconnect(self.on_lane_selection_changed)
                except:
                    pass
                self.lane_layer_connection = None
            self.status_changed.emit("⭕ 自动关联模式已关闭")
    
    def on_lane_selection_changed(self):
        """LANE 选择变化时自动高亮和选中关联要素"""
        # 递归锁：防止无限循环
        if self._is_processing:
            return
        
        try:
            if not self.auto_mode_enabled:
                return
            
            lane_layer = self._get_lane_layer()
            if not lane_layer:
                return
            
            lane_features = lane_layer.selectedFeatures()
            
            # 如果没有选中任何要素，清除所有关联图层的选择和高亮
            if not lane_features:
                self._clear_all_related_selections()
                return
            
            # 使用当前配置或默认配置
            if not self.auto_mode_config:
                # 默认配置：所有字段都启用
                self.auto_mode_config = {
                    'enabled_fields': set(self.FIELD_LAYER_MAP.keys()),
                    'field_colors': DEFAULT_FIELD_COLORS.copy(),
                    'highlight_duration': 1000
                }
            
            # 设置递归锁
            self._is_processing = True
            try:
                self._auto_highlight_and_select(lane_features)
            finally:
                # 确保锁被释放
                self._is_processing = False
                
        except Exception as e:
            import traceback
            error_msg = "自动关联触发错误: {}\n{}".format(str(e), traceback.format_exc())
            print(error_msg)
            # 出错时自动关闭自动模式
            self.auto_mode_enabled = False
            self.auto_mode_action.setText(u"自动关联模式 (关闭)")
            self.status_changed.emit("❌ 自动模式出错已关闭: {}".format(str(e)))
            # 释放锁
            self._is_processing = False
    
    def _auto_highlight_and_select(self, lane_features):
        """执行自动高亮和选中"""
        try:
            if not self.auto_mode_config:
                return
            
            # 使用正确的键名：enabled_fields 和 field_colors
            selected_fields = self.auto_mode_config.get('enabled_fields', [])
            if not selected_fields:
                return
            
            field_colors = self.auto_mode_config.get('field_colors', {})
            
            lane_layer = self._get_lane_layer()
            if not lane_layer:
                return
            
            # 获取字段映射
            lane_field_names = {f.name().upper(): f.name() for f in lane_layer.fields()}
            layer_selections = {}
            
            for lane_feature in lane_features:
                if not lane_feature:
                    continue
                    
                for field_upper in selected_fields:
                    if not field_upper:
                        continue
                        
                    field_name = lane_field_names.get(field_upper)
                    if not field_name:
                        continue
                    
                    # 安全获取字段值
                    try:
                        field_value = lane_feature.attribute(field_name)
                    except:
                        continue
                        
                    if not field_value or str(field_value).strip().upper() in ('NULL', 'NONE', ''):
                        continue
                    
                    ids = self._parse_ids(field_value)
                    if not ids:
                        continue
                    
                    layer_name = self.FIELD_LAYER_MAP.get(field_upper)
                    if not layer_name:
                        continue
                    
                    target_layer = self._get_target_layer(layer_name)
                    if not target_layer:
                        continue
                    
                    if layer_name not in layer_selections:
                        layer_selections[layer_name] = {
                            'ids': [], 
                            'color': field_colors.get(field_upper, QColor(255, 0, 0, 200))
                        }
                    
                    # 查找要素
                    for feature_id in ids:
                        try:
                            expression = '"ID" = \'{}\''.format(feature_id)
                            request = QgsFeatureRequest(QgsExpression(expression))
                            for feature in target_layer.getFeatures(request):
                                if feature.id() not in layer_selections[layer_name]['ids']:
                                    layer_selections[layer_name]['ids'].append(feature.id())
                                break
                        except:
                            continue
            
            # 选中要素
            total_selected = 0
            highlight_duration = self.auto_mode_config.get('highlight_duration', 1000)
            
            for layer_name, data in layer_selections.items():
                try:
                    target_layer = self._get_target_layer(layer_name)
                    if target_layer and data.get('ids'):
                        target_layer.selectByIds(data['ids'], QgsVectorLayer.AddToSelection)
                        
                        # 高亮
                        color = data.get('color', QColor(255, 0, 0, 200))
                        
                        if highlight_duration == -1:
                            # 一直高亮（不闪烁）- 使用非常大的持续时间和1次闪烁
                            self.iface.mapCanvas().flashFeatureIds(
                                target_layer,
                                data['ids'],
                                color,
                                color,  # 开始和结束颜色相同，避免闪烁效果
                                flashes=1,
                                duration=999999999  # 近乎永久
                            )
                        else:
                            # 按配置的时间闪烁
                            self.iface.mapCanvas().flashFeatureIds(
                                target_layer,
                                data['ids'],
                                color,
                                QColor(color.red(), color.green(), color.blue(), 100),
                                flashes=2,
                                duration=highlight_duration
                            )
                        total_selected += len(data['ids'])
                except Exception as e:
                    print("高亮图层 {} 时出错: {}".format(layer_name, str(e)))
                    continue
            
            if total_selected > 0:
                self.status_changed.emit("自动关联：已选中并高亮 {} 个要素".format(total_selected))
        except Exception as e:
            import traceback
            error_msg = "自动高亮选中错误: {}\n{}".format(str(e), traceback.format_exc())
            print(error_msg)
            raise
    
    def _clear_all_related_selections(self):
        """清除所有关联图层的选择"""
        try:
            for layer_name in self.FIELD_LAYER_MAP.values():
                target_layer = self._get_target_layer(layer_name)
                if target_layer:
                    # 清除选择
                    target_layer.removeSelection()
            
            # 刷新画布以清除高亮
            self.iface.mapCanvas().refresh()
            self.status_changed.emit("⭕ 已清除关联要素选择")
        except Exception as e:
            print("清除关联选择时出错: {}".format(str(e)))
    
    def open_config_dialog(self):
        """打开配置对话框（不需要选中 LANE 要素）"""
        lane_layer = self._get_lane_layer()
        if not lane_layer:
            QMessageBox.warning(None, "错误", "未找到 LANE 图层")
            return
        
        # 打开配置对话框（不需要传入选中的要素）
        dialog = RelationConfigDialog(lane_layer, self.FIELD_LAYER_MAP, self)
        if dialog.exec_() == QDialog.Accepted:
            # 保存配置供自动模式使用
            config = dialog.get_config()
            self.auto_mode_config = config
            # 保存配置到 QSettings
            self._save_config(config)
            self.status_changed.emit("✅ 关联配置已保存")
    
    def highlight_and_select(self):
        """打开关联高亮&选择对话框（向后兼容）"""
        self.open_config_dialog()
    
    def assign_relation(self):
        """打开关联赋值对话框"""
        lane_layer = self._get_lane_layer()
        if not lane_layer:
            QMessageBox.warning(None, "错误", "未找到 LANE 图层")
            return
        
        # 自动开启 LANE 图层的编辑模式
        if not lane_layer.isEditable():
            lane_layer.startEditing()
        
        # 获取 BOUNDARY 图层
        boundary_layer = self._get_target_layer('BOUNDARY')
        if not boundary_layer:
            QMessageBox.warning(None, "提示", "未找到 BOUNDARY 图层")
            return
        
        # 创建并显示非模态对话框（不需要预先选中要素）
        dialog = RelationAssignDialog(lane_layer, None, boundary_layer, self.iface.mainWindow())
        
        # 连接对话框的 accepted 信号
        dialog.accepted.connect(lambda: self._on_dialog_accepted(dialog, lane_layer))
        
        # 保存对话框引用，防止被垃圾回收
        self._assign_dialog = dialog
        
        # 非模态显示
        dialog.show()
    
    def _on_dialog_accepted(self, dialog, lane_layer):
        """对话框确认后的处理"""
        updates = dialog.get_updates()
        if updates:
            self._apply_updates(lane_layer, updates)
    
    def _apply_updates(self, lane_layer, updates):
        """应用字段更新
        updates 格式：{feature_id: {field_name: value}}
        """
        try:
            total_updated = 0
            feature_count = 0
            for feature_id, field_updates in updates.items():
                feature_count += 1
                for field_name, new_value in field_updates.items():
                    field_idx = lane_layer.fields().indexOf(field_name)
                    if field_idx >= 0:
                        lane_layer.changeAttributeValue(feature_id, field_idx, new_value)
                        total_updated += 1
            
            # 不自动提交，让用户自己决定是否保存
            self.status_changed.emit("✅ 已更新 {} 条 LANE 要素的 {} 个字段（未保存，请手动保存或撤销）".format(
                feature_count, total_updated))
        except Exception as e:
            import traceback
            error_msg = "应用更新失败: {}\n{}".format(str(e), traceback.format_exc())
            print(error_msg)
            QMessageBox.critical(None, "错误", "应用更新失败：{}".format(str(e)))


class RelationAssignDialog(QDialog):
    """关联赋值对话框 - 灵活管理 LANE 字段的 BOUNDARY ID"""
    
    def __init__(self, lane_layer, lane_features, boundary_layer, parent=None):
        super().__init__(parent)
        self.lane_layer = lane_layer
        # 如果没有传入要素，尝试获取当前选中的 LANE 要素
        if lane_features is None:
            selected_features = lane_layer.selectedFeatures()
            self.lane_features = selected_features if selected_features else []
        else:
            self.lane_features = lane_features
        self.current_lane_features = self.lane_features  # 当前要处理的要素
        self.boundary_layer = boundary_layer
        self.field_widgets = {}  # {field_name: list_widget}
        self.field_modified = {}  # {field_name: bool} 跟踪哪些字段被修改过
        self.field_original_values = {}  # {field_name: set} 记录原始值
        self.iface = None  # 获取 iface 引用用于高亮
        self.info_label = None  # 顶部信息标签
        self.boundary_label = None  # BOUNDARY 信息标签
        self.is_updating = False  # 标记是否正在更新列表（避免递归）
        
        # 设置为独立窗口，可以与主窗口来回切换
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        
        # 尝试获取 iface
        try:
            from qgis.utils import iface
            self.iface = iface
        except:
            pass
        
        # 收集选中的 BOUNDARY ID
        self.boundary_ids = []
        self._update_boundary_ids()
        
        # 加载颜色配置
        self.field_colors = self._load_field_colors()
        
        self.setWindowTitle("关联赋值 - BOUNDARY ID 管理")
        self.resize(800, 600)
        self.setup_ui()
        
        # 连接 LANE 图层的选择变化信号
        if self.lane_layer:
            self.lane_layer.selectionChanged.connect(self.on_lane_selection_changed)
        
        # 连接 BOUNDARY 图层的选择变化信号
        if self.boundary_layer:
            self.boundary_layer.selectionChanged.connect(self.on_boundary_selection_changed)
    
    def _load_field_colors(self):
        """加载字段颜色配置"""
        settings = QSettings()
        field_colors = {}
        for field_name in ['BDY_LEFT', 'BDY_RIGHT', 'RBDY_L', 'RBDY_R']:
            color_str = settings.value("feature_relation/field_colors/{}".format(field_name))
            if color_str:
                field_colors[field_name] = QColor(color_str)
            else:
                # 使用默认颜色
                field_colors[field_name] = DEFAULT_FIELD_COLORS.get(field_name, QColor(255, 0, 0, 200))
        return field_colors
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 顶部信息：显示选中的 BOUNDARY ID
        info_layout = QHBoxLayout()
        self.boundary_label = QLabel()
        self._update_boundary_label()
        info_layout.addWidget(self.boundary_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)
        
        # 提示信息
        tip_label = QLabel("💡 左侧：选择 LANE ID | 右侧：编辑字段值 | 点击 BOUNDARY ID 可高亮要素")
        tip_label.setStyleSheet("color: #666; font-size: 10pt;")
        layout.addWidget(tip_label)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        
        # 主布局：左右分栏
        main_layout = QHBoxLayout()
        
        # ===== 左侧：LANE ID 列表 =====
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        left_label = QLabel("选中的 LANE (可多选)")
        left_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        left_layout.addWidget(left_label)
        
        # LANE ID 列表
        self.lane_list_widget = QListWidget()
        self.lane_list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.lane_list_widget.setMinimumWidth(200)
        self.lane_list_widget.itemSelectionChanged.connect(self._on_lane_list_selection_changed)
        left_layout.addWidget(self.lane_list_widget)
        
        # 初始化 LANE 列表
        self._update_lane_list()
        
        left_widget.setMaximumWidth(250)
        main_layout.addWidget(left_widget)
        
        # ===== 右侧：字段编辑区域 =====
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        right_label = QLabel("字段编辑区")
        right_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        right_layout.addWidget(right_label)
        
        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # 四个字段：BDY_RIGHT, BDY_LEFT, RBDY_L, RBDY_R
        fields = ['BDY_RIGHT', 'BDY_LEFT', 'RBDY_L', 'RBDY_R']
        for field_name in fields:
            # 检查字段是否存在
            if self.lane_layer.fields().indexOf(field_name) < 0:
                continue
            
            # 创建字段组
            group_box = QGroupBox(field_name)
            group_layout = QVBoxLayout()
            
            # 记录原始值
            self.field_original_values[field_name] = set()
            self.field_modified[field_name] = False
            
            # 列表控件
            list_widget = QListWidget()
            list_widget.setSelectionMode(QListWidget.ExtendedSelection)
            list_widget.setMinimumHeight(100)
            
            # 保存列表控件引用
            self.field_widgets[field_name] = list_widget
            
            # 连接点击事件，用于高亮要素
            list_widget.itemClicked.connect(
                lambda item, fn=field_name: self._highlight_boundary(item, fn)
            )
            
            group_layout.addWidget(list_widget)
            
            # 按钮区域
            btn_layout = QHBoxLayout()
            
            add_btn = QPushButton("添加 BOUNDARY 到左侧选中的 LANE")
            add_btn.setToolTip("将选中的 BOUNDARY ID 添加到左侧选中的所有 LANE 的此字段")
            add_btn.clicked.connect(
                lambda checked=False, fn=field_name, lw=list_widget: 
                self._add_boundary_to_selected_lanes(fn)
            )
            btn_layout.addWidget(add_btn)
            
            remove_btn = QPushButton("删除选中项")
            remove_btn.setToolTip("删除列表中选中的 BOUNDARY ID")
            remove_btn.clicked.connect(
                lambda checked=False, fn=field_name, lw=list_widget: 
                self._remove_selected_ids(fn, lw)
            )
            btn_layout.addWidget(remove_btn)
            
            clear_btn = QPushButton("清空")
            clear_btn.setToolTip("清空此字段的所有 ID")
            clear_btn.clicked.connect(
                lambda checked=False, fn=field_name, lw=list_widget: 
                self._clear_ids(fn, lw)
            )
            btn_layout.addWidget(clear_btn)
            
            group_layout.addLayout(btn_layout)
            group_box.setLayout(group_layout)
            scroll_layout.addWidget(group_box)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        right_layout.addWidget(scroll)
        
        main_layout.addWidget(right_widget)
        layout.addLayout(main_layout)
        
        # 底部按钮 - 只保留关闭按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # 初始化完成后，如果有选中的 LANE，更新列表
        if self.current_lane_features:
            QTimer.singleShot(100, self._update_field_lists)
    
    def _update_lane_list(self):
        """更新左侧 LANE ID 列表"""
        self.lane_list_widget.clear()
        if self.current_lane_features:
            for feature in self.current_lane_features:
                lane_id = feature.attribute('ID')
                if lane_id:
                    item = QListWidgetItem(str(lane_id))
                    item.setData(Qt.UserRole, feature.id())  # 保存 feature id
                    self.lane_list_widget.addItem(item)
            # 默认选中第一个
            if self.lane_list_widget.count() > 0:
                self.lane_list_widget.item(0).setSelected(True)
    
    def _on_lane_list_selection_changed(self):
        """左侧 LANE 列表选择变化"""
        selected_items = self.lane_list_widget.selectedItems()
        if not selected_items:
            # 清空右侧字段
            for list_widget in self.field_widgets.values():
                list_widget.clear()
            return
        
        # 获取选中的 LANE 要素
        selected_lane_features = []
        for item in selected_items:
            fid = item.data(Qt.UserRole)
            for feature in self.current_lane_features:
                if feature.id() == fid:
                    selected_lane_features.append(feature)
                    break
        
        # 更新右侧字段显示
        self._update_field_lists_for_lanes(selected_lane_features)
    
    def _update_field_lists_for_lanes(self, lane_features):
        """根据选中的 LANE 更新字段列表"""
        if not lane_features:
            return
        
        # 重新从图层获取最新的要素数据
        refreshed_features = []
        for feature in lane_features:
            fresh_feature = self.lane_layer.getFeature(feature.id())
            if fresh_feature.isValid():
                refreshed_features.append(fresh_feature)
        
        if not refreshed_features:
            return
        
        # 如果只选中一个 LANE，直接显示它的字段值
        if len(refreshed_features) == 1:
            feature = refreshed_features[0]
            for field_name, list_widget in self.field_widgets.items():
                list_widget.clear()
                field_value = feature.attribute(field_name)
                if field_value and str(field_value).strip().upper() not in ('NULL', 'NONE', ''):
                    ids = self._parse_ids(field_value)
                    for id_val in sorted(ids, key=lambda x: int(x) if x.isdigit() else x):
                        list_widget.addItem(id_val)
        else:
            # 如果选中多个 LANE，显示它们的并集
            for field_name, list_widget in self.field_widgets.items():
                all_ids = set()
                for feature in refreshed_features:
                    field_value = feature.attribute(field_name)
                    if field_value and str(field_value).strip().upper() not in ('NULL', 'NONE', ''):
                        all_ids.update(self._parse_ids(field_value))
                
                list_widget.clear()
                for id_val in sorted(all_ids, key=lambda x: int(x) if x.isdigit() else x):
                    list_widget.addItem(id_val)
    
    def _refresh_current_lane_features(self):
        """刷新 current_lane_features 以获取最新的字段值"""
        if not self.current_lane_features:
            return
        
        # 获取当前要素的 ID 列表
        feature_ids = [f.id() for f in self.current_lane_features]
        
        # 重新从图层获取这些要素
        self.current_lane_features = []
        for fid in feature_ids:
            feature = self.lane_layer.getFeature(fid)
            if feature.isValid():
                self.current_lane_features.append(feature)
    
    def _highlight_boundary(self, item, field_name):
        """高亮指定 ID 的 BOUNDARY 要素"""
        if not self.iface or not self.boundary_layer:
            return
        
        boundary_id = item.text()
        
        # 查找对应的要素
        target_feature = None
        for feature in self.boundary_layer.getFeatures():
            fid = feature.attribute('ID')
            if fid and str(fid) == boundary_id:
                target_feature = feature
                break
        
        if not target_feature:
            return
        
        # 获取字段颜色
        color = self.field_colors.get(field_name, QColor(255, 0, 0, 200))
        
        # 获取高亮时长配置
        settings = QSettings()
        highlight_duration = settings.value("feature_relation/highlight_duration", 1000, type=int)
        
        # 清除之前的高亮
        if hasattr(self, '_highlight_rubber_band') and self._highlight_rubber_band:
            self.iface.mapCanvas().scene().removeItem(self._highlight_rubber_band)
        
        # 清除之前的定时器
        if hasattr(self, '_highlight_timer') and self._highlight_timer:
            self._highlight_timer.stop()
            self._highlight_timer.deleteLater()
        
        # 创建高亮
        from qgis.gui import QgsRubberBand
        rubber_band = QgsRubberBand(self.iface.mapCanvas(), target_feature.geometry().type())
        rubber_band.setToGeometry(target_feature.geometry(), self.boundary_layer)
        rubber_band.setColor(color)
        rubber_band.setWidth(3)
        rubber_band.setFillColor(QColor(color.red(), color.green(), color.blue(), 50))
        
        # 保存引用
        self._highlight_rubber_band = rubber_band
        
        # 刷新画布
        self.iface.mapCanvas().refresh()
        
        # 如果不是永久高亮，设置定时器
        if highlight_duration != -1:
            from PyQt5.QtCore import QTimer
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(self._clear_highlight)
            timer.start(highlight_duration)
            self._highlight_timer = timer
    
    def _clear_highlight(self):
        """清除高亮"""
        if hasattr(self, '_highlight_rubber_band') and self._highlight_rubber_band:
            self.iface.mapCanvas().scene().removeItem(self._highlight_rubber_band)
            self._highlight_rubber_band = None
            self.iface.mapCanvas().refresh()
    
    def _parse_ids(self, field_value):
        """解析字段值中的 ID 列表"""
        if not field_value or str(field_value).strip().upper() in ('NULL', 'NONE', ''):
            return []
        value_str = str(field_value).strip()
        return [id_str.strip() for id_str in value_str.split('|') if id_str.strip()]
    
    def on_lane_selection_changed(self):
        """LANE 图层选择变化时的回调"""
        if self.is_updating:
            return
        
        selected_features = self.lane_layer.selectedFeatures()
        self.current_lane_features = selected_features
        
        # 更新左侧 LANE 列表
        self._update_lane_list()
        
        # 更新右侧字段列表（根据左侧选中的项）
        selected_items = self.lane_list_widget.selectedItems()
        if selected_items:
            selected_lane_features = []
            for item in selected_items:
                fid = item.data(Qt.UserRole)
                for feature in self.current_lane_features:
                    if feature.id() == fid:
                        selected_lane_features.append(feature)
                        break
            self._update_field_lists_for_lanes(selected_lane_features)
    
    def on_boundary_selection_changed(self):
        """BOUNDARY 图层选择变化时的回调"""
        if self.is_updating:
            return
        
        # 更新 BOUNDARY ID 列表
        self._update_boundary_ids()
        
        # 更新 BOUNDARY 信息标签
        self._update_boundary_label()
    
    def _update_boundary_ids(self):
        """更新选中的 BOUNDARY ID 列表"""
        self.boundary_ids = []
        if self.boundary_layer:
            boundary_selected = self.boundary_layer.selectedFeatures()
            for f in boundary_selected:
                fid = f.attribute('ID')
                if fid and str(fid).strip().upper() not in ('NULL', 'NONE', ''):
                    self.boundary_ids.append(str(fid))
    
    def _update_boundary_label(self):
        """更新 BOUNDARY 信息标签"""
        if not self.boundary_label:
            return
        
        if self.boundary_ids:
            text = "已选中 <b>{}</b> 个 BOUNDARY 要素: {}".format(
                len(self.boundary_ids), 
                ', '.join(self.boundary_ids[:5]) + ('...' if len(self.boundary_ids) > 5 else '')
            )
        else:
            text = "未选中 BOUNDARY 要素"
        self.boundary_label.setText(text)
    
    def _update_info_label(self):
        """更新顶部信息标签 - 已移除，不再需要"""
        pass
    
    def _update_field_lists(self):
        """根据当前选中的 LANE 要素更新各字段的列表 - 已废弃，使用 _update_field_lists_for_lanes"""
        pass
    
    def _add_ids(self, field_name, list_widget, new_ids):
        """添加 ID 到列表"""
        if not new_ids:
            QMessageBox.warning(self, "提示", "请先在地图上选中 BOUNDARY 要素")
            return
        
        current_ids = set()
        for i in range(list_widget.count()):
            current_ids.add(list_widget.item(i).text())
        
        added_count = 0
        for new_id in new_ids:
            if new_id not in current_ids:
                list_widget.addItem(new_id)
                current_ids.add(new_id)
                added_count += 1
        
        if added_count > 0:
            # 重新排序
            self._sort_list(list_widget)
    
    def _add_boundary_to_selected_lanes(self, field_name):
        """将选中的 BOUNDARY ID 添加到左侧选中的所有 LANE 的指定字段"""
        # 检查是否选中了 BOUNDARY
        if not self.boundary_ids:
            QMessageBox.warning(self, "提示", "请先在地图上选中 BOUNDARY 要素")
            return
        
        # 获取左侧选中的 LANE
        selected_items = self.lane_list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "请先在左侧列表中选择 LANE ID")
            return
        
        # 获取选中的 LANE 要素
        selected_lane_features = []
        for item in selected_items:
            fid = item.data(Qt.UserRole)
            for feature in self.current_lane_features:
                if feature.id() == fid:
                    selected_lane_features.append(feature)
                    break
        
        if not selected_lane_features:
            return
        
        # 批量添加 BOUNDARY ID 到所有选中的 LANE
        field_idx = self.lane_layer.fields().indexOf(field_name)
        if field_idx < 0:
            return
        
        try:
            self.is_updating = True  # 设置更新标志
            for feature in selected_lane_features:
                # 获取当前字段值
                current_value = feature.attribute(field_name)
                if current_value and str(current_value).strip().upper() not in ('NULL', 'NONE', ''):
                    current_ids = set(self._parse_ids(current_value))
                else:
                    current_ids = set()
                
                # 添加新的 BOUNDARY ID
                current_ids.update(self.boundary_ids)
                
                # 排序并生成新值
                sorted_ids = sorted(current_ids, key=lambda x: int(x) if x.isdigit() else x)
                new_value = '|'.join(sorted_ids) if sorted_ids else None
                
                # 更新字段值
                self.lane_layer.changeAttributeValue(feature.id(), field_idx, new_value)
            
            # 刷新 current_lane_features 以获取最新数据
            self._refresh_current_lane_features()
            
            # 刷新右侧显示
            self._update_field_lists_for_lanes(selected_lane_features)
            
            QMessageBox.information(self, "成功", 
                "已将 {} 个 BOUNDARY ID 添加到 {} 个 LANE 的 {} 字段".format(
                    len(self.boundary_ids), len(selected_lane_features), field_name))
        except Exception as e:
            QMessageBox.critical(self, "错误", "添加失败：{}".format(str(e)))
        finally:
            self.is_updating = False  # 清除更新标志
    
    def _remove_selected_ids(self, field_name, list_widget):
        """删除选中的 BOUNDARY ID"""
        selected_items = list_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "提示", "请先在列表中选择要删除的 ID")
            return
        
        # 获取要删除的 ID
        ids_to_remove = [item.text() for item in selected_items]
        
        # 获取左侧选中的 LANE
        selected_lane_items = self.lane_list_widget.selectedItems()
        if not selected_lane_items:
            QMessageBox.warning(self, "提示", "请先在左侧列表中选择 LANE ID")
            return
        
        # 获取选中的 LANE 要素
        selected_lane_features = []
        for item in selected_lane_items:
            fid = item.data(Qt.UserRole)
            for feature in self.current_lane_features:
                if feature.id() == fid:
                    selected_lane_features.append(feature)
                    break
        
        if not selected_lane_features:
            return
        
        # 批量删除 BOUNDARY ID
        field_idx = self.lane_layer.fields().indexOf(field_name)
        if field_idx < 0:
            return
        
        try:
            self.is_updating = True  # 设置更新标志
            for feature in selected_lane_features:
                # 获取当前字段值
                current_value = feature.attribute(field_name)
                if current_value and str(current_value).strip().upper() not in ('NULL', 'NONE', ''):
                    current_ids = set(self._parse_ids(current_value))
                else:
                    continue
                
                # 删除指定的 ID
                for id_to_remove in ids_to_remove:
                    current_ids.discard(id_to_remove)
                
                # 排序并生成新值
                sorted_ids = sorted(current_ids, key=lambda x: int(x) if x.isdigit() else x)
                new_value = '|'.join(sorted_ids) if sorted_ids else None
                
                # 更新字段值
                self.lane_layer.changeAttributeValue(feature.id(), field_idx, new_value)
            
            # 刷新 current_lane_features 以获取最新数据
            self._refresh_current_lane_features()
            
            # 刷新右侧显示
            self._update_field_lists_for_lanes(selected_lane_features)
            
            QMessageBox.information(self, "成功", 
                "已从 {} 个 LANE 的 {} 字段删除 {} 个 BOUNDARY ID".format(
                    len(selected_lane_features), field_name, len(ids_to_remove)))
        except Exception as e:
            QMessageBox.critical(self, "错误", "删除失败：{}".format(str(e)))
        finally:
            self.is_updating = False  # 清除更新标志
    
    def _clear_ids(self, field_name, list_widget):
        """清空所有 BOUNDARY ID"""
        if list_widget.count() == 0:
            return
        
        # 获取左侧选中的 LANE
        selected_lane_items = self.lane_list_widget.selectedItems()
        if not selected_lane_items:
            QMessageBox.warning(self, "提示", "请先在左侧列表中选择 LANE ID")
            return
        
        # 确认操作
        reply = QMessageBox.question(self, "确认", 
            "确定要清空选中 LANE 的 {} 字段吗？".format(field_name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply != QMessageBox.Yes:
            return
        
        # 获取选中的 LANE 要素
        selected_lane_features = []
        for item in selected_lane_items:
            fid = item.data(Qt.UserRole)
            for feature in self.current_lane_features:
                if feature.id() == fid:
                    selected_lane_features.append(feature)
                    break
        
        if not selected_lane_features:
            return
        
        # 批量清空字段
        field_idx = self.lane_layer.fields().indexOf(field_name)
        if field_idx < 0:
            return
        
        try:
            self.is_updating = True  # 设置更新标志
            for feature in selected_lane_features:
                self.lane_layer.changeAttributeValue(feature.id(), field_idx, None)
            
            # 刷新 current_lane_features 以获取最新数据
            self._refresh_current_lane_features()
            
            # 刷新右侧显示
            self._update_field_lists_for_lanes(selected_lane_features)
            
            QMessageBox.information(self, "成功", 
                "已清空 {} 个 LANE 的 {} 字段".format(
                    len(selected_lane_features), field_name))
        except Exception as e:
            QMessageBox.critical(self, "错误", "清空失败：{}".format(str(e)))
        finally:
            self.is_updating = False  # 清除更新标志
    
    def _sort_list(self, list_widget):
        """对列表进行排序"""
        items = []
        for i in range(list_widget.count()):
            items.append(list_widget.item(i).text())
        
        items.sort(key=lambda x: int(x) if x.isdigit() else x)
        
        list_widget.clear()
        for item in items:
            list_widget.addItem(item)
    
    def get_updates(self):
        """获取所有更新 - 由于操作已经直接修改了 LANE 要素，这里返回空字典"""
        # 新的设计中，所有修改都在按钮操作中直接提交到图层了
        # 所以对话框关闭时不需要再次提交
        return 
    
    def closeEvent(self, event):
        """对话框关闭时清除高亮"""
        self._clear_highlight()
        super().closeEvent(event)


class RelationConfigDialog(QDialog):
    """关联配置对话框（不需要选中要素，纯配置）"""
    
    def __init__(self, lane_layer, field_layer_map, controller, parent=None):
        super().__init__(parent)
        self.lane_layer = lane_layer
        self.field_layer_map = field_layer_map
        self.controller = controller
        
        # 从 controller 加载已保存的配置
        if controller.auto_mode_config:
            self.field_colors = controller.auto_mode_config.get('field_colors', DEFAULT_FIELD_COLORS.copy())
            self.enabled_fields = controller.auto_mode_config.get('enabled_fields', set(field_layer_map.keys()))
            self.highlight_duration = controller.auto_mode_config.get('highlight_duration', 1000)
        else:
            self.field_colors = DEFAULT_FIELD_COLORS.copy()
            self.enabled_fields = set(field_layer_map.keys())
            self.highlight_duration = 1000  # 默认 1 秒
        
        self.field_checkboxes = {}
        
        self.setWindowTitle("关联配置")
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 顶部说明
        info_label = QLabel("配置关联字段的启用状态和高亮颜色（用于自动关联模式）：")
        layout.addWidget(info_label)
        
        # 高亮持续时间设置
        duration_layout = QHBoxLayout()
        duration_label = QLabel("高亮持续时间：")
        duration_layout.addWidget(duration_label)
        
        self.duration_radio_custom = QRadioButton("自定义")
        self.duration_radio_custom.toggled.connect(self._on_custom_duration_toggled)
        duration_layout.addWidget(self.duration_radio_custom)
        
        self.duration_spinbox = QSpinBox()
        self.duration_spinbox.setRange(1, 60)
        self.duration_spinbox.setValue(1)
        self.duration_spinbox.setSuffix(" 秒")
        self.duration_spinbox.setEnabled(False)
        self.duration_spinbox.valueChanged.connect(self._on_spinbox_value_changed)
        duration_layout.addWidget(self.duration_spinbox)
        
        self.duration_radio_forever = QRadioButton("一直高亮")
        self.duration_radio_forever.toggled.connect(lambda checked: self._set_duration(-1) if checked else None)
        duration_layout.addWidget(self.duration_radio_forever)
        
        duration_layout.addStretch()
        layout.addLayout(duration_layout)
        
        # 根据当前配置设置选中状态
        if self.highlight_duration == -1:
            self.duration_radio_forever.setChecked(True)
        else:
            self.duration_radio_custom.setChecked(True)
            self.duration_spinbox.setValue(self.highlight_duration // 1000)
            self.duration_spinbox.setEnabled(True)
        
        # 添加分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        
        # 获取所有相关字段
        lane_field_names = {f.name().upper(): f.name() for f in self.lane_layer.fields()}
        
        # 按图层类型分组显示字段
        layer_groups = {}
        for field_upper, layer_name in self.field_layer_map.items():
            field_name = lane_field_names.get(field_upper)
            if not field_name:
                continue
            if layer_name not in layer_groups:
                layer_groups[layer_name] = []
            layer_groups[layer_name].append((field_upper, field_name))
        
        # 为每个图层创建分组框
        for layer_name, fields in sorted(layer_groups.items()):
            group_box = QGroupBox("{} 图层".format(layer_name))
            group_layout = QGridLayout()
            
            row = 0
            for field_upper, field_name in sorted(fields):
                # 复选框
                checkbox = QCheckBox(field_name)
                checkbox.setChecked(field_upper in self.enabled_fields)
                self.field_checkboxes[field_upper] = checkbox
                group_layout.addWidget(checkbox, row, 0)
                
                # 颜色按钮
                color_btn = QPushButton()
                color_btn.setMaximumWidth(60)
                color_btn.setStyleSheet("background-color: {};".format(
                    self.field_colors[field_upper].name()
                ))
                color_btn.clicked.connect(
                    lambda checked=False, fu=field_upper, btn=color_btn: 
                    self._change_color(fu, btn)
                )
                group_layout.addWidget(color_btn, row, 1)
                
                row += 1
            
            group_box.setLayout(group_layout)
            layout.addWidget(group_box)
        
        # 底部按钮
        btn_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("全不选")
        deselect_all_btn.clicked.connect(self._deselect_all)
        btn_layout.addWidget(deselect_all_btn)
        
        btn_layout.addStretch()
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        btn_layout.addWidget(button_box)
        
        layout.addLayout(btn_layout)
    
    def _set_duration(self, duration):
        """设置高亮持续时间"""
        self.highlight_duration = duration
    
    def _on_custom_duration_toggled(self, checked):
        """自定义时长单选按钮切换"""
        self.duration_spinbox.setEnabled(checked)
        if checked:
            self._set_duration(self.duration_spinbox.value() * 1000)
    
    def _on_spinbox_value_changed(self, value):
        """自定义秒数变化"""
        if self.duration_radio_custom.isChecked():
            self._set_duration(value * 1000)
    
    def _change_color(self, field_upper, button):
        """更改字段颜色"""
        current_color = self.field_colors[field_upper]
        color = QColorDialog.getColor(current_color, self, "选择高亮颜色")
        if color.isValid():
            self.field_colors[field_upper] = color
            button.setStyleSheet("background-color: {};".format(color.name()))
    
    def _select_all(self):
        """全选字段"""
        for checkbox in self.field_checkboxes.values():
            checkbox.setChecked(True)
    
    def _deselect_all(self):
        """取消全选"""
        for checkbox in self.field_checkboxes.values():
            checkbox.setChecked(False)
    
    def get_config(self):
        """获取当前配置"""
        enabled_fields = set()
        for field_upper, checkbox in self.field_checkboxes.items():
            if checkbox.isChecked():
                enabled_fields.add(field_upper)
        
        return {
            'enabled_fields': enabled_fields,
            'field_colors': self.field_colors.copy(),
            'highlight_duration': self.highlight_duration
        }


class HighlightSelectDialog(QDialog):
    """关联高亮&选择对话框"""
    
    def __init__(self, lane_layer, lane_features, field_layer_map, controller, parent=None):
        super().__init__(parent)
        self.lane_layer = lane_layer
        self.lane_features = lane_features
        self.field_layer_map = field_layer_map
        self.controller = controller
        self.field_colors = DEFAULT_FIELD_COLORS.copy()
        self.field_checkboxes = {}
        
        self.setWindowTitle("关联高亮 & 选择")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 顶部信息
        info_label = QLabel("已选中 {} 个 LANE 要素，请选择要处理的关联字段：".format(len(self.lane_features)))
        layout.addWidget(info_label)
        
        # 获取所有相关字段
        lane_field_names = {f.name().upper(): f.name() for f in self.lane_layer.fields()}
        
        # 按图层类型分组显示字段
        layer_groups = {}
        for field_upper, layer_name in self.field_layer_map.items():
            field_name = lane_field_names.get(field_upper)
            if not field_name:
                continue
            if layer_name not in layer_groups:
                layer_groups[layer_name] = []
            layer_groups[layer_name].append((field_upper, field_name))
        
        # 为每个图层创建分组框
        for layer_name, fields in sorted(layer_groups.items()):
            group_box = QGroupBox("{} 图层".format(layer_name))
            group_layout = QGridLayout()
            
            row = 0
            for field_upper, field_name in sorted(fields):
                # 复选框
                checkbox = QCheckBox(field_name)
                checkbox.setChecked(True)
                self.field_checkboxes[field_upper] = checkbox
                group_layout.addWidget(checkbox, row, 0)
                
                # 颜色按钮
                color_btn = QPushButton()
                color_btn.setMaximumWidth(60)
                color_btn.setStyleSheet("background-color: {};".format(
                    self.field_colors[field_upper].name()
                ))
                color_btn.clicked.connect(
                    lambda checked=False, fu=field_upper, btn=color_btn: 
                    self._change_color(fu, btn)
                )
                group_layout.addWidget(color_btn, row, 1)
                
                # 统计信息
                id_count = self._count_related_ids(field_name)
                count_label = QLabel("({} 个 ID)".format(id_count))
                group_layout.addWidget(count_label, row, 2)
                
                row += 1
            
            group_box.setLayout(group_layout)
            layout.addWidget(group_box)
        
        # 底部按钮
        btn_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("全不选")
        deselect_all_btn.clicked.connect(self._deselect_all)
        btn_layout.addWidget(deselect_all_btn)
        
        btn_layout.addStretch()
        
        highlight_btn = QPushButton("高亮")
        highlight_btn.clicked.connect(self._do_highlight)
        btn_layout.addWidget(highlight_btn)
        
        select_btn = QPushButton("选中")
        select_btn.clicked.connect(self._do_select)
        btn_layout.addWidget(select_btn)
        
        highlight_select_btn = QPushButton("高亮 + 选中")
        highlight_select_btn.clicked.connect(self._do_highlight_and_select)
        btn_layout.addWidget(highlight_select_btn)
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
    
    def _count_related_ids(self, field_name):
        """统计字段中的关联 ID 数量"""
        id_set = set()
        for lane_feature in self.lane_features:
            field_value = lane_feature.attribute(field_name)
            if field_value and str(field_value).strip().upper() not in ('NULL', 'NONE', ''):
                ids = self.controller._parse_ids(field_value)
                id_set.update(ids)
        return len(id_set)
    
    def _change_color(self, field_upper, button):
        """更改字段颜色"""
        current_color = self.field_colors[field_upper]
        color = QColorDialog.getColor(current_color, self, "选择高亮颜色")
        if color.isValid():
            self.field_colors[field_upper] = color
            button.setStyleSheet("background-color: {};".format(color.name()))
    
    def _select_all(self):
        """全选字段"""
        for checkbox in self.field_checkboxes.values():
            checkbox.setChecked(True)
    
    def _deselect_all(self):
        """取消全选"""
        for checkbox in self.field_checkboxes.values():
            checkbox.setChecked(False)
    
    def get_config(self):
        """获取当前配置（供自动模式使用）"""
        selected_fields = []
        for field_upper, checkbox in self.field_checkboxes.items():
            if checkbox.isChecked():
                selected_fields.append(field_upper)
        
        return {
            'selected_fields': selected_fields,
            'colors': self.field_colors.copy()
        }
    
    def _get_selected_fields(self):
        """获取选中的字段"""
        selected = {}
        lane_field_names = {f.name().upper(): f.name() for f in self.lane_layer.fields()}
        
        for field_upper, checkbox in self.field_checkboxes.items():
            if checkbox.isChecked():
                field_name = lane_field_names.get(field_upper)
                if field_name:
                    selected[field_upper] = field_name
        
        return selected
    
    def _do_highlight(self):
        """执行高亮操作"""
        selected_fields = self._get_selected_fields()
        if not selected_fields:
            QMessageBox.warning(self, "提示", "请至少选择一个字段")
            return
        
        total_highlighted = 0
        
        for lane_feature in self.lane_features:
            for field_upper, field_name in selected_fields.items():
                field_value = lane_feature.attribute(field_name)
                if not field_value or str(field_value).strip().upper() in ('NULL', 'NONE', ''):
                    continue
                
                ids = self.controller._parse_ids(field_value)
                if not ids:
                    continue
                
                layer_name = self.field_layer_map[field_upper]
                target_layer = self.controller._get_target_layer(layer_name)
                if not target_layer:
                    continue
                
                # 查找要素并高亮
                feature_ids = []
                for feature_id in ids:
                    expression = '"ID" = \'{}\''.format(feature_id)
                    request = QgsFeatureRequest(QgsExpression(expression))
                    for feature in target_layer.getFeatures(request):
                        feature_ids.append(feature.id())
                        break
                
                if feature_ids:
                    color = self.field_colors[field_upper]
                    self.controller.iface.mapCanvas().flashFeatureIds(
                        target_layer,
                        feature_ids,
                        color,
                        QColor(color.red(), color.green(), color.blue(), 100),
                        flashes=3,
                        duration=1500
                    )
                    total_highlighted += len(feature_ids)
        
        if total_highlighted > 0:
            self.controller.status_changed.emit("已高亮 {} 个关联要素".format(total_highlighted))
            QMessageBox.information(self, "完成", "已高亮 {} 个关联要素".format(total_highlighted))
        else:
            QMessageBox.information(self, "提示", "未找到关联要素")
    
    def _do_select(self):
        """执行选择操作"""
        selected_fields = self._get_selected_fields()
        if not selected_fields:
            QMessageBox.warning(self, "提示", "请至少选择一个字段")
            return
        
        layer_selections = {}
        
        for lane_feature in self.lane_features:
            for field_upper, field_name in selected_fields.items():
                field_value = lane_feature.attribute(field_name)
                if not field_value or str(field_value).strip().upper() in ('NULL', 'NONE', ''):
                    continue
                
                ids = self.controller._parse_ids(field_value)
                if not ids:
                    continue
                
                layer_name = self.field_layer_map[field_upper]
                target_layer = self.controller._get_target_layer(layer_name)
                if not target_layer:
                    continue
                
                if layer_name not in layer_selections:
                    layer_selections[layer_name] = []
                
                # 查找要素 ID
                for feature_id in ids:
                    expression = '"ID" = \'{}\''.format(feature_id)
                    request = QgsFeatureRequest(QgsExpression(expression))
                    for feature in target_layer.getFeatures(request):
                        if feature.id() not in layer_selections[layer_name]:
                            layer_selections[layer_name].append(feature.id())
                        break
        
        total_selected = 0
        for layer_name, feature_ids in layer_selections.items():
            target_layer = self.controller._get_target_layer(layer_name)
            if target_layer:
                target_layer.selectByIds(feature_ids, QgsVectorLayer.AddToSelection)
                total_selected += len(feature_ids)
        
        if total_selected > 0:
            self.controller.status_changed.emit("已选中 {} 个关联要素".format(total_selected))
            QMessageBox.information(self, "完成", "已选中 {} 个关联要素".format(total_selected))
        else:
            QMessageBox.information(self, "提示", "未找到关联要素")
    
    def _do_highlight_and_select(self):
        """执行高亮+选择操作"""
        self._do_highlight()
        self._do_select()

