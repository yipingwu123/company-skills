#!/usr/bin/env python3
"""迈鲸导出文件校验逻辑测试。"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "workflows" / "迈鲸公海客户筛选导出-maijing-public-sea-filter-export" / "validate_export_file.py"


def load_module():
    spec = importlib.util.spec_from_file_location("validate_export_file", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_module()


class MaijingValidateExportFileTest(unittest.TestCase):
    def test_valid_records_pass_filter_validation(self) -> None:
        records = [
            {"城市": "长沙市", "区县": "岳麓区", "品类": "餐饮", "电话": "13800000000"},
            {"城市": "长沙市", "区县": "岳麓区", "品类": "休闲娱乐", "电话": "13900000000"},
        ]
        filter_plan = {
            "dynamic_filters": {
                "city": "长沙市",
                "districts": ["岳麓区"],
                "categories": ["餐饮", "休闲娱乐"],
            }
        }

        report = validator.validate_records(records, filter_plan, expected_total=2)

        self.assertTrue(report["ok"])
        self.assertFalse(report["needs_human_review"])
        self.assertEqual(report["resolved_columns"]["city"], "城市")

    def test_row_count_mismatch_fails(self) -> None:
        records = [{"城市": "长沙市", "区县": "岳麓区", "品类": "餐饮", "电话": "13800000000"}]
        filter_plan = {"dynamic_filters": {"city": "长沙市"}}

        report = validator.validate_records(records, filter_plan, expected_total=2)

        self.assertFalse(report["ok"])
        self.assertEqual(report["errors"][0]["type"], "row_count_mismatch")

    def test_city_mismatch_fails_with_examples(self) -> None:
        records = [{"城市": "株洲市", "区县": "岳麓区", "品类": "餐饮", "电话": "13800000000"}]
        filter_plan = {"dynamic_filters": {"city": "长沙市"}}

        report = validator.validate_records(records, filter_plan, expected_total=1)

        self.assertFalse(report["ok"])
        self.assertEqual(report["errors"][0]["type"], "city_mismatch")
        self.assertEqual(report["errors"][0]["examples"][0]["row"], 2)

    def test_missing_phone_column_fails(self) -> None:
        records = [{"城市": "长沙市", "区县": "岳麓区", "品类": "餐饮"}]
        filter_plan = {"dynamic_filters": {"city": "长沙市"}}

        report = validator.validate_records(records, filter_plan, expected_total=1)

        self.assertFalse(report["ok"])
        self.assertIn("missing_phone_column", [error["type"] for error in report["errors"]])

    def test_missing_category_column_requires_human_review(self) -> None:
        records = [{"城市": "长沙市", "区县": "岳麓区", "电话": "13800000000"}]
        filter_plan = {"dynamic_filters": {"city": "长沙市", "categories": ["餐饮"]}}

        report = validator.validate_records(records, filter_plan, expected_total=1)

        self.assertTrue(report["ok"])
        self.assertTrue(report["needs_human_review"])
        self.assertEqual(report["warnings"][0]["type"], "missing_category_column")


if __name__ == "__main__":
    unittest.main()
