# -*- coding: utf-8 -*-
"""
安全岛与不可通行区域自动关联工具
自动检测紧贴着SAFETYISLAND的PROHIBITED_AREA，并将其ID填入SAFETYISLAND的PILLARS字段
"""
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsFeatureRequest, QgsSpatialIndex, QgsGeometry


class SafetyIslandRelationController:
    def __init__(self, iface, plugin_dir):
        self.iface = iface
        self.plugin_dir = plugin_dir
    
    def run(self):
        """执行安全岛与不可通行区域的自动关联"""
        # 查找图层
        safety_island_layer = None
        prohibited_area_layer = None
        
        for layer in QgsProject.instance().mapLayers().values():
            if hasattr(layer, 'name'):
                layer_name = layer.name().upper()
                if 'SAFETYISLAND' in layer_name:
                    safety_island_layer = layer
                elif 'PROHIBITED_AREA' in layer_name or 'PROHIBITEDAREA' in layer_name:
                    prohibited_area_layer = layer
        
        # 检查图层是否存在
        if safety_island_layer is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "图层缺失",
                "未找到 SAFETYISLAND 图层，请确保图层已加载。"
            )
            return
        
        if prohibited_area_layer is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "图层缺失",
                "未找到 PROHIBITED_AREA 图层，请确保图层已加载。"
            )
            return
        
        # 检查必需的字段
        si_fields = safety_island_layer.fields()
        pa_fields = prohibited_area_layer.fields()
        
        if si_fields.indexFromName('ID') < 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "字段缺失",
                "SAFETYISLAND 图层缺少 ID 字段。"
            )
            return
        
        if si_fields.indexFromName('PILLARS') < 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "字段缺失",
                "SAFETYISLAND 图层缺少 PILLARS 字段。"
            )
            return
        
        if pa_fields.indexFromName('ID') < 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "字段缺失",
                "PROHIBITED_AREA 图层缺少 ID 字段。"
            )
            return
        
        # 开始处理
        self._process_relations(safety_island_layer, prohibited_area_layer)
    
    def _process_relations(self, safety_island_layer, prohibited_area_layer):
        """处理安全岛与不可通行区域的关联关系"""
        # 创建进度对话框
        progress = QProgressDialog(
            "正在检测安全岛与不可通行区域的关联关系...",
            "取消",
            0,
            safety_island_layer.featureCount(),
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setWindowTitle("自动关联")
        
        # 构建 PROHIBITED_AREA 的空间索引
        pa_index = QgsSpatialIndex(prohibited_area_layer.getFeatures())
        
        # 开启编辑模式
        if not safety_island_layer.isEditable():
            if not safety_island_layer.startEditing():
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "编辑失败",
                    "无法开启 SAFETYISLAND 图层的编辑模式。"
                )
                progress.close()
                return
        
        pillars_field_index = safety_island_layer.fields().indexFromName('PILLARS')
        updated_count = 0
        skipped_count = 0
        
        try:
            # 遍历所有安全岛要素
            for index, si_feature in enumerate(safety_island_layer.getFeatures()):
                if progress.wasCanceled():
                    break
                
                progress.setValue(index)
                
                si_geom = si_feature.geometry()
                if si_geom is None or si_geom.isEmpty():
                    skipped_count += 1
                    continue
                
                # 查找紧贴着的 PROHIBITED_AREA（使用 touches 或 intersects）
                candidate_ids = pa_index.intersects(si_geom.boundingBox())
                
                touching_pa_ids = []
                for pa_fid in candidate_ids:
                    pa_feature = prohibited_area_layer.getFeature(pa_fid)
                    pa_geom = pa_feature.geometry()
                    
                    if pa_geom is None or pa_geom.isEmpty():
                        continue
                    
                    # 检查是否紧贴（touches）或相交（intersects）
                    if si_geom.touches(pa_geom) or si_geom.intersects(pa_geom):
                        pa_id = pa_feature.attribute('ID')
                        if pa_id is not None and pa_id != '':
                            touching_pa_ids.append(str(pa_id))
                
                # 如果找到了紧贴的 PROHIBITED_AREA，更新 PILLARS 字段
                if touching_pa_ids:
                    # 去重并排序
                    touching_pa_ids = sorted(set(touching_pa_ids), key=lambda x: (len(x), x))
                    pillars_value = '|'.join(touching_pa_ids)
                    
                    # 更新字段
                    safety_island_layer.changeAttributeValue(
                        si_feature.id(),
                        pillars_field_index,
                        pillars_value
                    )
                    updated_count += 1
                    
                    print(f"[DEBUG] SAFETYISLAND ID={si_feature.attribute('ID')}: "
                          f"PILLARS={pillars_value}")
            
            progress.setValue(safety_island_layer.featureCount())
            
            # 提交更改
            if safety_island_layer.commitChanges():
                QMessageBox.information(
                    self.iface.mainWindow(),
                    "关联完成",
                    f"成功更新 {updated_count} 个安全岛要素。\n"
                    f"跳过 {skipped_count} 个无效要素。"
                )
            else:
                errors = safety_island_layer.commitErrors()
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "提交失败",
                    f"无法提交更改：\n" + "\n".join(errors)
                )
                safety_island_layer.rollBack()
        
        except Exception as e:
            safety_island_layer.rollBack()
            QMessageBox.critical(
                self.iface.mainWindow(),
                "处理错误",
                f"处理过程中发生错误：\n{str(e)}"
            )
        finally:
            progress.close()
