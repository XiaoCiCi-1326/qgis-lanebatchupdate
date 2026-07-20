# -*- coding: utf-8 -*-
"""查找并执行 QGIS 工具栏/菜单动作（步骤 6~9）。"""

import re

from qgis.PyQt.QtWidgets import QAction, QToolBar
from qgis.core import QgsApplication, QgsProject

import processing

from .reconstruct_config import STEP_TOOLBAR


class ReconstructProcessing:
    """按工具栏按钮名称触发 Z Attribute / Z Tools 四步处理。"""

    def __init__(self, iface, algorithm_ids, log_fn):
        self.iface = iface
        self.algorithm_ids = algorithm_ids or {}
        self.log = log_fn

    @staticmethod
    def _normalize_text(text):
        """去掉快捷键、空格、标点，便于匹配菜单/工具栏文字。"""
        if not text:
            return ""
        text = text.replace("&", "")
        text = re.sub(r"[\s,，、/\\|]+", "", text)
        return text.upper()

    def _iter_actions(self):
        """收集主窗口及工具栏上的全部 QAction。"""
        main = self.iface.mainWindow() if self.iface else None
        if not main:
            return
        seen = set()
        for action in main.findChildren(QAction):
            aid = id(action)
            if aid in seen:
                continue
            seen.add(aid)
            yield action
        for toolbar in main.findChildren(QToolBar):
            for action in toolbar.actions():
                aid = id(action)
                if aid in seen:
                    continue
                seen.add(aid)
                yield action

    def _action_matches(self, action, keywords):
        text = action.text() or ""
        tip = action.toolTip() or ""
        status = action.statusTip() or ""
        merged = self._normalize_text(" ".join((text, tip, status)))
        keys = [self._normalize_text(kw) for kw in keywords if kw]
        return merged and all(kw in merged for kw in keys)

    def find_toolbar_action(self, step_key):
        """按步骤配置查找工具栏/菜单按钮。"""
        info = STEP_TOOLBAR.get(step_key)
        if not info:
            return None, None

        label_norm = self._normalize_text(info["label"])
        best = None
        best_score = -1

        for action in self._iter_actions():
            if not action.isEnabled() or not action.text():
                continue
            text_norm = self._normalize_text(action.text())
            if text_norm == label_norm:
                return action, action.text()

            for keywords in info["keyword_groups"]:
                if not self._action_matches(action, keywords):
                    continue
                score = len("".join(keywords))
                if score > best_score:
                    best = action
                    best_score = score

        if best is not None:
            return best, best.text()
        return None, None

    def run_toolbar_step(self, step_key):
        """触发工具栏按钮（与用户手动点击一致）。"""
        info = STEP_TOOLBAR.get(step_key, {})
        action, name = self.find_toolbar_action(step_key)
        if action is None:
            hint = info.get("hint") or info.get("label") or step_key
            return False, f"未找到工具栏按钮: {hint}"
        self.log(f"触发工具栏: {name}", show_bar=False)
        action.trigger()
        return True, name

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
        """可选：从 reconstruct_algorithms.json 读取 Processing 算法。"""
        configured = (self.algorithm_ids.get(step_key) or "").strip()
        if configured:
            alg = QgsApplication.processingRegistry().algorithmById(configured)
            if alg is not None:
                return configured, alg.displayName()
            self.log(f"配置的算法不存在: {configured}", level="WARN")

        info = STEP_TOOLBAR.get(step_key)
        if not info:
            return None, None
        return self._match_algorithm(info["keyword_groups"])

    def select_all_layers(self):
        """选中工程中全部图层（供 Z Attribute / Z Tools 读取选择集）。"""
        layers = [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if layer is not None
        ]
        if not layers or not self.iface:
            return len(layers)

        view = self.iface.layerTreeView()
        if not view:
            return len(layers)

        if hasattr(view, "setSelectedLayers"):
            view.setSelectedLayers(layers)
            return len(layers)

        from qgis.PyQt.QtCore import QItemSelectionModel
        from qgis.PyQt.QtWidgets import QAbstractItemView

        model = view.layerTreeModel()
        if model is None:
            return len(layers)

        old_mode = view.selectionMode()
        sel = view.selectionModel()
        sel.clearSelection()

        selected = 0
        for layer in layers:
            node = model.rootGroup().findLayer(layer.id())
            if node is None:
                continue
            index = model.node2index(node)
            if index.isValid():
                sel.select(index, QItemSelectionModel.Select)
                selected += 1

        if selected == 0:
            view.setSelectionMode(QAbstractItemView.MultiSelection)
            for layer in layers:
                view.setCurrentLayer(layer)
            view.setSelectionMode(old_mode)
        else:
            view.setSelectionMode(old_mode)

        return len(layers)

    def run_step(self, step_key, feedback):
        """执行单步：优先工具栏四按钮，失败再尝试 Processing。"""
        self.select_all_layers()
        count = len(QgsProject.instance().mapLayers())
        self.log(f"已选中 {count} 个图层", show_bar=False)

        ok, name = self.run_toolbar_step(step_key)
        if ok:
            return True, name

        self.log(name, level="WARN")

        alg_id, alg_name = self.resolve_step_algorithm(step_key)
        if alg_id:
            self.log(f"改走 Processing: {alg_name} ({alg_id})", show_bar=False)
            try:
                processing.run(alg_id, {}, feedback=feedback)
                return True, alg_name
            except Exception as exc:
                self.log(f"Processing 失败: {exc}", level="ERROR")

        info = STEP_TOOLBAR.get(step_key, {})
        hint = info.get("hint") or info.get("label") or step_key
        return False, f"未找到工具栏按钮: {hint}"

    def run_steps_6_to_9(self, feedback):
        """依次执行工具栏步骤 6~9。"""
        for step_key in ("step6", "step7", "step8", "step9"):
            info = STEP_TOOLBAR[step_key]
            feedback.setProgressText(f"步骤 {step_key[-1]}: {info['label']} …")
            ok, name = self.run_step(step_key, feedback)
            if not ok:
                raise RuntimeError(
                    f"步骤 {step_key} 执行失败: {name}\n"
                    f"请确认已安装 Z Attribute / Z Tools 插件，且工具栏四个按钮可见。"
                )
            self.log(f"{step_key} 完成: {name}", show_bar=False)
        return True

    def run_steps_8_to_9(self, feedback):
        """收尾：仅执行工具栏步骤 8、9。"""
        for step_key in ("step8", "step9"):
            info = STEP_TOOLBAR[step_key]
            feedback.setProgressText(f"步骤 {step_key[-1]}: {info['label']} …")
            ok, name = self.run_step(step_key, feedback)
            if not ok:
                raise RuntimeError(
                    f"步骤 {step_key} 执行失败: {name}\n"
                    f"请确认 Z Tools 工具栏按钮可见。"
                )
            self.log(f"{step_key} 完成: {name}", show_bar=False)
        return True
