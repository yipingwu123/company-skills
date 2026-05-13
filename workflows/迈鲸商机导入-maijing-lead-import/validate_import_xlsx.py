#!/usr/bin/env python3
"""迈鲸商机导入 xlsx 校验工具。

读取 import_leads_dry_run.py 生成的 xlsx，校验模板列、关键字段和手机号格式。
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = Path(__file__).resolve().parent


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


excel_validator = load_module(
    ROOT / "common" / "Excel处理-excel-transform" / "excel_validator.py",
    "excel_validator_for_maijing_import_validate",
)
import_leads = load_module(WORKFLOW_DIR / "import_leads_dry_run.py", "maijing_import_leads_for_validate")
TEMPLATE_COLUMNS = import_leads.TEMPLATE_COLUMNS


def is_mobile(value: str) -> bool:
    text = str(value or "").strip()
    return len(text) == 11 and text[0] == "1" and text.isdigit()


def print_check(ok: bool, message: str) -> None:
    prefix = "✅ 通过" if ok else "❌ 失败"
    print(f"{prefix}: {message}")


def validate_headers(headers: list[str]) -> bool:
    ok = headers == TEMPLATE_COLUMNS
    if ok:
        print_check(True, "列名与 TEMPLATE_COLUMNS 完全一致")
    else:
        print_check(False, "列名与 TEMPLATE_COLUMNS 不一致")
        print(f"  期望：{TEMPLATE_COLUMNS}")
        print(f"  实际：{headers}")
    return ok


def non_empty_rate(records: list[dict[str, str]], column: str) -> float:
    if not records:
        return 0.0
    count = sum(1 for row in records if str(row.get(column, "")).strip())
    return count / len(records)


def validate_required_columns(records: list[dict[str, str]]) -> bool:
    ok = True
    for column in ["POI编码", "POI名称", "电话"]:
        empty_rows = [idx for idx, row in enumerate(records, start=2) if not str(row.get(column, "")).strip()]
        if empty_rows:
            ok = False
            print_check(False, f"{column} 存在空值，示例行：{empty_rows[:10]}")
        else:
            print_check(True, f"{column} 全部非空")
    return ok


def validate_expected_source(records: list[dict[str, str]], expected_source: str | None) -> bool:
    if not expected_source:
        print("跳过: 未提供 --expected-source，不校验客户来源")
        return True
    bad_rows = [
        idx for idx, row in enumerate(records, start=2)
        if str(row.get("客户来源(跟进阶段)", "")).strip() != expected_source
    ]
    if bad_rows:
        print_check(False, f"客户来源不等于 {expected_source}，示例行：{bad_rows[:10]}")
        return False
    print_check(True, f"客户来源全部等于 {expected_source}")
    return True


def validate_mobile_column(records: list[dict[str, str]]) -> bool:
    bad = [
        {"row": idx, "value": row.get("电话", "")}
        for idx, row in enumerate(records, start=2)
        if not is_mobile(row.get("电话", ""))
    ]
    if bad:
        print_check(False, f"电话列存在非 11 位移动号，示例：{bad[:10]}")
        return False
    print_check(True, "电话列全部为 11 位移动号")
    return True


def print_column_rates(records: list[dict[str, str]]) -> None:
    print("\n各列非空率：")
    for column in TEMPLATE_COLUMNS:
        rate = non_empty_rate(records, column)
        print(f"  {column}: {rate:.1%}")


def print_sample_rows(records: list[dict[str, str]], count: int) -> None:
    print(f"\n前 {count} 行样本：")
    for idx, row in enumerate(records[:count], start=2):
        sample = {
            "行号": idx,
            "客户来源(跟进阶段)": row.get("客户来源(跟进阶段)", ""),
            "POI编码": row.get("POI编码", ""),
            "POI名称": row.get("POI名称", ""),
            "电话": row.get("电话", ""),
        }
        print(f"  {sample}")


def main() -> None:
    parser = argparse.ArgumentParser(description="校验迈鲸商机导入 xlsx。")
    parser.add_argument("--xlsx-file", required=True, help="要校验的 xlsx 路径")
    parser.add_argument("--expected-source", help="预期客户来源值，如 AI外呼")
    parser.add_argument("--show-rows", type=int, default=3, help="显示前 N 行数据，默认 3")
    args = parser.parse_args()

    xlsx_file = Path(args.xlsx_file).resolve()
    if not xlsx_file.exists():
        raise SystemExit(f"xlsx 文件不存在：{xlsx_file}")

    records = excel_validator.read_table(xlsx_file)
    headers = list(records[0].keys()) if records else []
    checks = [
        validate_headers(headers),
        validate_required_columns(records),
        validate_expected_source(records, args.expected_source),
        validate_mobile_column(records),
    ]
    print_column_rates(records)
    print_sample_rows(records, args.show_rows)

    if all(checks):
        print("\n校验通过")
        raise SystemExit(0)
    print("\n校验失败")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
