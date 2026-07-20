# -*- coding: utf-8 -*-
"""一键重构核心流程（第一次 / 第二次）。"""

import gc
import os
import shutil
import time

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from .reconstruct_config import DIR_DELETE_129, DIR_DELETE_NOT_11, DIR_ORIGINAL
from .reconstruct_processing import ReconstructProcessing


class ReconstructWorkflow:
    """数据复制、BOUNDARY 筛选、6~9 步处理、字段重构与 LANE 回写。"""

    def __init__(self, iface, plugin_dir, log_fn):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.log = log_fn
        self.data_dir = ""

    @staticmethod
    def work_dir_names():
        return {DIR_ORIGINAL, DIR_DELETE_129, DIR_DELETE_NOT_11}

    def work_dir_paths(self):
        return (
            os.path.join(self.plugin_dir, DIR_ORIGINAL),
            os.path.join(self.plugin_dir, DIR_DELETE_129),
            os.path.join(self.plugin_dir, DIR_DELETE_NOT_11),
        )

    def is_plugin_work_dir(self, folder):
        """是否为插件目录下的三份副本文件夹（不能当作原始数据源）。"""
        folder = os.path.normcase(os.path.normpath(folder))
        plugin = os.path.normcase(os.path.normpath(self.plugin_dir))
        if not folder.startswith(plugin + os.sep) and folder != plugin:
            return False
        rel = os.path.relpath(folder, plugin)
        top = rel.split(os.sep)[0]
        return top in self.work_dir_names()

    def workdirs_ready(self):
        """三份副本目录均已存在且含 shp。"""
        for folder in self.work_dir_paths():
            if not os.path.isdir(folder):
                return False
            has_shp = any(
                name.lower().endswith(".shp") for name in os.listdir(folder)
            )
            if not has_shp:
                return False
        return True

    @staticmethod
    def is_empty(value):
        if value is None:
            return True
        text = str(value).strip()
        return text in ("", "None", "NULL")

    @staticmethod
    def norm_id(value):
        if ReconstructWorkflow.is_empty(value):
            return ""
        text = str(value).strip()
        try:
            num = float(text)
            if num == int(num):
                return str(int(num))
        except (TypeError, ValueError):
            pass
        return text

    @staticmethod
    def layer_path(layer):
        src = layer.source()
        if "|" in src:
            src = src.split("|", 1)[0]
        return os.path.normpath(src)

    @staticmethod
    def resolve_field(layer, logical_name):
        upper = logical_name.upper()
        for field in layer.fields():
            if field.name().upper() == upper:
                return field.name()
        return None

    def detect_data_dir(self):
        """从当前工程矢量图层推断数据文件夹（跳过插件内三份副本）。"""
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                folder = os.path.dirname(self.layer_path(layer))
                if not os.path.isdir(folder):
                    continue
                if self.is_plugin_work_dir(folder):
                    continue
                return folder
        return None

    def resolve_source_dir(self, picked_dir=None, require_source=False):
        """
        确定用于复制的源目录。
        picked_dir: 用户在对话框中选择的目录（可为 None）。
        require_source: 为 True 时必须有外部源目录（准备三份数据用）。
        """
        if picked_dir:
            folder = os.path.normpath(picked_dir)
            if not os.path.isdir(folder):
                raise RuntimeError(f"目录不存在: {folder}")
            if self.is_plugin_work_dir(folder):
                raise RuntimeError(
                    "不能选择插件内的「原始文件/删除129/删除11以外」作为源。\n"
                    "请加载或选择您的原始数据文件夹。"
                )
            return folder

        detected = self.detect_data_dir()
        if detected:
            return detected

        if not require_source and self.workdirs_ready():
            return None

        raise RuntimeError(
            "未检测到原始数据目录。\n"
            "请先在 QGIS 中加载原始数据下的 shp，或点击确定后选择数据文件夹。"
        )

    def unload_layers_in_dir(self, folder):
        """卸载工程内指向某目录下文件的图层，避免 Windows 文件锁。"""
        folder_key = os.path.normcase(os.path.normpath(folder))
        remove_ids = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            path = os.path.normcase(os.path.normpath(self.layer_path(layer)))
            if path.startswith(folder_key + os.sep) or path == folder_key:
                remove_ids.append(layer.id())
        if remove_ids:
            QgsProject.instance().removeMapLayers(remove_ids)

    def unload_layers_in_workdirs(self):
        for folder in self.work_dir_paths():
            self.unload_layers_in_dir(folder)

    def safe_rmtree(self, path, retries=8):
        """删除目录，Windows 下 QGIS 释放句柄可能需要短暂重试。"""
        if not os.path.isdir(path):
            return
        last_err = None
        for attempt in range(retries):
            try:
                shutil.rmtree(path)
                return
            except PermissionError as exc:
                last_err = exc
                gc.collect()
                time.sleep(0.4 * (attempt + 1))
        raise PermissionError(
            f"无法删除目录（文件可能被 QGIS 占用）: {path}\n"
            f"请关闭对该目录图层的加载后重试。原始错误: {last_err}"
        )

    def copy_three_workdirs(self, source_dir):
        """将源目录全部文件复制三份到插件根目录（经临时目录，避免删源）。"""
        source_dir = os.path.normpath(source_dir)
        if not os.path.isdir(source_dir):
            raise RuntimeError(f"源目录不存在: {source_dir}")

        targets = self.work_dir_paths()
        staging = os.path.join(self.plugin_dir, "_copy_staging")

        self.remove_all_layers()
        self.unload_layers_in_workdirs()
        self.iface.mapCanvas().refresh()
        gc.collect()
        time.sleep(0.3)

        self.safe_rmtree(staging)
        shutil.copytree(source_dir, staging)
        try:
            for target in targets:
                self.unload_layers_in_dir(target)
                self.safe_rmtree(target)
                shutil.copytree(staging, target)
                self.log(f"已复制到: {target}", show_bar=False)
        finally:
            if os.path.isdir(staging):
                shutil.rmtree(staging, ignore_errors=True)
        return targets[0], targets[1], targets[2]

    def remove_all_layers(self):
        QgsProject.instance().removeAllMapLayers()
        self.iface.mapCanvas().refresh()

    def load_all_shp_in_dir(self, folder):
        """加载目录下全部 shp。"""
        loaded = []
        if not os.path.isdir(folder):
            raise RuntimeError(f"目录不存在: {folder}")
        names = sorted(name for name in os.listdir(folder) if name.lower().endswith(".shp"))
        if not names:
            raise RuntimeError(f"目录无 shp 文件: {folder}")
        for name in names:
            path = os.path.join(folder, name)
            base = os.path.splitext(name)[0]
            layer = QgsVectorLayer(path, base, "ogr")
            if not layer.isValid():
                raise RuntimeError(f"无法加载: {path}")
            QgsProject.instance().addMapLayer(layer)
            loaded.append(layer)
            self.log(f"已加载图层: {base}", show_bar=False)
        return loaded

    def get_layer_by_name(self, name):
        project = QgsProject.instance()
        layers = project.mapLayersByName(name)
        if layers:
            return layers[0]
        target = name.upper()
        for layer in project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.name().upper() == target:
                return layer
        return None

    def delete_boundary_by_type(self, pass_number):
        """第一次删 TYPE=1/2/9；第二次仅保留 TYPE=11。"""
        boundary = self.get_layer_by_name("BOUNDARY")
        if boundary is None:
            raise RuntimeError("未找到 BOUNDARY 图层")
        type_field = self.resolve_field(boundary, "TYPE")
        if not type_field:
            raise RuntimeError("BOUNDARY 缺少 TYPE 字段")

        if not boundary.startEditing():
            raise RuntimeError("BOUNDARY 无法进入编辑模式")

        delete_ids = []
        for feat in boundary.getFeatures():
            type_val = feat[type_field]
            try:
                type_int = int(float(type_val)) if not self.is_empty(type_val) else None
            except (TypeError, ValueError):
                type_int = None
            if pass_number == 1:
                if type_int in (1, 2, 9):
                    delete_ids.append(feat.id())
            else:
                if type_int != 11:
                    delete_ids.append(feat.id())

        if delete_ids:
            boundary.deleteFeatures(delete_ids)
        if not boundary.commitChanges():
            boundary.rollBack()
            raise RuntimeError("BOUNDARY 保存失败: " + "; ".join(boundary.commitErrors()))
        self.log(f"BOUNDARY 已删除 {len(delete_ids)} 条要素", show_bar=False)

    def remove_layers_except(self, keep_names):
        keep_upper = {n.upper() for n in keep_names}
        remove_ids = []
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name().upper() not in keep_upper:
                remove_ids.append(layer.id())
        if remove_ids:
            QgsProject.instance().removeMapLayers(remove_ids)

    def extract_refactor_pass1(self, lane_layer):
        """保留 ID/RBDY_L/RBDY_R → ID2/RBDY_L2/RBDY_R2（内存表）。"""
        id_f = self.resolve_field(lane_layer, "ID")
        l_f = self.resolve_field(lane_layer, "RBDY_L")
        r_f = self.resolve_field(lane_layer, "RBDY_R")
        missing = [n for n, f in (("ID", id_f), ("RBDY_L", l_f), ("RBDY_R", r_f)) if not f]
        if missing:
            raise RuntimeError(f"LANE 缺少字段: {', '.join(missing)}")

        table = {}
        for feat in lane_layer.getFeatures():
            key = self.norm_id(feat[id_f])
            if not key:
                continue
            table[key] = (feat[l_f], feat[r_f])
        self.log(f"第一次重构表: {len(table)} 条", show_bar=False)
        return table

    def extract_refactor_pass2(self, lane_layer):
        """保留 ID/RBDY_R → ID2/RBDY_R2。"""
        id_f = self.resolve_field(lane_layer, "ID")
        r_f = self.resolve_field(lane_layer, "RBDY_R")
        if not id_f or not r_f:
            raise RuntimeError("LANE 缺少 ID 或 RBDY_R 字段")

        table = {}
        for feat in lane_layer.getFeatures():
            key = self.norm_id(feat[id_f])
            if not key:
                continue
            table[key] = feat[r_f]
        self.log(f"第二次重构表: {len(table)} 条", show_bar=False)
        return table

    @staticmethod
    def _value_not_empty(value):
        if ReconstructWorkflow.is_empty(value):
            return False
        text = str(value).strip()
        return text not in ("0", "0.0")

    def apply_refactor_to_original_lane(self, original_lane_path, refactor_table, pass_number):
        """将重构结果写回「原始文件」中的 LANE.shp。"""
        layer = QgsVectorLayer(original_lane_path, "LANE", "ogr")
        if not layer.isValid():
            raise RuntimeError(f"无法打开原始 LANE: {original_lane_path}")

        id_f = self.resolve_field(layer, "ID")
        if not id_f:
            raise RuntimeError("原始 LANE 缺少 ID 字段")

        if pass_number == 1:
            l_f = self.resolve_field(layer, "RBDY_L")
            r_f = self.resolve_field(layer, "RBDY_R")
            if not l_f or not r_f:
                raise RuntimeError("原始 LANE 缺少 RBDY_L / RBDY_R")
        else:
            r_f = self.resolve_field(layer, "RBDY_R")
            if not r_f:
                raise RuntimeError("原始 LANE 缺少 RBDY_R")

        if not layer.startEditing():
            raise RuntimeError("原始 LANE 无法进入编辑模式")

        updated = 0
        for feat in layer.getFeatures():
            key = self.norm_id(feat[id_f])
            if key not in refactor_table:
                continue
            if pass_number == 1:
                new_l, new_r = refactor_table[key]
                feat[l_f] = new_l
                feat[r_f] = new_r
                layer.updateFeature(feat)
                updated += 1
            else:
                new_r = refactor_table[key]
                if self._value_not_empty(new_r):
                    feat[r_f] = new_r
                    layer.updateFeature(feat)
                    updated += 1

        if not layer.commitChanges():
            layer.rollBack()
            raise RuntimeError("原始 LANE 保存失败: " + "; ".join(layer.commitErrors()))
        self.log(f"原始 LANE 已更新 {updated} 条", show_bar=False)
        return updated

    def save_refactor_sidecar(self, lane_layer, pass_number, work_dir):
        """可选：把重构表导出为仅含 ID2/RBDY_*2 的 shp 便于检查。"""
        id_f = self.resolve_field(lane_layer, "ID")
        if not id_f:
            return None

        fields = QgsFields()
        fields.append(QgsField("ID2", QVariant.LongLong))
        if pass_number == 1:
            fields.append(QgsField("RBDY_L2", QVariant.String))
            fields.append(QgsField("RBDY_R2", QVariant.String))
        else:
            fields.append(QgsField("RBDY_R2", QVariant.String))

        suffix = "refactor_pass1" if pass_number == 1 else "refactor_pass2"
        out_path = os.path.join(work_dir, f"LANE_{suffix}.shp")
        writer = QgsVectorFileWriter(
            out_path,
            "UTF-8",
            fields,
            lane_layer.wkbType(),
            lane_layer.crs(),
            "ESRI Shapefile",
        )
        if writer.hasError():
            return None

        if pass_number == 1:
            l_f = self.resolve_field(lane_layer, "RBDY_L")
            r_f = self.resolve_field(lane_layer, "RBDY_R")
            for feat in lane_layer.getFeatures():
                f = QgsFeature(fields)
                f.setGeometry(feat.geometry())
                f.setAttribute("ID2", feat[id_f])
                f.setAttribute("RBDY_L2", feat[l_f] if l_f else None)
                f.setAttribute("RBDY_R2", feat[r_f] if r_f else None)
                writer.addFeature(f)
        else:
            r_f = self.resolve_field(lane_layer, "RBDY_R")
            for feat in lane_layer.getFeatures():
                f = QgsFeature(fields)
                f.setGeometry(feat.geometry())
                f.setAttribute("ID2", feat[id_f])
                f.setAttribute("RBDY_R2", feat[r_f] if r_f else None)
                writer.addFeature(f)

        del writer
        return out_path

    def ensure_workdirs(self):
        """三份目录不存在时，从当前工程图层源目录复制。"""
        if self.workdirs_ready():
            return
        source = self.resolve_source_dir()
        if not source:
            raise RuntimeError("三份副本不完整，且未检测到原始数据目录")
        self.copy_three_workdirs(source)

    def run_pass(self, pass_number, feedback, algorithm_ids):
        """执行单次重构（1 或 2）。"""
        if pass_number == 1:
            work_dir = os.path.join(self.plugin_dir, DIR_DELETE_129)
        else:
            work_dir = os.path.join(self.plugin_dir, DIR_DELETE_NOT_11)
        original_dir = os.path.join(self.plugin_dir, DIR_ORIGINAL)
        original_lane = os.path.join(original_dir, "LANE.shp")

        self.log(f"===== 第{pass_number}次重构 工作目录: {work_dir} =====")
        self.remove_all_layers()
        self.load_all_shp_in_dir(work_dir)

        self.delete_boundary_by_type(pass_number)

        processor = ReconstructProcessing(self.iface, algorithm_ids, self.log)
        processor.run_steps_6_to_9(feedback)

        self.remove_layers_except(["BOUNDARY", "LANE"])
        lane = self.get_layer_by_name("LANE")
        if lane is None:
            raise RuntimeError("处理完成后未找到 LANE 图层")

        if pass_number == 1:
            refactor_table = self.extract_refactor_pass1(lane)
        else:
            refactor_table = self.extract_refactor_pass2(lane)

        self.save_refactor_sidecar(lane, pass_number, work_dir)
        self.remove_all_layers()

        if not os.path.isfile(original_lane):
            raise RuntimeError(f"原始文件缺少 LANE.shp: {original_lane}")

        self.apply_refactor_to_original_lane(original_lane, refactor_table, pass_number)
        self.log(f"第{pass_number}次重构完成，结果已写入: {original_lane}")

    def run_full(self, feedback, algorithm_ids, copy_only=False, source_dir=None):
        """复制三份 + 第一次 + 第二次重构。source_dir 可为对话框所选路径。"""
        source = self.resolve_source_dir(source_dir)
        if source:
            self.data_dir = source
            self.log(f"源数据目录: {source}")
            self.copy_three_workdirs(source)
        elif self.workdirs_ready():
            self.log("未加载原始图层，使用已有三份副本继续（跳过复制）")
            self.remove_all_layers()
        else:
            raise RuntimeError(
                "无法开始：请加载原始数据图层、选择数据目录，或先执行「准备三份数据」"
            )

        if copy_only:
            self.log("三份数据已准备完成（仅复制）")
            return

        self.run_pass(1, feedback, algorithm_ids)
        self.run_pass(2, feedback, algorithm_ids)
        self.remove_all_layers()
        self.log("一键重构（两次）全部完成")
