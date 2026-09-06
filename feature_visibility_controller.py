# -*- coding: utf-8 -*-
"""Feature visibility control - show/hide features on canvas."""
import os
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import QAction, QMenu
from qgis.core import Qgis, QgsProject, QgsVectorLayer, QgsFeatureRequest
from qgis.gui import QgsMapCanvas

MENU_NAME = u"车道处理工具"


class FeatureVisibilityController:
    """Control feature visibility on canvas."""

    def __init__(self, iface, plugin_dir):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.action = None
        self.menu = None
        # 存储每个图层的隐藏要素 ID: {layer_id: set(feature_ids)}
        self.hidden_features = {}
        # 记录每个图层原始的 subset string
        self.original_subsets = {}
        # 记录每个图层原始的渲染器（用于编辑模式恢复）
        self.original_renderers = {}

    def initGui(self, actions_master):
        # 创建主菜单按钮
        self.action = QAction(
            QIcon(os.path.join(self.plugin_dir, "icon_feature_visibility.svg")),
            u"要素显隐控制",
            self.iface.mainWindow()
        )

        # 创建下拉菜单
        self.menu = QMenu()

        # 隐藏所选
        hide_selected = QAction(
            QIcon(os.path.join(self.plugin_dir, "icon_hide_selected.svg")),
            u"隐藏选中要素",
            self.iface.mainWindow()
        )
        hide_selected.triggered.connect(self.hide_selected)
        self.menu.addAction(hide_selected)

        # 显示所选
        show_selected = QAction(
            QIcon(os.path.join(self.plugin_dir, "icon_show_selected.svg")),
            u"显示选中要素",
            self.iface.mainWindow()
        )
        show_selected.triggered.connect(self.show_selected)
        self.menu.addAction(show_selected)

        # 切换所选
        toggle_selected = QAction(
            QIcon(os.path.join(self.plugin_dir, "icon_toggle_selected.svg")),
            u"切换选中要素",
            self.iface.mainWindow()
        )
        toggle_selected.triggered.connect(self.toggle_selected)
        self.menu.addAction(toggle_selected)

        self.menu.addSeparator()

        # 仅显示所选
        show_only_selected = QAction(
            QIcon(os.path.join(self.plugin_dir, "icon_show_only_selected.svg")),
            u"仅显示选中要素",
            self.iface.mainWindow()
        )
        show_only_selected.triggered.connect(self.show_only_selected)
        self.menu.addAction(show_only_selected)

        # 隐藏未选中
        hide_unselected = QAction(
            QIcon(os.path.join(self.plugin_dir, "icon_hide_unselected.svg")),
            u"隐藏未选中要素",
            self.iface.mainWindow()
        )
        hide_unselected.triggered.connect(self.hide_unselected)
        self.menu.addAction(hide_unselected)

        self.menu.addSeparator()

        # 显示全部
        show_all = QAction(
            QIcon(os.path.join(self.plugin_dir, "icon_show_all.svg")),
            u"显示当前图层全部要素",
            self.iface.mainWindow()
        )
        show_all.triggered.connect(self.show_all)
        self.menu.addAction(show_all)

        # 显示所有图层的全部要素
        show_all_layers = QAction(
            QIcon(os.path.join(self.plugin_dir, "icon_show_all_layers.svg")),
            u"显示所有图层全部要素",
            self.iface.mainWindow()
        )
        show_all_layers.triggered.connect(self.show_all_layers)
        self.menu.addAction(show_all_layers)

        self.action.setMenu(self.menu)
        self.iface.addPluginToVectorMenu(MENU_NAME, self.action)
        actions_master.append(self.action)

    def unload(self):
        if self.action:
            try:
                self.iface.removePluginMenu(MENU_NAME, self.action)
            except (AttributeError, RuntimeError):
                pass
        self.show_all_layers()

    def hide_selected(self):
        """隐藏选中的要素"""
        layer = self.iface.activeLayer()
        if not self._check_layer(layer):
            return

        selected = layer.selectedFeatures()
        if not selected:
            self._warning(u"要素显隐", u"请先选择要隐藏的要素")
            return

        layer_id = layer.id()
        if layer_id not in self.hidden_features:
            self.hidden_features[layer_id] = set()

        for feat in selected:
            self.hidden_features[layer_id].add(feat.id())

        self._apply_visibility(layer)
        self._message(u"要素显隐", u"已隐藏 %d 个要素" % len(selected))

    def show_selected(self):
        """显示选中的要素"""
        layer = self.iface.activeLayer()
        if not self._check_layer(layer):
            return

        selected = layer.selectedFeatures()
        if not selected:
            self._warning(u"要素显隐", u"请先选择要显示的要素")
            return

        layer_id = layer.id()
        if layer_id in self.hidden_features:
            for feat in selected:
                self.hidden_features[layer_id].discard(feat.id())

            self._apply_visibility(layer)
            self._message(u"要素显隐", u"已显示 %d 个要素" % len(selected))

    def toggle_selected(self):
        """切换选中要素的可见性"""
        layer = self.iface.activeLayer()
        if not self._check_layer(layer):
            return

        selected = layer.selectedFeatures()
        if not selected:
            self._warning(u"要素显隐", u"请先选择要切换的要素")
            return

        layer_id = layer.id()
        if layer_id not in self.hidden_features:
            self.hidden_features[layer_id] = set()

        hidden_count = 0
        shown_count = 0

        for feat in selected:
            fid = feat.id()
            if fid in self.hidden_features[layer_id]:
                self.hidden_features[layer_id].discard(fid)
                shown_count += 1
            else:
                self.hidden_features[layer_id].add(fid)
                hidden_count += 1

        self._apply_visibility(layer)
        self._message(u"要素显隐", u"已隐藏 %d 个，显示 %d 个" % (hidden_count, shown_count))

    def show_only_selected(self):
        """仅显示选中的要素（隐藏其他所有）"""
        layer = self.iface.activeLayer()
        if not self._check_layer(layer):
            return

        selected = layer.selectedFeatures()
        if not selected:
            self._warning(u"要素显隐", u"请先选择要保留显示的要素")
            return

        layer_id = layer.id()
        selected_ids = {feat.id() for feat in selected}

        # 隐藏所有未选中的要素
        all_ids = {feat.id() for feat in layer.getFeatures()}
        self.hidden_features[layer_id] = all_ids - selected_ids

        self._apply_visibility(layer)
        self._message(u"要素显隐", u"仅显示 %d 个要素" % len(selected))

    def hide_unselected(self):
        """隐藏未选中的要素"""
        layer = self.iface.activeLayer()
        if not self._check_layer(layer):
            return

        selected = layer.selectedFeatures()
        if not selected:
            self._warning(u"要素显隐", u"请先选择要保留的要素")
            return

        layer_id = layer.id()
        if layer_id not in self.hidden_features:
            self.hidden_features[layer_id] = set()

        selected_ids = {feat.id() for feat in selected}
        all_ids = {feat.id() for feat in layer.getFeatures()}
        unselected_ids = all_ids - selected_ids

        self.hidden_features[layer_id].update(unselected_ids)

        self._apply_visibility(layer)
        self._message(u"要素显隐", u"已隐藏 %d 个未选中要素" % len(unselected_ids))

    def show_all(self):
        """显示当前图层的全部要素"""
        layer = self.iface.activeLayer()
        if not self._check_layer(layer):
            return

        layer_id = layer.id()
        if layer_id in self.hidden_features:
            count = len(self.hidden_features[layer_id])
            self.hidden_features[layer_id].clear()
            self._apply_visibility(layer)
            self._message(u"要素显隐", u"已显示全部要素（恢复 %d 个）" % count)

    def show_all_layers(self):
        """显示所有图层的全部要素"""
        count = 0
        for layer_id in list(self.hidden_features.keys()):
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer and isinstance(layer, QgsVectorLayer):
                count += len(self.hidden_features[layer_id])
                self.hidden_features[layer_id].clear()
                self._apply_visibility(layer)

        if count > 0:
            self._message(u"要素显隐", u"已显示所有图层全部要素（恢复 %d 个）" % count)

    def _check_layer(self, layer):
        """检查图层是否有效"""
        if not isinstance(layer, QgsVectorLayer):
            self._warning(u"要素显隐", u"请先选择一个矢量图层")
            return False
        return True

    def _apply_visibility(self, layer):
        """应用可见性设置 - 兼容编辑模式"""
        layer_id = layer.id()
        hidden_ids = self.hidden_features.get(layer_id, set())

        if layer.isEditable():
            # 编辑模式：使用图层刷新函数过滤渲染
            self._apply_visibility_edit_mode(layer, hidden_ids)
        else:
            # 非编辑模式：使用 subset string（更高效）
            self._apply_visibility_normal_mode(layer, hidden_ids)

        # 刷新显示
        try:
            layer.triggerRepaint()
            self.iface.mapCanvas().refresh()
        except Exception:
            pass

    def _apply_visibility_edit_mode(self, layer, hidden_ids):
        """编辑模式下的显隐实现 - 使用规则渲染器"""
        from qgis.core import QgsRuleBasedRenderer, QgsSymbol, QgsMarkerSymbol, QgsLineSymbol, QgsFillSymbol
        
        layer_id = layer.id()
        
        if not hidden_ids:
            # 恢复原始渲染器
            if layer_id in self.original_renderers:
                try:
                    layer.setRenderer(self.original_renderers[layer_id].clone())
                    del self.original_renderers[layer_id]
                except Exception as e:
                    self._warning(u"要素显隐", u"恢复渲染器失败: %s" % str(e))
            return
        
        try:
            # 保存原始渲染器（第一次修改时）
            if layer_id not in self.original_renderers:
                self.original_renderers[layer_id] = layer.renderer().clone()
            
            # 构建过滤表达式 - 只显示未隐藏的要素
            id_list = ",".join(str(fid) for fid in hidden_ids)
            filter_expr = "$id NOT IN (%s)" % id_list
            
            # 获取原始渲染器
            original_renderer = self.original_renderers[layer_id]
            
            # 如果原始渲染器已经是规则渲染器，直接在根规则上添加过滤表达式
            if isinstance(original_renderer, QgsRuleBasedRenderer):
                rule_renderer = original_renderer.clone()
                root_rule = rule_renderer.rootRule()
                # 为根规则添加过滤条件
                if root_rule and root_rule.children():
                    # 遍历所有子规则，添加过滤表达式
                    for child in root_rule.children():
                        existing_filter = child.filterExpression()
                        if existing_filter:
                            child.setFilterExpression("(%s) AND (%s)" % (existing_filter, filter_expr))
                        else:
                            child.setFilterExpression(filter_expr)
                else:
                    # 根规则没有子规则，添加过滤到根规则
                    if root_rule:
                        root_rule.setFilterExpression(filter_expr)
            else:
                # 对于非规则渲染器，创建一个规则包装它
                # 获取默认符号
                symbol = None
                try:
                    if hasattr(original_renderer, 'symbol'):
                        symbol = original_renderer.symbol()
                        if symbol:
                            symbol = symbol.clone()
                except Exception:
                    pass
                
                # 如果无法获取符号，根据图层几何类型创建默认符号
                if not symbol:
                    from qgis.core import QgsWkbTypes
                    geom_type = layer.geometryType()
                    if geom_type == QgsWkbTypes.PointGeometry:
                        symbol = QgsMarkerSymbol.createSimple({})
                    elif geom_type == QgsWkbTypes.LineGeometry:
                        symbol = QgsLineSymbol.createSimple({})
                    elif geom_type == QgsWkbTypes.PolygonGeometry:
                        symbol = QgsFillSymbol.createSimple({})
                
                if not symbol:
                    self._warning(u"要素显隐", u"无法获取图层符号，编辑模式下暂不支持显隐")
                    return
                
                # 创建根规则
                root_rule = QgsRuleBasedRenderer.Rule(None)
                
                # 添加显示规则
                visible_rule = QgsRuleBasedRenderer.Rule(symbol.clone())
                visible_rule.setFilterExpression(filter_expr)
                visible_rule.setLabel(u"可见要素")
                root_rule.appendChild(visible_rule)
                
                # 创建规则渲染器
                rule_renderer = QgsRuleBasedRenderer(root_rule)
            
            layer.setRenderer(rule_renderer)
            self._message(u"要素显隐", u"编辑模式下使用渲染器过滤", duration=2)
            
        except Exception as e:
            self._warning(u"要素显隐", u"编辑模式下设置显隐失败: %s" % str(e))
            # 清除记录
            if layer_id in self.hidden_features:
                self.hidden_features[layer_id].clear()
            if layer_id in self.original_renderers:
                del self.original_renderers[layer_id]

    def _apply_visibility_normal_mode(self, layer, hidden_ids):
        """非编辑模式下的显隐实现 - 使用 subset string"""
        layer_id = layer.id()
        
        # 保存原始的 subset string（第一次修改时）
        if layer_id not in self.original_subsets and hidden_ids:
            self.original_subsets[layer_id] = layer.subsetString()

        if not hidden_ids:
            # 没有隐藏的要素，恢复原始过滤
            original_subset = self.original_subsets.get(layer_id, "")
            try:
                layer.setSubsetString(original_subset)
                if layer_id in self.original_subsets:
                    del self.original_subsets[layer_id]
            except Exception as e:
                self._warning(u"要素显隐", u"恢复过滤失败: %s" % str(e))
                return
        else:
            # 构建过滤表达式
            id_list = ",".join(str(fid) for fid in hidden_ids)
            
            # 获取原始过滤条件
            original_subset = self.original_subsets.get(layer_id, "")
            
            # 尝试不同的 ID 字段表达式
            expressions_to_try = [
                "$id NOT IN (%s)" % id_list,
                '"fid" NOT IN (%s)' % id_list,
                'fid NOT IN (%s)' % id_list,
                '"ogc_fid" NOT IN (%s)' % id_list,
            ]
            
            success = False
            for hide_filter in expressions_to_try:
                try:
                    if original_subset:
                        new_filter = "(%s) AND (%s)" % (original_subset, hide_filter)
                    else:
                        new_filter = hide_filter
                    
                    layer.setSubsetString(new_filter)
                    
                    # 验证是否设置成功
                    if layer.subsetString():
                        success = True
                        break
                except Exception:
                    continue
            
            if not success:
                self._warning(
                    u"要素显隐", 
                    u"当前数据源不支持过滤，请尝试其他图层格式（如 GeoPackage）"
                )
                # 清除隐藏记录
                layer_id = layer.id()
                if layer_id in self.hidden_features:
                    self.hidden_features[layer_id].clear()
                if layer_id in self.original_subsets:
                    del self.original_subsets[layer_id]

    def _message(self, title, text, duration=2):
        self.iface.messageBar().pushMessage(
            title, text, level=Qgis.Info, duration=duration
        )

    def _warning(self, title, text):
        self.iface.messageBar().pushMessage(
            title, text, level=Qgis.Warning, duration=3
        )
