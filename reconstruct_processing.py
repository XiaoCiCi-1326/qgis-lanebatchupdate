# -*- coding: utf-8 -*-
"""查找并执行 QGIS Processing / 菜单动作（步骤 6~9）。"""

from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication, QgsProcessingFeedback, QgsProject

import processing


class ReconstructProcessing:
    """按名称或配置文件调用外部处理工具。"""

    def __init__(self, iface, algorithm_ids, log_fn):
        self.iface = iface
        self.algorithm_ids = algorithm_ids or {}
        self.log = log_fn

    def _match_algorithm(self, keyword_groups):
        registry = QgsApplication.processingRegistry()
        for keywords in keyword_groups:
            if not keywords:
                continue
            for algorithm in registry.algorithms():
                display = algorithm.displayName() or ""
                name_upper = display.upper()
                if all(kw.upper() in name_upper for kw in keywords):
                    return algorithm.id(), display
        return None, None

    def resolve_step_algorithm(self, step_key):
        """优先配置文件，其次按关键字搜索 Processing 算法。"""
        configured = (self.algorithm_ids.get(step_key) or "").strip()
        if configured:
            alg = QgsApplication.processingRegistry().algorithmById(configured)
            if alg is not None:
                return configured, alg.displayName()
            self.log(f"配置的算法不存在: {configured}，改按名称搜索", level="WARN")

        groups = []
        primary = step_key
        alt = f"{step_key}_alt"
        from .reconstruct_config import STEP_KEYWORDS

        if primary in STEP_KEYWORDS:
            groups.append(STEP_KEYWORDS[primary])
        if alt in STEP_KEYWORDS:
            groups.append(STEP_KEYWORDS[alt])
        return self._match_algorithm(groups)

    def select_all_layers(self):
        """选中工程中全部图层（供部分插件读取选择集）。"""
        layers = [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if layer is not None
        ]
        if layers and self.iface.layerTreeView():
            self.iface.layerTreeView().setSelectedLayers(layers)
        return len(layers)

    def run_menu_action(self, keywords):
        """在 QGIS 菜单/工具栏中按文字触发动作。"""
        if not self.iface or not self.iface.mainWindow():
            return False, "无法访问 QGIS 主窗口"
        matches = []
        for action in self.iface.mainWindow().findChildren(QAction):
            text = action.text() or ""
            text_clean = text.replace("&", "")
            if all(kw in text_clean for kw in keywords):
                matches.append(action)
        if not matches:
            return False, f"未找到菜单按钮: {' / '.join(keywords)}"
        action = matches[0]
        self.log(f"触发菜单: {action.text()}", show_bar=False)
        action.trigger()
        return True, action.text()

    def run_step(self, step_key, feedback):
        """执行单个步骤（Processing 优先，失败则尝试菜单）。"""
        self.select_all_layers()
        alg_id, alg_name = self.resolve_step_algorithm(step_key)
        if alg_id:
            self.log(f"Processing: {alg_name} ({alg_id})", show_bar=False)
            try:
                processing.run(alg_id, {}, feedback=feedback)
                return True, alg_name
            except Exception as exc:
                self.log(f"Processing 失败: {exc}", level="ERROR")

        from .reconstruct_config import STEP_KEYWORDS

        keywords = STEP_KEYWORDS.get(step_key) or STEP_KEYWORDS.get(f"{step_key}_alt")
        if keywords:
            ok, msg = self.run_menu_action(keywords)
            if ok:
                return True, msg
            self.log(msg, level="ERROR")
        return False, f"步骤 {step_key} 未找到可用工具"

    def run_steps_6_to_9(self, feedback):
        """依次执行步骤 6~9，每步同步等待完成。"""
        for step_key in ("step6", "step7", "step8", "step9"):
            feedback.setProgressText(f"正在执行 {step_key} …")
            ok, name = self.run_step(step_key, feedback)
            if not ok:
                raise RuntimeError(
                    f"步骤 {step_key} 执行失败: {name}\n"
                    f"请在插件目录配置 reconstruct_algorithms.json 填写算法 ID"
                )
            self.log(f"{step_key} 完成: {name}", show_bar=False)
        return True
