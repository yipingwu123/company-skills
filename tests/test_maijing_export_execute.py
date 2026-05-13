#!/usr/bin/env python3
"""迈鲸真实导出执行脚本的安全行为测试。"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "workflows" / "迈鲸公海客户筛选导出-maijing-public-sea-filter-export" / "export_execute.py"


def load_module():
    spec = importlib.util.spec_from_file_location("export_execute", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export_execute = load_module()


class MaijingExportExecuteTest(unittest.TestCase):
    def test_confirmation_requires_explicit_approval(self) -> None:
        result = export_execute.validate_confirmation(
            {
                "approved": False,
                "confirmed_by": "业务负责人",
                "confirmed_at": "2026-05-13T12:00:00+08:00",
                "expected_total": 869,
                "approved_route": "sync_download",
            },
            current_total=869,
            current_route="sync_download",
        )

        self.assertFalse(result["ok"])
        self.assertIn("approved 必须为 true。", result["errors"])

    def test_confirmation_rejects_total_drift(self) -> None:
        result = export_execute.validate_confirmation(
            {
                "approved": True,
                "confirmed_by": "业务负责人",
                "confirmed_at": "2026-05-13T12:00:00+08:00",
                "expected_total": 869,
                "approved_route": "sync_download",
            },
            current_total=870,
            current_route="sync_download",
        )

        self.assertFalse(result["ok"])
        self.assertIn("确认 total=869，当前导出统计 total=870，不一致。", result["errors"])

    def test_confirmation_rejects_async_route(self) -> None:
        result = export_execute.validate_confirmation(
            {
                "approved": True,
                "confirmed_by": "业务负责人",
                "confirmed_at": "2026-05-13T12:00:00+08:00",
                "expected_total": 10001,
                "approved_route": "async_task",
            },
            current_total=10001,
            current_route="async_task",
        )

        self.assertFalse(result["ok"])
        self.assertIn("当前脚本只实现同步下载；异步任务导出必须另做脚本。", result["errors"])

    def test_json_payload_is_rejected_as_not_a_file(self) -> None:
        summary = export_execute.validate_download_payload(
            b'{"code":500,"msg":"error"}',
            {"Content-Type": "application/json"},
        )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["json_summary"]["code"], 500)

    def test_xlsx_payload_is_accepted(self) -> None:
        summary = export_execute.validate_download_payload(
            b"PK\x03\x04fake-xlsx-content",
            {"Content-Type": "application/octet-stream"},
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["suggested_extension"], ".xlsx")

    def test_export_filename_is_sanitized(self) -> None:
        filename = export_execute.build_safe_export_filename("长沙/岳麓", "00:1", ".xlsx")

        self.assertEqual(filename, "maijing_public_sea_customers_长沙-岳麓_00-1.xlsx")


if __name__ == "__main__":
    unittest.main()
