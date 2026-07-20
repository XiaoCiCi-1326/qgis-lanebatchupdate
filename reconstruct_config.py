# -*- coding: utf-8 -*-
"""一键重构：目录名、工具栏步骤 6~9 匹配规则。"""

import json
import os

# 插件根目录下三份数据副本文件夹名
DIR_ORIGINAL = "原始文件"
DIR_DELETE_129 = "删除129"
DIR_DELETE_NOT_11 = "删除11以外"

# 步骤 6~9：对应 QGIS 工具栏里 Z Attribute / Z Tools 的四个按钮（见用户截图）
STEP_TOOLBAR = {
    "step6": {
        "label": "计算 车道边界及车道长宽",
        "hint": "Plugins/Z Attribute/计算 车道边界及车道长宽",
        "keyword_groups": (
            ("计算", "车道边界", "车道长宽"),
            ("车道边界", "车道长宽"),
        ),
    },
    "step7": {
        "label": "计算 道路边界及邻近车道",
        "hint": "Plugins/Z Attribute/计算 道路边界及邻近车道",
        "keyword_groups": (
            ("计算", "道路边界", "邻近车道"),
            ("道路边界", "邻近车道"),
        ),
    },
    "step8": {
        "label": "自动生成 LANE_SECTION, ROAD 图层",
        "hint": "Plugins/Z Tools/自动生成 LANE_SECTION, ROAD 图层",
        "keyword_groups": (
            ("自动生成", "LANE_SECTION", "ROAD"),
            ("LANE_SECTION", "ROAD"),
        ),
    },
    "step9": {
        "label": "自动生成 LANE_NODE 图层",
        "hint": "Plugins/Z Tools/自动生成 LANE_NODE 图层",
        "keyword_groups": (
            ("自动生成", "LANE_NODE"),
            ("LANE_NODE", "图层"),
        ),
    },
}

# 兼容旧代码引用
STEP_KEYWORDS = {key: info["keyword_groups"][0] for key, info in STEP_TOOLBAR.items()}

# 若存在 reconstruct_algorithms.json，可在菜单找不到时回退 Processing
ALGORITHM_CONFIG_FILE = "reconstruct_algorithms.json"

DEFAULT_ALGORITHM_IDS = {
    "step6": "",
    "step7": "",
    "step8": "",
    "step9": "",
    "refactor_fields": "",
}


def load_algorithm_ids(plugin_dir):
    """读取可选的 Processing 算法 ID（一般留空，直接点工具栏按钮）。"""
    ids = dict(DEFAULT_ALGORITHM_IDS)
    path = os.path.join(plugin_dir, ALGORITHM_CONFIG_FILE)
    if not os.path.isfile(path):
        return ids
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            ids.update({k: str(v) for k, v in data.items() if v and not str(k).startswith("_")})
    except (OSError, ValueError, TypeError):
        pass
    return ids
