# -*- coding: utf-8 -*-
"""
要素关联管理器
支持 LANE 图层字段关联到其他图层要素的高亮、选择、赋值
"""
import os
from qgis.PyQt.QtCore import QObject, pyqtSignal, Qt, QSettings
from qgis.PyQt.QtWidgets import (
    QAction, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QDialogButtonBox,
    QCheckBox, QGroupBox, QColorDialog, QGridLayout, QMenu, QToolButton,
    QRadioButton, QFrame, QSpinBox
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
        self.assign_toolbar_action = None  # 关联赋值按钮的工具栏引用
        self._is_processing = False  # 递归锁，防止无限循环
        
        # 加载保存的配置
        self._load_config()
    
    def initGui(self, actions_master, register_action=True):
        if not register_action:
            return
        # 关联赋值按钮（添加到菜单）
        assign_icon_path = os.path.join(self.plugin_dir, "icon_relation_assign.svg")
        self.assign_action = QAction(QIcon(assign_icon_path), u"关联赋值", self.iface.mainWindow())
        self.assign_action.triggered.connect(self.assign_relation)
        self.iface.addPluginToVectorMenu(u"车道处理工具", self.assign_action)
        
        self.actions.append(self.assign_action)
        actions_master.append(self.assign_action)
        
        # 保存 assign_action 的工具栏引用（稍后添加）
        self.assign_toolbar_action = None
        self.toolbar_button = None
        self.toolbar_action = None
    
    def _create_toolbar_button(self):
        """创建工具栏按钮 - 关联功能下拉菜单"""
        icon_path = os.path.join(self.plugin_dir, "icon_auto_relation.svg")
        
        # 创建工具按钮（支持下拉菜单）
        tool_button = QToolButton()
        tool_button.setIcon(QIcon(icon_path))
        tool_button.setText(u"关联功能")
        tool_button.setToolTip(u"关联功能")
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
        
        # 第三项：关联赋值
        assign_icon_path = os.path.join(self.plugin_dir, "icon_relation_assign.svg")
        assign_menu_action = QAction(QIcon(assign_icon_path), u"关联赋值", self.iface.mainWindow())
        assign_menu_action.triggered.connect(self.assign_relation)
        menu.addAction(assign_menu_action)
        
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
        
        toolbar = self.iface.vectorToolBar()
        if toolbar:
            # 添加下拉按钮
            if self.toolbar_button and not self.toolbar_action:
                self.toolbar_action = toolbar.addWidget(self.toolbar_button)
    
    def remove_toolbar_button(self):
        """从工具栏移除工具按钮"""
        toolbar = self.iface.vectorToolBar()
        
        # 移除下拉按钮
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
            
            # 按字段分组，保留每个字段的独立颜色
            field_selections = {}
            
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
                    
                    if field_upper not in field_selections:
                        field_selections[field_upper] = {
                            'layer_name': layer_name,
                            'layer': target_layer,
                            'ids': [], 
                            'color': field_colors.get(field_upper, QColor(255, 0, 0, 200))
                        }
                    
                    # 查找要素
                    for feature_id in ids:
                        try:
                            expression = '"ID" = \'{}\''.format(feature_id)
                            request = QgsFeatureRequest(QgsExpression(expression))
                            for feature in target_layer.getFeatures(request):
                                if feature.id() not in field_selections[field_upper]['ids']:
                                    field_selections[field_upper]['ids'].append(feature.id())
                                break
                        except:
                            continue
            
            # 应用新的高亮 - 按字段逐个闪烁，保持不同颜色
            total_selected = 0
            highlight_duration = self.auto_mode_config.get('highlight_duration', 1000)
            
            for field_upper, data in field_selections.items():
                try:
                    target_layer = data['layer']
                    fids = data['ids']
                    color = data['color']
                    
                    if target_layer and fids:
                        # 选中要素
                        target_layer.selectByIds(fids, QgsVectorLayer.AddToSelection)
                        
                        if highlight_duration == -1:
                            # 一直高亮（不闪烁）- 使用非常大的持续时间和1次闪烁
                            self.iface.mapCanvas().flashFeatureIds(
                                target_layer,
                                fids,
                                color,
                                color,  # 开始和结束颜色相同，避免闪烁效果
                                flashes=1,
                                duration=999999999  # 近乎永久
                            )
                        else:
                            # 按配置的时间闪烁（1次闪烁）
                            self.iface.mapCanvas().flashFeatureIds(
                                target_layer,
                                fids,
                                color,
                                QColor(color.red(), color.green(), color.blue(), 100),
                                flashes=1,
                                duration=highlight_duration
                            )
                        total_selected += len(fids)
                except Exception as e:
                    print("高亮字段 {} 时出错: {}".format(field_upper, str(e)))
                    continue
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
    
    def assign_relation(self):
        """打开关联赋值对话框"""
        lane_layer = self._get_lane_layer()
        if not lane_layer:
            QMessageBox.warning(None, "错误", "未找到 LANE 图层")
            return
        
        lane_features = lane_layer.selectedFeatures()
        if not lane_features:
            QMessageBox.warning(None, "提示", "请先选中 LANE 要素")
            return
        
        # 收集其他图层的选中要素
        layer_selections = {}
        for layer_name in set(self.FIELD_LAYER_MAP.values()):
            target_layer = self._get_target_layer(layer_name)
            if not target_layer:
                continue
            selected = target_layer.selectedFeatures()
            if selected:
                selected_ids = []
                for f in selected:
                    fid = f.attribute('ID')
                    if fid and str(fid).strip().upper() not in ('NULL', 'NONE', ''):
                        selected_ids.append(str(fid))
                if selected_ids:
                    layer_selections[layer_name] = selected_ids
        
        if not layer_selections:
            QMessageBox.warning(None, "提示", "请先选中要关联的要素（BOUNDARY/LANE/SIGNAL）")
            return
        
        # 打开赋值对话框
        dialog = RelationAssignDialog(lane_layer, lane_features, layer_selections, self.FIELD_LAYER_MAP, self.iface.mainWindow())
        if dialog.exec_() == QDialog.Accepted:
            updates = dialog.get_updates()
            if updates:
                self._apply_updates(lane_layer, lane_features, updates)
    
    def _apply_updates(self, lane_layer, lane_features, updates):
        """应用字段更新"""
        if not updates:
            QMessageBox.information(None, "提示", "没有任何字段需要更新")
            return
        
        if not lane_layer.startEditing():
            QMessageBox.critical(None, "错误", "无法开启编辑模式")
            return
        
        try:
            updated_fields = []
            for lane_feature in lane_features:
                for field_name, new_value in updates.items():
                    field_idx = lane_layer.fields().indexOf(field_name)
                    if field_idx >= 0:
                        lane_layer.changeAttributeValue(lane_feature.id(), field_idx, new_value)
                        if field_name not in updated_fields:
                            updated_fields.append(field_name)
            
            if lane_layer.commitChanges():
                msg = "已更新 {} 条 LANE 要素的 {} 个字段:\n{}".format(
                    len(lane_features), 
                    len(updated_fields),
                    ', '.join(updated_fields)
                )
                self.status_changed.emit(msg)
                QMessageBox.information(None, "完成", msg)
            else:
                errors = lane_layer.commitErrors()
                lane_layer.rollBack()
                QMessageBox.critical(None, "错误", "保存失败:\n" + '\n'.join(errors))
        except Exception as e:
            lane_layer.rollBack()
            QMessageBox.critical(None, "错误", "更新失败: {}".format(str(e)))


class RelationAssignDialog(QDialog):
    """关联赋值对话框 - 灵活的字段赋值界面"""
    
    def __init__(self, lane_layer, lane_features, layer_selections, field_layer_map, parent=None):
        super().__init__(parent)
        self.lane_layer = lane_layer
        self.lane_features = lane_features
        self.layer_selections = layer_selections
        self.field_layer_map = field_layer_map
        self.field_widgets = {}  # 存储每个字段的 ListWidget
        
        self.setWindowTitle("关联赋值 - 灵活管理")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 顶部信息
        info_layout = QHBoxLayout()
        info_label = QLabel("已选中 <b>{}</b> 个 LANE 要素".format(len(self.lane_features)))
        info_layout.addWidget(info_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)
        
        # 获取所有相关字段
        lane_field_names = {f.name().upper(): f.name() for f in self.lane_layer.fields()}
        
        # 为每个图层类型创建控制区域
        for layer_name, selected_ids in self.layer_selections.items():
            # 找到所有映射到这个图层的字段
            related_fields = [
                (field_upper, lane_field_names[field_upper])
                for field_upper, target_layer in self.field_layer_map.items()
                if target_layer == layer_name and field_upper in lane_field_names
            ]
            
            if not related_fields:
                continue
            
            # 创建分组框
            group_box = QGroupBox("{} 图层 - 已选 {} 个要素: {}".format(
                layer_name, 
                len(selected_ids),
                ', '.join(selected_ids[:5]) + ('...' if len(selected_ids) > 5 else '')
            ))
            group_layout = QVBoxLayout()
            
            # 显示选中的要素ID列表
            ids_label = QLabel("待分配的 ID: <b>{}</b>".format(' | '.join(selected_ids)))
            ids_label.setWordWrap(True)
            ids_label.setStyleSheet("color: #0066cc; padding: 5px; background: #f0f0f0; border-radius: 3px;")
            group_layout.addWidget(ids_label)
            
            # 为每个字段创建控制行
            for field_upper, field_name in sorted(related_fields):
                field_frame = QFrame()
                field_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
                field_layout = QHBoxLayout(field_frame)
                
                # 字段标签
                field_label = QLabel("<b>{}</b>:".format(field_name))
                field_label.setMinimumWidth(100)
                field_layout.addWidget(field_label)
                
                # 当前值列表
                current_ids = set()
                for lane_feature in self.lane_features:
                    field_value = lane_feature.attribute(field_name)
                    if field_value and str(field_value).strip().upper() not in ('NULL', 'NONE', ''):
                        current_ids.update(self._parse_ids(field_value))
                
                list_widget = QListWidget()
                list_widget.setSelectionMode(QListWidget.MultiSelection)
                list_widget.setMaximumHeight(100)
                for id_val in sorted(current_ids):
                    list_widget.addItem(id_val)
                field_layout.addWidget(list_widget, 3)
                self.field_widgets[field_name] = list_widget
                
                # 按钮区域
                btn_layout = QVBoxLayout()
                
                add_btn = QPushButton("← 添加")
                add_btn.setToolTip("将左侧选中的 ID 添加到此字段")
                add_btn.clicked.connect(
                    lambda checked=False, fw=field_name, lw=list_widget, ids=selected_ids: 
                    self._add_ids(fw, lw, ids)
                )
                btn_layout.addWidget(add_btn)
                
                remove_btn = QPushButton("删除选中 →")
                remove_btn.setToolTip("删除此字段中选中的 ID")
                remove_btn.clicked.connect(
                    lambda checked=False, fw=field_name, lw=list_widget: 
                    self._remove_selected_ids(fw, lw)
                )
                btn_layout.addWidget(remove_btn)
                
                clear_btn = QPushButton("清空")
                clear_btn.setToolTip("清空此字段的所有 ID")
                clear_btn.clicked.connect(
                    lambda checked=False, fw=field_name, lw=list_widget: 
                    self._clear_ids(fw, lw)
                )
                btn_layout.addWidget(clear_btn)
                btn_layout.addStretch()
                
                field_layout.addLayout(btn_layout, 1)
                group_layout.addWidget(field_frame)
            
            group_box.setLayout(group_layout)
            layout.addWidget(group_box)
        
        layout.addStretch()
        
        # 底部按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def _parse_ids(self, field_value):
        """解析字段值中的 ID 列表"""
        if not field_value or str(field_value).strip().upper() in ('NULL', 'NONE', ''):
            return []
        value_str = str(field_value).strip()
        return [id_str.strip() for id_str in value_str.split('|') if id_str.strip()]
    
    def _add_ids(self, field_name, list_widget, new_ids):
        """添加 ID 到列表"""
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
            # 排序列表
            self._sort_list_widget(list_widget)
    
    def _remove_selected_ids(self, field_name, list_widget):
        """删除选中的 ID"""
        selected_items = list_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "提示", "请先在列表中选中要删除的 ID")
            return
        
        for item in selected_items:
            list_widget.takeItem(list_widget.row(item))
    
    def _clear_ids(self, field_name, list_widget):
        """清空所有 ID"""
        if list_widget.count() == 0:
            return
        
        reply = QMessageBox.question(
            self, 
            "确认", 
            "确定要清空 {} 字段的所有 ID 吗？".format(field_name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            list_widget.clear()
    
    def _sort_list_widget(self, list_widget):
        """对列表项进行排序"""
        items = []
        for i in range(list_widget.count()):
            items.append(list_widget.item(i).text())
        
        list_widget.clear()
        for item_text in sorted(items):
            list_widget.addItem(item_text)
    
    def get_updates(self):
        """获取所有字段的更新值"""
        updates = {}
        
        for field_name, list_widget in self.field_widgets.items():
            ids = []
            for i in range(list_widget.count()):
                ids.append(list_widget.item(i).text())
            
            if ids:
                updates[field_name] = '|'.join(ids)
            else:
                updates[field_name] = None
        
        return updates


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
