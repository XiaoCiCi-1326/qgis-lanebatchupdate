# -*- coding: utf-8 -*-
"""一键重构：目录名、处理步骤关键字、可覆盖的算法 ID。"""

import json
import os

# 插件根目录下三份数据副本文件夹名
DIR_ORIGINAL = "原始文件"
DIR_DELETE_129 = "删除129"
DIR_DELETE_NOT_11 = "删除11以外"

# 处理步骤（俗称 6~9）在 Processing/菜单 中的匹配关键字（全部包含才命中）
STEP_KEYWORDS = {
    "step6": ("计算车道边界", "车道长宽"),
    "step6_alt": ("计算车道边界",),
    "step7": ("计算道路边界", "邻近车道"),
    "step7_alt": ("道路边界", "邻近车道"),
    "step8": ("LANE", "SECTION"),
    "step8_alt": ("自动生成", "ROAD"),
    "step9": ("LANE", "NODE"),
    "step9_alt": ("LANE_NODE",),
    "refactor_fields": ("重构字段",),
}

# 若存在 reconstruct_algorithms.json，则优先使用其中的算法 ID
ALGORITHM_CONFIG_FILE = "reconstruct_algorithms.json"

DEFAULT_ALGORITHM_IDS = {
    "step6": "",
    "step7": "",
    "step8": "",
    "step9": "",
    "refactor_fields": "",
}


def load_algorithm_ids(plugin_dir):
    """读取用户配置的 Processing 算法 ID。"""
    ids = dict(DEFAULT_ALGORITHM_IDS)
    path = os.path.join(plugin_dir, ALGORITHM_CONFIG_FILE)
    if not os.path.isfile(path):
        return ids
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            ids.update({k: str(v) for k, v in data.items() if v})
    except (OSError, ValueError, TypeError):
        pass
    return ids
