# -*- coding: utf-8 -*-
"""QGIS 3.16 子进程中的 jdchecker 自动化入口。"""
from __future__ import print_function

import ctypes
from ctypes import wintypes
import os
import sys
import time
import traceback

from qgis.PyQt.QtCore import QTimer, QObject
from qgis.PyQt.QtWidgets import (QApplication, QAbstractButton, QDialog, QMessageBox,
                                  QAction, QMenu, QProgressBar)
from qgis.core import QgsProject, QgsVectorLayer
from qgis.utils import iface

input_dir = os.environ.get("LANEBATCH_JDCHECKER_INPUT", "")
dll_path = os.environ.get("LANEBATCH_JDCHECKER_DLL", "")
log_path = os.environ.get("LANEBATCH_JDCHECKER_LOG", "")
lines = ["input=%s" % input_dir, "dll=%s" % dll_path]
started = time.time()
state = {"started": False, "launched": False, "selected": False, "executed": False,
         "done": False, "completion_seen": False, "finish_ticks": 0, "ticks": 0,
         "last_launch_tick": 0}


def log(text):
    lines.append(str(text))
    if log_path:
        try:
            with open(log_path, "w", encoding="utf-8-sig") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass


def load_layers():
    names = ("CLEARAREA", "CROSSWALK", "FREEAREA", "GATE", "INTERSECTION", "LANE_GROUP", "LANE_MARKING", "LANE_NODE", "LANE", "PARKING", "PILLAR", "PROHIBITED_AREA", "ROAD_LINK", "SAFETYISLAND", "SPEEDBUMP", "STOPLINE", "TRAFFICLIGHT")
    for name in names + ("CROSSWALK_LANE_REL", "INTERSECTION_SIGNAL_REL"):
        ext = ".shp" if name not in ("CROSSWALK_LANE_REL", "INTERSECTION_SIGNAL_REL") else ".dbf"
        path = os.path.join(input_dir, name + ext)
        layer = QgsVectorLayer(path, name, "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            log("loaded %s" % name)
        else:
            log("invalid %s" % path)


def all_qt_widgets():
    """Return all Qt widgets (top-level and children), regardless of visibility."""
    return QApplication.allWidgets()


def widget_info(widget):
    """Return a combined string from text, toolTip, and objectName."""
    try:
        parts = [widget.text(), widget.toolTip(), widget.objectName()]
        return " ".join(p for p in parts if p)
    except Exception:
        return ""


def log_all_checker_widgets():
    """Log all Qt widgets in the app, focusing on dialogs that might be jdchecker."""
    dialogs = []
    for widget in all_qt_widgets():
        if isinstance(widget, QDialog):
            title = widget.windowTitle()
            all_buttons = []
            for btn in widget.findChildren(QAbstractButton):
                all_buttons.append(widget_info(btn))
            dialogs.append("QDialog title=%r buttons=%r" % (title, all_buttons))
        elif "vector" in widget.objectName().lower() or "check" in widget.objectName().lower():
            dialogs.append("QWidget name=%r text=%r" % (widget.objectName(), widget.windowTitle()))
    if dialogs:
        log("ALL Qt dialogs: " + " | ".join(dialogs))


def checker_qt_roots():
    """Find actual checker dialogs, not an empty plugin container."""
    roots = []
    for widget in all_qt_widgets():
        try:
            identity = "%s %s" % (widget.windowTitle(), widget.objectName())
            is_dialog = isinstance(widget, QDialog)
            controls = widget.findChildren(QObject) if is_dialog else []
            has_checker_control = any(
                any(p.lower() in widget_info(child).lower()
                    for p in SELECT_PATTERNS + EXEC_PATTERNS)
                for child in controls
            )
        except RuntimeError:
            continue
        if (is_dialog and ("vectordatacheck" in identity.lower()
                           or "jdchecker" in identity.lower()
                           or "质检" in identity
                           or has_checker_control)):
            roots.append(widget)
    return roots


def log_all_qt_windows():
    details = []
    for widget in QApplication.topLevelWidgets():
        try:
            details.append("%s title=%r name=%r visible=%s" % (
                widget.metaObject().className(), widget.windowTitle(),
                widget.objectName(), widget.isVisible()))
        except RuntimeError:
            continue
    if details:
        log("Qt top-level windows: " + " | ".join(details))


def hide_qgis_main_window():
    try:
        main_window = iface.mainWindow()
        if main_window is not None and main_window.isVisible():
            main_window.hide()
            log("hidden QGIS 3.16 main window after checker dialog opened")
    except Exception as exc:
        log("hide QGIS main window failed: %r" % (exc,))


def log_checker_window():
    roots = checker_qt_roots()
    if not roots:
        log("VectorDataCheck window not found")
        return False
    details = []
    for root in roots:
        buttons = [widget_info(button) for button in root.findChildren(QAbstractButton)]
        details.append("VectorDataCheck title=%r name=%r buttons=%r" % (
            root.windowTitle(), root.objectName(), buttons
        ))
    log(" | ".join(details))
    return True


def log_checker_controls():
    """Log every descendant of the jdchecker container for control discovery."""
    for root in checker_qt_roots():
        controls = []
        for child in root.findChildren(QObject):
            try:
                class_name = child.metaObject().className()
                name = child.objectName()
                text = child.text() if hasattr(child, "text") else ""
                tooltip = child.toolTip() if hasattr(child, "toolTip") else ""
                if name or text or tooltip or class_name not in ("QWidget", "QObject"):
                    controls.append("%s name=%r text=%r tip=%r" % (
                        class_name, name, text, tooltip
                    ))
            except (RuntimeError, AttributeError, TypeError):
                continue
        log("jdchecker controls: " + " | ".join(controls))


def _vector_data_check_roots():
    """Return only the real VectorDataCheck dialog, not unrelated QGIS dialogs."""
    roots = []
    for widget in all_qt_widgets():
        try:
            if (isinstance(widget, QDialog)
                    and widget.windowTitle().strip().lower() == "vectordatacheck"
                    and widget.objectName().strip().lower() == "dialog"):
                roots.append(widget)
        except RuntimeError:
            continue
    return roots


def _checker_progress_complete():
    """Detect completion from VectorDataCheck's own progress bar."""
    for root in _vector_data_check_roots():
        try:
            bars = root.findChildren(QProgressBar)
            if any(bar.value() >= 100 for bar in bars):
                log("VectorDataCheck progressBar reached 100%")
                log("检查完毕")
                return True
        except RuntimeError:
            continue
    return False


def _checker_dialog_roots():
    """Return the actual VectorDataCheck dialog before generic QDialogs."""
    exact = []
    fallback = []
    for root in checker_qt_roots():
        try:
            title = root.windowTitle().strip().lower()
            name = root.objectName().strip().lower()
            if title == "vectordatacheck" and name == "dialog":
                exact.append(root)
            else:
                fallback.append(root)
        except RuntimeError:
            continue
    return exact + fallback


def click_checker_action(patterns):
    """Click matching QAction controls used by custom/native Qt plugins."""
    for root in _checker_dialog_roots():
        for action in root.findChildren(QAction):
            info = widget_info(action)
            if action.isEnabled() and info and any(p.lower() in info.lower() for p in patterns):
                action.trigger()
                log("triggered VectorDataCheck action: %s" % info)
                return True
    return False


def click_checker_button(patterns):
    """Click the actual VectorDataCheck execute button first."""
    roots = _checker_dialog_roots()
    if any(p.lower() in ("执行检查", "执行", "开始检查", "开始质检") for p in patterns):
        ordered_buttons = []
        for root in roots:
            for object_name in ("pushButton_4", "pushButton_3"):
                button = root.findChild(QAbstractButton, object_name)
                if button is not None:
                    ordered_buttons.append(button)
        buttons = ordered_buttons
    else:
        buttons = [button for root in roots for button in root.findChildren(QAbstractButton)]
    for button in buttons:
        try:
            info = widget_info(button)
            matches = any(p.lower() in info.lower() for p in patterns)
            log("checker button candidate: %s enabled=%s visible=%s match=%s" % (
                info, button.isEnabled(), button.isVisible(), matches))
            if button.isEnabled() and button.isVisible() and info and matches:
                button.click()
                log("clicked VectorDataCheck button: %s" % info)
                return True
        except RuntimeError:
            continue
    return False


def checker_native_windows():
    """Find actual native checker windows by their title or controls."""
    result = []
    for hwnd in _native_windows():
        title = _native_window_text(hwnd).lower()
        buttons = " ".join(text.lower() for _button, text in _native_child_buttons(hwnd))
        if ("vectordatacheck" in title
                or any(p.lower() in buttons for p in SELECT_PATTERNS + EXEC_PATTERNS)):
            result.append(hwnd)
    return result


def click_checker_native_button(patterns):
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    for hwnd in reversed(checker_native_windows()):
        for button, text in _native_child_buttons(hwnd):
            if any(pattern.lower() in text.lower() for pattern in patterns):
                user32.SendMessageW(button, 0x00F5, 0, 0)  # BM_CLICK
                log("clicked native VectorDataCheck button: %s" % text)
                return True
    return False


def _native_window_text(hwnd):
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def _native_windows():
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    current_pid = os.getpid()
    windows = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def add_window(hwnd, _lparam):
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == current_pid and user32.IsWindowVisible(hwnd):
            windows.append(hwnd)
        return True

    user32.EnumWindows(callback_type(add_window), 0)
    return windows


def _native_child_buttons(hwnd):
    user32 = ctypes.windll.user32
    buttons = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def add_button(child, _lparam):
        if user32.IsWindowVisible(child) and user32.IsWindowEnabled(child):
            text = _native_window_text(child)
            if text:
                buttons.append((child, text))
        return True

    user32.EnumChildWindows(hwnd, callback_type(add_button), 0)
    return buttons


def _native_child_texts(hwnd):
    """Read every visible child text, including disabled labels."""
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    texts = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def add_child(child, _lparam):
        if user32.IsWindowVisible(child):
            text = _native_window_text(child)
            if text:
                texts.append(text)
        return True

    user32.EnumChildWindows(hwnd, callback_type(add_child), 0)
    return texts


def _native_window_all_text(hwnd):
    return " ".join([_native_window_text(hwnd)] + _native_child_texts(hwnd))


def log_native_dialogs():
    if os.name != "nt":
        return
    details = []
    for hwnd in _native_windows():
        title = _native_window_text(hwnd)
        buttons = [text for _button, text in _native_child_buttons(hwnd)]
        if title or buttons:
            details.append("native window=%r buttons=%r" % (title, buttons))
    if details:
        log("native controls: " + " | ".join(details))


def click_native(patterns):
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    for hwnd in reversed(_native_windows()):
        for button, text in _native_child_buttons(hwnd):
            if any(pattern.lower() in text.lower() for pattern in patterns):
                user32.SendMessageW(button, 0x00F5, 0, 0)  # BM_CLICK
                log("clicked native %s" % text)
                return True
    return False



def close_checker_dialogs():
    """Close Qt and native checker windows after completion."""
    closed = False
    for root in _vector_data_check_roots():
        try:
            if root.isVisible():
                root.close()
                closed = True
        except RuntimeError:
            continue
    if os.name == "nt":
        user32 = ctypes.windll.user32
        for hwnd in _native_windows():
            text = _native_window_all_text(hwnd).lower()
            if "vectordatacheck" in text or "vector data check" in text:
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                closed = True
    if closed:
        log("closed VectorDataCheck window")
    return closed


def _is_completion_text(text):
    text = (text or "").lower()
    return ("检查完成" in text or "检查完毕" in text or "质检完成" in text
            or "质检完毕" in text or "finished" in text or "complete" in text)


def _close_completion_widget(widget):
    try:
        widget.close()
        log("closed Qt completion window")
        close_checker_dialogs()
        state["completion_seen"] = True
        state["finish_ticks"] = 0
        return True
    except RuntimeError:
        return False


def _mark_completion():
    """Keep the child alive briefly so delayed checker windows can close."""
    state["completion_seen"] = True
    state["finish_ticks"] += 1
    close_finished_message()
    close_checker_dialogs()
    if state["finish_ticks"] >= 4:
        state["done"] = True


def close_finished_message():
    for widget in all_qt_widgets():
        if isinstance(widget, QMessageBox):
            text = widget.windowTitle() + " " + widget.text()
            if _is_completion_text(text):
                log("closed Qt completion message")
                widget.accept()
                close_checker_dialogs()
                state["completion_seen"] = True
                return True
    for widget in QApplication.topLevelWidgets():
        try:
            if isinstance(widget, QDialog) and widget.isVisible():
                controls = " ".join(widget_info(child)
                                    for child in widget.findChildren(QObject))
                text = widget.windowTitle() + " " + controls
                if _is_completion_text(text):
                    return _close_completion_widget(widget)
        except RuntimeError:
            continue
    if os.name == "nt":
        user32 = ctypes.windll.user32
        for hwnd in _native_windows():
            text = _native_window_all_text(hwnd)
            if _is_completion_text(text):
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                log("closed native completion message")
                close_checker_dialogs()
                state["completion_seen"] = True
                return True
    return False


def ensure_jdchecker_plugin():
    """Preload the native DLL; QGIS 3.16 loads native plugins at startup."""
    if not dll_path or not os.path.isfile(dll_path):
        log("jdchecker DLL not found: %s" % dll_path)
        return False
    try:
        ctypes.CDLL(dll_path)
        log("loaded jdchecker DLL: %s" % dll_path)
        return True
    except Exception as exc:
        log("jdchecker DLL load failed: %r" % (exc,))
        return False


def _menu_label(menu):
    try:
        action = menu.menuAction()
        return action.text().replace("&", "").strip() if action is not None else ""
    except (RuntimeError, AttributeError):
        return ""


def _normalized_text(value):
    return value.replace("&", "").strip().lower() if value else ""


def _is_jdchecker_text(text):
    normalized = _normalized_text(text)
    return (normalized == "jdchecker"
            or normalized == "jdchecker jdchecker"
            or normalized.startswith("jdchecker "))


def _collect_jdchecker_actions(menu, result, path=()):
    """Collect jdchecker commands from the real QGIS menu hierarchy."""
    try:
        actions = menu.actions()
    except RuntimeError:
        return
    for action in actions:
        try:
            text = action.text().replace("&", "").strip()
            submenu = action.menu()
            current_path = path + (text,)
            if submenu is not None:
                _collect_jdchecker_actions(submenu, result, current_path)
            elif _is_jdchecker_text(text) and action.isEnabled():
                result.append((action, text, " -> ".join(path)))
        except (RuntimeError, AttributeError):
            continue


def find_jdchecker_menu_action():
    """Locate the jdchecker command registered in the QGIS menu bar."""
    main_window = iface.mainWindow()
    if main_window is None:
        return None, ""
    candidates = []
    menu_bar = main_window.menuBar()
    if menu_bar is not None:
        for root_action in menu_bar.actions():
            submenu = root_action.menu()
            if submenu is not None:
                _collect_jdchecker_actions(submenu, candidates,
                                            (root_action.text().replace("&", "").strip(),))
    # Some QGIS/plugin versions expose menus outside menuBar().
    if not candidates:
        for menu in main_window.findChildren(QMenu):
            _collect_jdchecker_actions(menu, candidates, (_menu_label(menu),))
    details = ["%s [%s]" % (path, text)
               for _action, text, path in candidates]
    log("jdchecker menu candidates: %r" % details)
    if len(candidates) != 1:
        return None, ""
    action, text, _path = candidates[0]
    return action, text


def start_checker():
    action, text = find_jdchecker_menu_action()
    if action is None:
        log("unique Plugins -> jdchecker -> jdchecker action not found; refusing to click")
        return False
    try:
        main_window = iface.mainWindow()
        if main_window is not None:
            main_window.show()
            main_window.raise_()
            main_window.activateWindow()
        log("found jdchecker menu action=%r enabled=%s" % (text, action.isEnabled()))
        action.trigger()
        log("triggered Plugins -> jdchecker -> %s" % text)
        return True
    except RuntimeError as exc:
        log("jdchecker menu trigger failed: %r" % (exc,))
        return False


SELECT_PATTERNS = (
    "全选", "全部选择", "select all", "选择全部",
    "全选(x)", "quanxuan", "qx", "selectall",
)
EXEC_PATTERNS = (
    "执行检查", "执行质检", "执行检测", "执行", "开始检查", "开始质检",
    "开始检测", "检查数据", "运行检查", "运行质检", "开始", "check",
    "run", "quality check", "qualitycheck", "确认执行", "确定", "ok",
)


def poll():
    state["ticks"] += 1
    if state["completion_seen"]:
        _mark_completion()
        if state["done"]:
            log("finished")
            QApplication.quit()
            return
        QTimer.singleShot(500, poll)
        return
    if not state["started"]:
        state["started"] = True
        if ensure_jdchecker_plugin():
            log("jdchecker native plugin is ready")
        else:
            log("jdchecker native plugin did not report ready")
        try:
            QTimer.singleShot(1500, poll)
            return
        except Exception:
            log(traceback.format_exc())
            QApplication.quit()
            return
    if not state["launched"]:
        if start_checker():
            state["launched"] = True
            state["last_launch_tick"] = state["ticks"]
            log("clicked jdchecker; waiting for checker dialog...")
            QApplication.processEvents()
            QTimer.singleShot(1500, poll)
            return
    # Never trigger the QAction repeatedly: a native plugin may toggle or
    # ignore duplicate invocations while its dialog is opening.
    if not checker_qt_roots() and not checker_native_windows():
        if state["ticks"] % 5 == 0:
            log("checker dialog not found; waiting without retriggering QAction")
            log_all_qt_windows()
            log_native_dialogs()
        QTimer.singleShot(1000, poll)
        return
    hide_qgis_main_window()
    if state["ticks"] % 5 == 0:
        log_checker_window()
        log_checker_controls()
        log_native_dialogs()
    if not state["selected"]:
        clicked = click_checker_button(SELECT_PATTERNS)
        if not clicked:
            clicked = click_checker_action(SELECT_PATTERNS)
        if not clicked:
            clicked = click_checker_native_button(SELECT_PATTERNS)
        state["selected"] = clicked
        if state["selected"]:
            log("selected all VectorDataCheck items")
            # The plugin enables the execute button immediately after 全选.
            QApplication.processEvents()
            QTimer.singleShot(100, poll)
            return
        log("waiting for VectorDataCheck 全选 button...")
    elif not state["executed"]:
        clicked = click_checker_button(EXEC_PATTERNS)
        if not clicked:
            clicked = click_checker_action(EXEC_PATTERNS)
        if not clicked:
            clicked = click_checker_native_button(EXEC_PATTERNS)
        state["executed"] = clicked
        if state["executed"]:
            log("execute_clicked: VectorDataCheck 执行检查")
        else:
            if state["ticks"] % 3 == 0:
                log("execution candidates not clicked; dumping checker controls")
                log_checker_controls()
                log_native_dialogs()
            log("waiting for VectorDataCheck 执行检查 button...")
    else:
        if _checker_progress_complete():
            _mark_completion()
        else:
            close_finished_message()
    if state["ticks"] > 600:
        log("timeout")
        QApplication.quit()
        return
    QTimer.singleShot(1000, poll)


load_layers()
QTimer.singleShot(1500, poll)
