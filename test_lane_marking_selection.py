# -*- coding: utf-8 -*-
"""单元测试：ErrorResultsController._quality_error_record 的 ID 路由逻辑

不依赖 QGIS，仅用 mock 验证不同错误文本下 BOUNDARY / LANE 的选区路由是否正确。
运行：python test_lane_marking_selection.py
"""
import re
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, ".")

# 在 import error_results_controller 之前先 mock qgis.PyQt/qgis.core/qgis.gui，
# 让模块可以脱离 QGIS 环境加载。QGIS 模块在用户机器上一定能 import，
# 但我们希望单测可以在 CI / 普通 Python 环境里跑。
qgis_mock = mock.MagicMock()
sys.modules.setdefault("qgis", qgis_mock)
sys.modules.setdefault("qgis.PyQt", qgis_mock.PyQt)
sys.modules.setdefault("qgis.PyQt.QtCore", qgis_mock.PyQt.QtCore)
sys.modules.setdefault("qgis.PyQt.QtGui", qgis_mock.PyQt.QtGui)
sys.modules.setdefault("qgis.PyQt.QtWidgets", qgis_mock.PyQt.QtWidgets)
sys.modules.setdefault("qgis.core", qgis_mock.core)
sys.modules.setdefault("qgis.gui", qgis_mock.gui)

# 预加载 lanebatchupdate 包路径下的两个核心模块（避开相对导入）
from lanebatchupdate import error_results_controller as _erc  # noqa: E402
ErrorResultsController = _erc.ErrorResultsController


class FakeFeature:
    def __init__(self, fid, attrs):
        self._fid = fid
        self._attrs = {k.upper(): v for k, v in attrs.items()}
        self.id = lambda: fid  # noqa: E731

    def __getitem__(self, key):
        return self._attrs[key.upper()]

    def __contains__(self, key):
        return key.upper() in self._attrs


class FakeField:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class FakeVectorLayer:
    def __init__(self, name, features, layer_id=None):
        self._name = name
        self._features = features
        self._id_field = "ID"
        self._fields = [FakeField(self._id_field)] if features else []
        self._layer_id = layer_id or "layer_%s" % name

    def name(self):
        return self._name

    def id(self):  # noqa: A003 - mirrors QGIS API
        return self._layer_id

    def fields(self):
        return self._fields

    def getFeatures(self):
        for f in self._features:
            yield f


class QualityParseTest(unittest.TestCase):
    """仅测试纯文本解析，不真正选区。"""

    def _run_quality_error_record(self, data):
        # 拦截 _find_vector_layer：如果 name == target_name，构造一个含指定 ID 的 mock 图层
        project_layers = {
            "LANE": FakeVectorLayer("LANE", []),
            "BOUNDARY": FakeVectorLayer("BOUNDARY", [
                FakeFeature(101, {"ID": "8151373"}),
            ]),
            "ROAD": FakeVectorLayer("ROAD", []),
        }

        def fake_find(name):
            if not name:
                return None
            aliases = {
                "LANE_MARKING": "BOUNDARY",
                "ROAD_LINK": "ROAD",
            }
            target = aliases.get(str(name).strip().upper(), str(name).strip().upper())
            return project_layers.get(target)

        with mock.patch.object(ErrorResultsController, "_find_vector_layer", staticmethod(fake_find)):
            record = ErrorResultsController._quality_error_record(data)
        return record, project_layers

    def test_lane_marking_marktype11_routes_to_boundary(self):
        """【LANE_MARKING】marktype=11：必须选到 BOUNDARY 而不是 LANE"""
        # 同时模拟 ERROR_LOG 的两种可能 schema
        for data in (
            {
                # shpchecker 把 LANEMARKID 放在独立列
                "LAYER": "LANE_MARKING",
                "FEATUREID": "",
                "LANEMARKID": "8151373",
                "DETAIL": "marktype是11,但是不在ROAD_LINK的最外侧边界上",
            },
            {
                # shpchecker 序列化到 DETAIL：[error][LANE_MARKING][LANEMARKID][8151373】...
                "LAYER": "LANE_MARKING",
                "FEATUREID": "8151373",
                "LANEMARKID": "",
                "DETAIL": "[error][LANE_MARKING][LANEMARKID][8151373】marktype是11,但是不在ROAD_LINK的最外侧边界上",
            },
        ):
            record, layers = self._run_quality_error_record(data)
            self.assertIsNotNone(record, "record 不应为 None")
            selections = record["selections"]
            # selection key 是 layer.id()，这里是 layer_BOUNDARY
            self.assertIn(layers["BOUNDARY"].id(), selections, f"应选中 BOUNDARY，data={data}")
            # 不应该把 8151373 误登记到 LANE
            self.assertNotIn(layers["LANE"].id(), selections, f"不应把 marking ID 误判为 LANE，data={data}")
            # 选中的 BOUNDARY feature id 是 101
            boundary_fids = selections[layers["BOUNDARY"].id()]
            self.assertIn(101, boundary_fids, f"BOUNDARY 应选中 fid=101，data={data}")
            # quality_source 应记录原始字段便于 select_record 判断活动图层
            self.assertEqual(record["quality_source"]["LAYER"], "LANE_MARKING")

    def test_lane_marking_lanemarkid_in_text(self):
        """描述文本里直接出现 LANEMARKID=xxx"""
        data = {
            "LAYER": "LANE_MARKING",
            "DETAIL": "LANEMARKID=8151373 marktype是11不在最外侧边界上",
        }
        record, layers = self._run_quality_error_record(data)
        self.assertIn(layers["BOUNDARY"].id(), record["selections"])
        self.assertIn(101, record["selections"][layers["BOUNDARY"].id()])

    def test_lane_routing_unchanged(self):
        """回归测试：普通 LANE 错误仍按原路径走 LANE → ROAD → BOUNDARY → SIGNAL"""
        data = {
            "LAYER": "LANE",
            "FEATUREID": "4034636",
            "DETAIL": "路口lane挂接缺失:4034636",
        }
        # 给 LANE 加 ID=4034636 的 mock 要素
        project_layers = {
            "LANE": FakeVectorLayer("LANE", [FakeFeature(999, {"ID": "4034636"})]),
            "BOUNDARY": FakeVectorLayer("BOUNDARY", []),
            "ROAD": FakeVectorLayer("ROAD", []),
            "SIGNAL": FakeVectorLayer("SIGNAL", []),
            "INTERSECTION": FakeVectorLayer("INTERSECTION", []),
        }

        def fake_find(name):
            return project_layers.get(str(name).strip().upper())

        with mock.patch.object(ErrorResultsController, "_find_vector_layer", staticmethod(fake_find)):
            record = ErrorResultsController._quality_error_record(data)
        self.assertIn(project_layers["LANE"].id(), record["selections"])
        self.assertIn(999, record["selections"][project_layers["LANE"].id()])
        # BOUNDARY 不应被选中（没有 ID 命中）
        self.assertNotIn(project_layers["BOUNDARY"].id(), record["selections"])

    def test_bracket_form_lane_marking(self):
        """shpchecker 旧序列化格式：[LANE_MARKING][LANEMARKID][XXX]"""
        data = {
            "LAYER": "LANE_MARKING",
            "DETAIL": "[LANE_MARKING][LANEMARKID] 8151373 marktype是11",
        }
        record, layers = self._run_quality_error_record(data)
        self.assertIn(layers["BOUNDARY"].id(), record["selections"])
        self.assertIn(101, record["selections"][layers["BOUNDARY"].id()])


if __name__ == "__main__":
    unittest.main(verbosity=2)
