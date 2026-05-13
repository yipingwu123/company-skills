#!/usr/bin/env python3
"""迈鲸筛选计数 dry-run 的本地行为测试。"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "workflows" / "迈鲸公海客户筛选导出-maijing-public-sea-filter-export" / "filter_count_dry_run.py"


def load_module():
    spec = importlib.util.spec_from_file_location("filter_count_dry_run", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


filter_count = load_module()


class MaijingFilterCountDryRunTest(unittest.TestCase):
    def test_unverified_map_marks_query_plan_unsafe(self) -> None:
        plan = {
            "dynamic_filters": {
                "city": "长沙市",
                "districts": ["岳麓区"],
                "categories": ["餐饮", "休闲娱乐"],
            },
            "fixed_filters": {
                "has_phone": "有号码",
                "follow_progress": ["未接通", "未跟进"],
                "store_status": "营业中",
            },
        }
        param_map = {
            "status": "unverified",
            "dynamic_filters": {
                "city": {"api_param": "cityNameList", "verified": False},
                "districts": {"api_param": "districtNameList", "verified": False},
                "categories": {"api_param": "categoryNameList", "verified": False},
            },
            "fixed_filters": {
                "has_phone": {"api_param": "hasPhone", "value": "有号码", "verified": False},
                "follow_progress": {"api_param": "followProgressList", "value": ["未接通", "未跟进"], "verified": False},
                "store_status": {"api_param": None, "value": "营业中", "verified": False},
            },
        }

        query_plan = filter_count.build_query_params(plan, param_map)

        self.assertFalse(query_plan["safe_to_execute_without_confirmation"])
        self.assertIn("fixed_filters.store_status", query_plan["unmapped_filters"])
        self.assertIn("dynamic_filters.city:cityNameList", query_plan["unverified_params"])
        self.assertEqual(query_plan["params"]["pageSize"], ["1"])

    def test_verified_complete_map_can_be_safe_for_readonly_count(self) -> None:
        plan = {
            "dynamic_filters": {
                "city": "长沙市",
                "districts": ["岳麓区"],
                "categories": ["餐饮"],
            },
            "fixed_filters": {
                "has_phone": "有号码",
            },
        }
        param_map = {
            "status": "verified",
            "dynamic_filters": {
                "city": {"api_param": "cityName", "mode": "csv", "verified": True},
                "districts": {"api_param": "districtName", "mode": "csv", "verified": True},
                "categories": {"api_param": "categoryName", "mode": "csv", "verified": True},
            },
            "fixed_filters": {
                "has_phone": {"api_param": "hasPhone", "value": "1", "verified": True},
            },
        }

        query_plan = filter_count.build_query_params(plan, param_map)

        self.assertTrue(query_plan["safe_to_execute_without_confirmation"])
        self.assertEqual(query_plan["unmapped_filters"], [])
        self.assertEqual(query_plan["unverified_params"], [])
        self.assertEqual(query_plan["params"]["hasPhone"], ["1"])
        self.assertEqual(query_plan["params"]["cityName"], ["长沙市"])
        self.assertEqual(query_plan["params"]["categoryName"], ["餐饮"])

    def test_csv_mode_joins_multi_values_like_frontend(self) -> None:
        plan = {
            "dynamic_filters": {
                "categories": ["餐饮", "休闲娱乐"],
            },
            "fixed_filters": {
                "store_filter": ["有效", "误杀"],
            },
        }
        param_map = {
            "status": "verified",
            "dynamic_filters": {
                "categories": {"api_param": "categoryName", "mode": "csv", "verified": True},
            },
            "fixed_filters": {
                "store_filter": {"api_param": "storeFilterTags", "mode": "csv", "value": ["0", "2"], "verified": True},
            },
        }

        query_plan = filter_count.build_query_params(plan, param_map)

        self.assertEqual(query_plan["params"]["categoryName"], ["餐饮,休闲娱乐"])
        self.assertEqual(query_plan["params"]["storeFilterTags"], ["0,2"])

    def test_list_summary_does_not_include_customer_rows(self) -> None:
        response = {
            "code": 200,
            "msg": "查询成功",
            "total": 2,
            "rows": [
                {"id": 1, "customerName": "测试门店", "phone": "13800000000"},
            ],
        }

        summary = filter_count.summarize_list_response(response)

        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["first_row_keys_only"], ["customerName", "id", "phone"])
        self.assertFalse(summary["customer_rows_saved"])
        self.assertNotIn("测试门店", str(summary))
        self.assertNotIn("13800000000", str(summary))


if __name__ == "__main__":
    unittest.main()
