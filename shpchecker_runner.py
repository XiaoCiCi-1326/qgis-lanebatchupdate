# -*- coding: utf-8 -*-
"""在 QGIS 3.16 子进程中运行随插件发布的 shpchecker。"""
from __future__ import annotations

import os
import sys
import time
import traceback

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog, QPushButton
from qgis.core import QgsProject, QgsVectorLayer
from qgis.utils import iface


input_dir = os.environ.get("LANEBATCH_SHPCHECKER_INPUT", "")
vendor_parent = os.environ.get("LANEBATCH_SHPCHECKER_VENDOR", "")
log_path = os.environ.get("LANEBATCH_SHPCHECKER_LOG", "")
log_lines = ["input=%s" % input_dir, "vendor=%s" % vendor_parent]
run_started_at = time.time()


def log(text):
    log_lines.append(str(text))
    if log_path:
        try:
            with open(log_path, "w", encoding="utf-8-sig") as handle:
                handle.write("\n".join(log_lines) + "\n")
        except OSError:
            pass


def load_layers():
    for name in (
        "CLEARAREA", "CROSSWALK", "FREEAREA", "GATE", "INTERSECTION",
        "LANE_GROUP", "LANE_MARKING", "LANE_NODE", "LANE", "PARKING",
        "PILLAR", "PROHIBITED_AREA", "ROAD_LINK", "SAFETYISLAND",
        "SPEEDBUMP", "STOPLINE", "TRAFFICLIGHT",
    ):
        path = os.path.join(input_dir, name + ".shp")
        layer = QgsVectorLayer(path, name, "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            log("loaded %s (%s)" % (name, layer.featureCount()))
        else:
            log("invalid %s" % path)
    # 关系 DBF 需要在工程中存在，shpchecker 会按图层名读取它们。
    for name in ("CROSSWALK_LANE_REL", "INTERSECTION_SIGNAL_REL"):
        path = os.path.join(input_dir, name + ".dbf")
        layer = QgsVectorLayer(path, name, "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            log("loaded %s (%s)" % (name, layer.featureCount()))
        else:
            log("invalid %s" % path)


def button_text(button):
    return "%s %s" % (button.text(), button.toolTip())


def click_button(patterns):
    dialogs = [w for w in QApplication.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]
    for dialog in reversed(dialogs):
        for button in dialog.findChildren(QPushButton):
            text = button_text(button)
            if button.isVisible() and button.isEnabled() and any(pattern.lower() in text.lower() for pattern in patterns):
                # Queue the click so state is updated before a long synchronous checker callback starts.
                QTimer.singleShot(0, button.click)
                log("queued click %s" % text)
                return True
    return False


def has_export():
    for root, _dirs, files in os.walk(input_dir):
        for name in files:
            path = os.path.join(root, name)
            if (name.lower().startswith("errorlog") and name.lower().endswith(".xlsx")
                    and os.path.getmtime(path) >= run_started_at):
                return True
    return False


state = {
    "started": False, "selected": False, "executed": False,
    "export_clicked": False, "save_accepted": False, "ticks": 0,
}


def accept_export_dialog():
    output_path = os.path.join(input_dir, "errorlog.xlsx")
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QFileDialog) and widget.isVisible():
            widget.selectFile(output_path)
            widget.accept()
            log("export path=%s" % output_path)
            return True
    return False


def poll():
    state["ticks"] += 1
    if not state["started"]:
        state["started"] = True
        try:
            if vendor_parent and vendor_parent not in sys.path:
                sys.path.insert(0, vendor_parent)
            import shpchecker
            checker = shpchecker.classFactory(iface)
            state["checker"] = checker
            checker.initGui()
            log("calling shpchecker.run")
            # shpchecker.run() enters a modal dialog loop. Schedule the next automation
            # tick first so it can operate inside that nested event loop.
            QTimer.singleShot(500, poll)
            checker.run()
            log("shpchecker.run returned")
            return
        except Exception:
            log(traceback.format_exc())
            QApplication.quit()
            return
    if not state["selected"]:
        state["selected"] = click_button(("全选", "全部选择", "select all"))
    elif not state["executed"]:
        state["executed"] = click_button(("执行", "开始检查", "check"))
    elif not state["export_clicked"]:
        state["export_clicked"] = click_button(("导出结果", "导出", "export"))
    elif not state["save_accepted"]:
        state["save_accepted"] = accept_export_dialog()
    if state["export_clicked"]:
        if has_export() or state["ticks"] > 240:
            log("finished export=%s" % has_export())
            QApplication.quit()
            return
    if state["ticks"] > 300:
        log("timeout")
        QApplication.quit()
        return
    QTimer.singleShot(500, poll)


load_layers()
QTimer.singleShot(1000, poll)
