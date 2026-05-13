#!/usr/bin/env python3
"""外呼结果解析为迈鲸商机名单。

读取火山外呼结果 CSV 和 mobile_list_{品类}.json，筛选接通号码并匹配 poi_code，
输出可直接传给 import_leads_dry_run.py --mobile-list 的 JSON。
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ID = "volcengine-parse-result"
WORKFLOW_NAME_CN = "火山外呼结果解析"
PHONE_COLUMNS = ["被叫号码", "手机号", "客户号码", "客户手机号", "电话", "号码", "Phone", "phone", "phone_number"]
STATUS_COLUMNS = ["通话状态", "呼叫状态", "通话结果", "呼叫结果", "Status", "status"]
DEFAULT_STATUS_KEYWORDS = "接通,已接,ANSWERED,connected"
NEGATIVE_STATUS_KEYWORDS = ["未接通", "未接", "未应答", "未拨通", "NO ANSWER", "not connected"]


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checkpoint = load_module(
    ROOT / "common" / "断点续跑-checkpoint-runner" / "checkpoint_runner.py",
    "checkpoint_runner_volcengine_parse_result",
)


STEPS = [
    checkpoint.StepDef("read_csv", "读取外呼结果 CSV"),
    checkpoint.StepDef("read_mobile_list", "读取手机号列表"),
    checkpoint.StepDef("match_leads", "匹配接通号码"),
    checkpoint.StepDef("write_leads", "写入商机名单"),
]


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_name(value: str) -> str:
    return checkpoint.clean_part(value, "未指定品类")


def normalize_phone(raw: str) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def parse_keywords(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if path.stat().st_size == 0:
        raise SystemExit("CSV 为空")
    last_error: Exception | None = None
    for encoding in ["utf-8-sig", "utf-8", "gb18030"]:
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    raise SystemExit("CSV 为空")
                rows = [{key: value for key, value in row.items()} for row in reader]
                return rows, [str(name) for name in reader.fieldnames]
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    raise RuntimeError(f"无法识别 CSV 编码：{last_error}")


def pick_column(headers: list[str], candidates: list[str], label: str) -> str:
    lower_map = {header.lower(): header for header in headers}
    for candidate in candidates:
        found = lower_map.get(candidate.lower())
        if found:
            return found
    print(f"找不到{label}列。可用列名：{headers}")
    raise SystemExit(f"找不到{label}列")


def load_mobile_list(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    phone_list = data.get("phone_list")
    if not isinstance(phone_list, list):
        raise SystemExit("mobile_list 文件缺少 phone_list 数组。")
    return data


def build_phone_index(phone_list: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in phone_list:
        if not isinstance(item, dict):
            continue
        phone = normalize_phone(str(item.get("Phone") or item.get("phone") or ""))
        if phone:
            index[phone] = item
    return index


def row_matches_status(row: dict[str, str], status_column: str, keywords: list[str]) -> bool:
    status = str(row.get(status_column) or "")
    status_upper = status.upper()
    if any(keyword.upper() in status_upper for keyword in NEGATIVE_STATUS_KEYWORDS):
        return False
    return any(keyword in status for keyword in keywords)


def match_leads(
    csv_rows: list[dict[str, str]],
    phone_column: str,
    status_column: str,
    status_keywords: list[str],
    phone_index: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    leads: list[dict[str, Any]] = []
    seen: set[str] = set()
    answered_count = 0
    unmatched_count = 0
    for row in csv_rows:
        if not row_matches_status(row, status_column, status_keywords):
            continue
        answered_count += 1
        phone = normalize_phone(row.get(phone_column, ""))
        matched = phone_index.get(phone)
        if not matched:
            unmatched_count += 1
            continue
        if phone in seen:
            continue
        seen.add(phone)
        leads.append(dict(matched))
    return leads, answered_count, unmatched_count


def main() -> None:
    parser = argparse.ArgumentParser(description="将火山外呼结果 CSV 解析为迈鲸商机导入名单。")
    parser.add_argument("--result-csv", required=True, help="火山结果 CSV 文件路径")
    parser.add_argument("--mobile-list", required=True, help="mobile_list_{品类}.json 路径")
    parser.add_argument("--category", required=True, help="品类名称")
    parser.add_argument("--status-keywords", default=DEFAULT_STATUS_KEYWORDS, help="接通状态关键词，逗号分隔")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--base-dir", default=str(ROOT))
    args = parser.parse_args()

    run_dir = checkpoint.ensure_run_dir(
        base_dir=Path(args.base_dir).resolve(),
        workflow_id=WORKFLOW_ID,
        workflow_name_cn=WORKFLOW_NAME_CN,
        city=safe_name(args.category),
        batch=args.batch,
        dry_run=False,
        steps=STEPS,
    )

    result_csv = Path(args.result_csv).resolve()
    mobile_list_path = Path(args.mobile_list).resolve()
    if not result_csv.exists():
        raise SystemExit(f"结果 CSV 不存在：{result_csv}")
    if not mobile_list_path.exists():
        raise SystemExit(f"mobile_list 不存在：{mobile_list_path}")

    checkpoint.update_step(run_dir, "read_csv", "running", "读取外呼结果 CSV")
    csv_rows, headers = read_csv_rows(result_csv)
    phone_column = pick_column(headers, PHONE_COLUMNS, "号码")
    status_column = pick_column(headers, STATUS_COLUMNS, "状态")
    checkpoint.update_step(run_dir, "read_csv", "completed", f"读取外呼结果 CSV，共 {len(csv_rows)} 条")

    checkpoint.update_step(run_dir, "read_mobile_list", "running", "读取手机号列表")
    mobile_data = load_mobile_list(mobile_list_path)
    original_phone_list = mobile_data.get("phone_list") or []
    phone_index = build_phone_index(original_phone_list)
    checkpoint.update_step(run_dir, "read_mobile_list", "completed", f"读取手机号列表，共 {len(phone_index)} 个可匹配号码")

    checkpoint.update_step(run_dir, "match_leads", "running", "匹配接通号码")
    keywords = parse_keywords(args.status_keywords)
    leads, answered_count, unmatched_count = match_leads(csv_rows, phone_column, status_column, keywords, phone_index)
    checkpoint.update_step(run_dir, "match_leads", "completed", f"接通 {answered_count} 条，匹配 {len(leads)} 条")

    checkpoint.update_step(run_dir, "write_leads", "running", "写入商机名单")
    payload = {
        "category": args.category,
        "source": "volcengine_call_result",
        "total_in_csv": len(csv_rows),
        "answered_in_csv": answered_count,
        "matched_with_poi": len(leads),
        "phone_list": leads,
    }
    summary = {
        "category": args.category,
        "result_csv": str(result_csv),
        "mobile_list": str(mobile_list_path),
        "phone_column": phone_column,
        "status_column": status_column,
        "status_keywords": keywords,
        "total_in_csv": len(csv_rows),
        "answered_in_csv": answered_count,
        "matched_with_poi": len(leads),
        "unmatched_answered": unmatched_count,
    }
    output_path = run_dir / "outputs" / f"leads_for_import_{safe_name(args.category)}.json"
    write_json(output_path, payload)
    write_json(run_dir / "outputs" / "parse_summary.json", summary)
    checkpoint.update_step(run_dir, "write_leads", "completed", "写入商机名单")
    checkpoint.check_contract(run_dir)
    print(f"解析完成：总数 {len(csv_rows)}，接通 {answered_count} 条，匹配 {len(leads)} 条")
    print(f"商机名单：{output_path}")
    print(f"运行目录：{run_dir}")


if __name__ == "__main__":
    main()
