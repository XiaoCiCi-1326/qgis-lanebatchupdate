# -*- coding: utf-8 -*-
"""
要素关联管理器
支持 LANE 图层字段关联到其他图层要素的高亮、选择、赋值
"""
import os
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.core import (
    QTL,
    QTL,
    QTL,
)


class FeatureRelationController(QObject):
    """要素关联控制器"""
    
    # 字段到图层的映射规则
    FIELD_LAYER_MAP = {
        'BDY_L': 'BOUNDARY',
        'BDY_R': 'BOUNDARY',
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
        self.project = QTL.instance()
        self.highlight_mode = False
        self.actions = []
    
    def initGui(self, actions_master):
        entries = (
            (u"关联高亮", "icon_relation_highlight.svg", self.toggle_highlight),
            (u"关联选择", "icon_relation_select.svg", self.select_related),
            (u"关联赋值", "icon_relation_assign.svg", self.assign_relation),
        )
        
        for label, icon_name, callback in entries:
            icon_path = os.path.join(self.plugin_dir, icon_name)
            action = QAction(QIcon(icon_path), label, self.iface.mainWindow())
            action.triggered.connect(callback)
            self.iface.addPluginToVectorMenu(u"车道处理工具", action)
            self.actions.append(action)
            actions_master.append(action)
    
    def unload(self):
        if self.highlight_mode:
            self._remove_selection_listener()
        for action in self.actions:
            try:
                self.iface.removePluginMenu(u"车道处理工具", action)
            except:
                pass
        self.actions = []
    
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
                expression = '"ID" = \'{}\''.format(feature_id)
                request = QTL(expression)
                
                for feature in target_layer.getFeatures(request):
                    if layer_name not in related:
                        related[layer_name] = []
                    related[layer_name].append((feature.id(), field_name))
                    break
        
        return related
    
    def toggle_highlight(self):
        self.highlight_mode = not self.highlight_mode
        
        if self.highlight_mode:
            self.status_changed.emit("关联高亮已启用")
            self._setup_selection_listener()
            self._on_lane_selection_changed()
        else:
            self.status_changed.emit("关联高亮已禁用")
            self._remove_selection_listener()
    
    def _setup_selection_listener(self):
        lane_layer = self._get_lane_layer()
        if not lane_layer:
            self.status_changed.emit("未找到 LANE 图层")
            return
        lane_layer.selectionChanged.connect(self._on_lane_selection_changed)
    
    def _remove_selection_listener(self):
        lane_layer = self._get_lane_layer()
        if not lane_layer:
            return
        try:
            lane_layer.selectionChanged.disconnect(self._on_lane_selection_changed)
        except:
            pass
    
    def _on_lane_selection_changed(self):
        if not self.highlight_mode:
            return
        
        lane_layer = self._get_lane_layer()
        if not lane_layer:
            return
        
        selected_features = lane_layer.selectedFeatures()
        if not selected_features:
            return
        
        total_highlighted = 0
        for lane_feature in selected_features:
            related = self._get_related_features(lane_feature)
            for layer_name, feature_infos in related.items():
                target_layer = self._get_target_layer(layer_name)
                if not target_layer:
                    continue
                
                feature_ids = [fid for fid, _ in feature_infos]
                if feature_ids:
                    self.iface.mapCanvas().flashFeatureIds(
                        target_layer,
                        feature_ids,
                        QColor(255, 255, 0, 200),
                        QColor(255, 200, 0, 100),
                        flashes=3,
                        duration=1000
                    )
                    total_highlighted += len(feature_ids)
        
        if total_highlighted > 0:
            self.status_changed.emit("已高亮 {} 个关联要素".format(total_highlighted))
    
    def select_related(self):
        lane_layer = self._get_lane_layer()
        if not lane_layer:
            QMessageBox.warning(None, "错误", "未找到 LANE 图层")
            return
        
        selected_features = lane_layer.selectedFeatures()
        if not selected_features:
            QMessageBox.warning(None, "提示", "请先选中 LANE 要素")
            return
        
        layer_selections = {}
        
        for lane_feature in selected_features:
            related = self._get_related_features(lane_feature)
            
            for layer_name, feature_infos in related.items():
                if layer_name not in layer_selections:
                    layer_selections[layer_name] = []
                
                for fid, _ in feature_infos:
                    if fid not in layer_selections[layer_name]:
                        layer_selections[layer_name].append(fid)
        
        total_count = 0
        for layer_name, feature_ids in layer_selections.items():
            target_layer = self._get_target_layer(layer_name)
            if target_layer:
                target_layer.selectByIds(feature_ids, QTL.AddToSelection)
                total_count += len(feature_ids)
        
        if total_count > 0:
            self.status_changed.emit("已选中 {} 个关联要素".format(total_count))
        else:
            QMessageBox.information(None, "提示", "当前 LANE 要素没有关联要素")
    
    def assign_relation(self):
        lane_layer = self._get_lane_layer()
        if not lane_layer:
            QMessageBox.warning(None, "错误", "未找到 LANE 图层")
            return
        
        lane_features = lane_layer.selectedFeatures()
        if not lane_features:
            QMessageBox.warning(None, "提示", "请先选中 LANE 要素")
            return
        
        if len(lane_features) > 1:
            QMessageBox.warning(None, "提示", "关联赋值仅支持单个 LANE 要素，请只选中一个")
            return
        
        lane_feature = lane_features[0]
        
        layer_selections = {}
        for layer_name in set(self.FIELD_LAYER_MAP.values()):
            target_layer = self._get_target_layer(layer_name)
            if not target_layer:
                continue
            selected = target_layer.selectedFeatures()
            if selected:
                layer_selections[layer_name] = selected
        
        if not layer_selections:
            QMessageBox.warning(None, "提示", "请先选中要关联的要素（BOUNDARY/LANE/SIGNAL）")
            return
        
        lane_field_names = {f.name().upper(): f.name() for f in lane_layer.fields()}
        
        if not lane_layer.startEditing():
            QMessageBox.critical(None, "错误", "无法开启编辑模式")
            return
        
        updates = {}
        
        for field_name_upper, layer_name in self.FIELD_LAYER_MAP.items():
            if layer_name not in layer_selections:
                continue
            
            field_name = lane_field_names.get(field_name_upper)
            if not field_name:
                continue
            
            ids = []
            for feature in layer_selections[layer_name]:
                feature_id = feature.attribute('ID')
                if feature_id and str(feature_id).strip().upper() not in ('NULL', 'NONE', ''):
                    ids.append(str(feature_id))
            
            if ids:
                updates[field_name] = '|'.join(ids)
        
        if updates:
            for field_name, value in updates.items():
                field_idx = lane_layer.fields().indexOf(field_name)
                if field_idx >= 0:
                    lane_layer.changeAttributeValue(lane_feature.id(), field_idx, value)
            
            if lane_layer.commitChanges():
                self.status_changed.emit("已更新 {} 个字段".format(len(updates)))
            else:
                lane_layer.rollBack()
                QMessageBox.critical(None, "错误", "保存失败")
        else:
            lane_layer.rollBack()
            QMessageBox.information(None, "提示", "没有找到有效的 ID 可以赋值")
