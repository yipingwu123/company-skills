#!/usr/bin/env python3
"""迈鲸公海客户导出文件本地校验。

校验真实导出后的 Excel/CSV 文件，不访问迈鲸网站。
重点校验行数、关键字段是否存在，以及城市、区县、品类是否和筛选计划一致。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = Path(__file__).resolve().parent


DEFAULT_COLUMN_CANDIDATES = {
    "city": ["城市", "所在城市", "city", "cityName"],
    "district": ["区县", "区域", "所在区县", "district", "districtName"],
    "category": ["品类", "一级品类", "行业品类", "category", "categoryName"],
    "phone": ["电话", "手机号", "联系电话", "号码", "phone", "kpPhone"],
}


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
    "checkpoint_runner_for_maijing_export_file_validate",
)
excel_validator = load_module(
    ROOT / "common" / "Excel处理-excel-transform" / "excel_validator.py",
    "excel_validator_for_maijing_export_file_validate",
)


STEPS = [
    checkpoint.StepDef("load_export_file", "读取导出文件"),
    checkpoint.StepDef("validate_row_count", "校验导出行数"),
    checkpoint.StepDef("validate_filter_columns", "校验筛选字段"),
    checkpoint.StepDef("write_validation_report", "写入校验报告"),
    checkpoint.StepDef("human_review_validation", "人工复核校验结果"),
]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(value: Any) -> str:
    return "" if value is None else str(value).strip()


def load_filter_plan_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.filter_plan:
        return read_json(Path(args.filter_plan).resolve())
    if args.export_run_dir:
        run_dir = Path(args.export_run_dir).resolve()
        plan_path = run_dir / "input" / "filter_plan.json"
        if not plan_path.exists():
            raise SystemExit(f"导出运行目录缺少筛选计划：{plan_path}")
        return read_json(plan_path)
    raise SystemExit("必须提供 --filter-plan 或 --export-run-dir。")


def load_expected_total(args: argparse.Namespace) -> int | None:
    if args.expected_total is not None:
        return int(args.expected_total)
    if args.export_run_dir:
        evidence_path = Path(args.export_run_dir).resolve() / "outputs" / "export_file_evidence.json"
        if evidence_path.exists():
            evidence = read_json(evidence_path)
            value = evidence.get("expected_total")
            return int(value) if value is not None else None
    return None


def find_column(headers: list[str], candidates: list[str]) -> str | None:
    normalized_headers = {normalize(header).lower(): header for header in headers}
    for candidate in candidates:
        found = normalized_headers.get(normalize(candidate).lower())
        if found:
            return found
    for header in headers:
        for candidate in candidates:
            if normalize(candidate).lower() in normalize(header).lower():
                return header
    return None


def first_bad_rows(
    records: list[dict[str, str]],
    column: str,
    allowed_values: list[str],
    *,
    contains: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    allowed = [normalize(value) for value in allowed_values if normalize(value)]
    bad = []
    for index, row in enumerate(records, start=2):
        value = normalize(row.get(column))
        if contains:
            ok = any(item in value for item in allowed)
        else:
            ok = value in allowed
        if not ok:
            bad.append({"row": index, "value": value})
        if len(bad) >= limit:
            break
    return bad


def validate_records(
    records: list[dict[str, str]],
    filter_plan: dict[str, Any],
    expected_total: int | None,
    column_candidates: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    candidates = column_candidates or DEFAULT_COLUMN_CANDIDATES
    headers = list(records[0].keys()) if records else []
    dynamic = filter_plan.get("dynamic_filters") or {}
    errors = []
    warnings = []

    row_count = len(records)
    if expected_total is not None:
        # 允许 ±5 条波动（公海数据实时变化，认领/移入导致小幅差异）
        tolerance = max(5, int(expected_total * 0.01))
        if abs(row_count - expected_total) > tolerance:
            errors.append({
                "type": "row_count_mismatch",
                "message_cn": f"导出行数 {row_count} 与预期 total {expected_total} 差异 {abs(row_count - expected_total)} 超过容忍范围 {tolerance}",
            })
        elif row_count != expected_total:
            # 在容忍范围内，只记录为警告
            warnings.append(f"导出行数 {row_count} 与预期 total {expected_total} 差 {abs(row_count - expected_total)} 条（在容忍范围 ±{tolerance} 内，正常）")

    resolved_columns = {
        field: find_column(headers, names)
        for field, names in candidates.items()
    }

    if not resolved_columns.get("phone"):
        errors.append({"type": "missing_phone_column", "message_cn": "未找到号码列，无法确认有号码条件。"})

    city = normalize(dynamic.get("city"))
    if city:
        column = resolved_columns.get("city")
        if not column:
            errors.append({"type": "missing_city_column", "message_cn": "未找到城市列，无法校验城市。"})
        else:
            bad = first_bad_rows(records, column, [city])
            if bad:
                errors.append({"type": "city_mismatch", "message_cn": f"城市列存在不等于 {city} 的行", "examples": bad})

    districts = [normalize(item) for item in dynamic.get("districts") or [] if normalize(item)]
    if districts:
        column = resolved_columns.get("district")
        if not column:
            warnings.append({"type": "missing_district_column", "message_cn": "未找到区县列，需要人工抽查区县。"})
        else:
            bad = first_bad_rows(records, column, districts)
            if bad:
                errors.append({"type": "district_mismatch", "message_cn": "区县列存在不在需求范围内的行", "examples": bad})

    categories = [normalize(item) for item in dynamic.get("categories") or [] if normalize(item)]
    if categories:
        column = resolved_columns.get("category")
        if not column:
            warnings.append({"type": "missing_category_column", "message_cn": "未找到品类列，需要人工抽查品类。"})
        else:
            bad = first_bad_rows(records, column, categories, contains=True)
            if bad:
                errors.append({"type": "category_mismatch", "message_cn": "品类列存在不包含需求品类的行", "examples": bad})

    return {
        "ok": not errors,
        "row_count": row_count,
        "expected_total": expected_total,
        "columns": headers,
        "resolved_columns": resolved_columns,
        "errors": errors,
        "warnings": warnings,
        "needs_human_review": bool(errors or warnings),
    }


def write_review_checklist(run_dir: Path, report: dict[str, Any]) -> None:
    lines = [
        "# 迈鲸公海客户导出文件校验确认清单",
        "",
        f"- 校验是否通过：{report.get('ok')}",
        f"- 导出行数：{report.get('row_count')}",
        f"- 预期 total：{report.get('expected_total')}",
        f"- 需要人工复核：{report.get('needs_human_review')}",
        "",
        "## 字段匹配",
        "",
    ]
    for field, column in (report.get("resolved_columns") or {}).items():
        lines.append(f"- {field}：{column or '未找到'}")
    lines.extend([
        "",
        "## 错误",
        "",
        json.dumps(report.get("errors") or [], ensure_ascii=False, indent=2),
        "",
        "## 警告",
        "",
        json.dumps(report.get("warnings") or [], ensure_ascii=False, indent=2),
    ])
    (run_dir / "outputs" / "validation_review_checklist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="迈鲸公海客户导出文件本地校验。")
    parser.add_argument("--file", required=True)
    parser.add_argument("--filter-plan")
    parser.add_argument("--export-run-dir")
    parser.add_argument("--expected-total", type=int)
    parser.add_argument("--column-map", help="自定义字段候选 JSON。")
    parser.add_argument("--batch", default="001")
    args = parser.parse_args()

    source_file = Path(args.file).resolve()
    if not source_file.exists():
        raise SystemExit(f"导出文件不存在：{source_file}")

    filter_plan = load_filter_plan_from_args(args)
    expected_total = load_expected_total(args)
    column_candidates = read_json(Path(args.column_map).resolve()) if args.column_map else None
    city = (filter_plan.get("dynamic_filters") or {}).get("city") or "未指定城市"
    run_dir = checkpoint.ensure_run_dir(
        base_dir=ROOT,
        workflow_id="maijing-public-sea-export-file-validate",
        workflow_name_cn="迈鲸公海客户导出文件校验",
        city=city,
        batch=args.batch,
        dry_run=False,
        steps=STEPS,
    )

    checkpoint.update_step(run_dir, "load_export_file", "running", "读取导出文件")
    write_json(run_dir / "input" / "filter_plan.json", filter_plan)
    write_json(run_dir / "input" / "validation_input.json", {
        "source_file": str(source_file),
        "expected_total": expected_total,
        "column_candidates": column_candidates or DEFAULT_COLUMN_CANDIDATES,
    })
    records = excel_validator.read_table(source_file)
    checkpoint.update_step(run_dir, "load_export_file", "completed", "读取导出文件")

    checkpoint.update_step(run_dir, "validate_row_count", "running", "校验导出行数")
    checkpoint.update_step(run_dir, "validate_row_count", "completed", "校验导出行数")

    checkpoint.update_step(run_dir, "validate_filter_columns", "running", "校验筛选字段")
    report = validate_records(records, filter_plan, expected_total, column_candidates)
    report["source_file"] = str(source_file)
    checkpoint.update_step(run_dir, "validate_filter_columns", "completed", "校验筛选字段")

    checkpoint.update_step(run_dir, "write_validation_report", "running", "写入校验报告")
    write_json(run_dir / "outputs" / "validation_report.json", report)
    write_review_checklist(run_dir, report)
    checkpoint.update_step(run_dir, "write_validation_report", "completed", "写入校验报告")

    checkpoint.update_step(run_dir, "human_review_validation", "pending", "人工复核校验结果")
    checkpoint.check_contract(run_dir)
    checkpoint.append_log(run_dir, f"迈鲸导出文件校验完成：{'通过' if report['ok'] else '未通过'}")

    print(f"迈鲸导出文件校验完成，运行目录：{run_dir}")
    print(f"校验报告：{run_dir / 'outputs' / 'validation_report.json'}")
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
