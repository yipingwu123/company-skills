#!/usr/bin/env python3
"""迈鲸导出预检 dry-run 的本地行为测试。"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "workflows" / "迈鲸公海客户筛选导出-maijing-public-sea-filter-export" / "export_preflight_dry_run.py"


def load_module():
    spec = importlib.util.spec_from_file_location("export_preflight_dry_run", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = load_module()


class MaijingExportPreflightDryRunTest(unittest.TestCase):
    def test_export_stat_summary_keeps_only_count(self) -> None:
        response = {"code": 200, "msg": "ok", "data": 869}

        summary = preflight.summarize_export_stat(response)

        self.assertEqual(summary["export_stat_total"], 869)
        self.assertFalse(summary["business_rows_saved"])
        self.assertNotIn("rows", summary)

    def test_route_uses_sync_download_under_threshold(self) -> None:
        route = preflight.pick_export_route(869)

        self.assertEqual(route["route"], "sync_download")
        self.assertEqual(route["endpoint"], preflight.EXPORT_DOWNLOAD_ENDPOINT)
        self.assertFalse(route["will_execute_in_dry_run"])

    def test_route_uses_async_task_over_threshold(self) -> None:
        route = preflight.pick_export_route(10001)

        self.assertEqual(route["route"], "async_task")
        self.assertEqual(route["endpoint"], preflight.EXPORT_ASYNC_ENDPOINT)
        self.assertFalse(route["will_execute_in_dry_run"])

    def test_build_export_plan_never_executes_export(self) -> None:
        query_plan = {
            "endpoint": "/customer/public/list",
            "params": {"pageNum": ["1"], "pageSize": ["1"], "cityName": ["长沙市"]},
            "query_string": "pageNum=1&pageSize=1&cityName=%E9%95%BF%E6%B2%99%E5%B8%82",
        }
        stat_summary = {"export_stat_total": 869}

        plan = preflight.build_export_plan(query_plan, stat_summary)

        self.assertTrue(plan["requires_human_confirmation"])
        self.assertFalse(plan["export_executed"])
        self.assertFalse(plan["download_executed"])
        self.assertTrue(plan["export_routes"]["sync_download"]["dry_run_forbidden"])
        self.assertTrue(plan["export_routes"]["async_task"]["dry_run_forbidden"])


if __name__ == "__main__":
    unittest.main()
