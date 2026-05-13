#!/usr/bin/env python3
"""端到端 SOP 流程状态总览。

给定日期，扫描 runs 目录，按品类展示迈鲸导出、手机号拉取、火山任务、
火山结果、结果解析、迈鲸导入这条主流程的关键输出是否存在。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CN_TZ = timezone(timedelta(hours=8))


STEPS = [
    {
        "index": 1,
        "workflow": "maijing-public-sea-export-execute",
        "label": "迈鲸公海导出",
        "output": lambda category: Path("outputs") / "split" / f"category_{category}.xlsx",
    },
    {
        "index": 2,
        "workflow": "maijing-fetch-phone-by-id",
        "label": "迈鲸手机号拉取",
        "output": lambda category: Path("outputs") / f"mobile_list_{category}.json",
        "check_poi": True,
    },
    {
        "index": 3,
        "workflow": "volcengine-call-task-create",
        "label": "火山任务创建",
        "output": lambda category: Path("outputs") / "task_plan.json",
    },
    {
        "index": 4,
        "workflow": "volcengine-call-result-export",
        "label": "火山结果导出",
        "output": lambda category: Path("outputs") / f"result_{category}.csv",
    },
    {
        "index": 5,
        "workflow": "volcengine-parse-result",
        "label": "外呼结果解析",
        "output": lambda category: Path("outputs") / f"leads_for_import_{category}.json",
    },
    {
        "index": 6,
        "workflow": "maijing-lead-import",
        "label": "迈鲸商机导入",
        "output": lambda category: Path("outputs") / "import_summary.json",
    },
]


def today_str() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def run_state(run_dir: Path) -> dict[str, Any]:
    return load_json(run_dir / "state" / "run_state.json") or {}


def has_failed(run_dir: Path) -> bool:
    state = run_state(run_dir)
    steps = state.get("steps") or {}
    if isinstance(steps, dict):
        return any(isinstance(step, dict) and step.get("status") == "failed" for step in steps.values())
    if isinstance(steps, list):
        return any(isinstance(step, dict) and step.get("status") == "failed" for step in steps)
    return False


def parse_run_parts(run_dir_name: str, workflow_id: str) -> tuple[str, str]:
    suffix = run_dir_name[len(workflow_id):].lstrip("-")
    if not suffix:
        return "未指定品类", "001"
    parts = suffix.rsplit("-", 1)
    if len(parts) == 2:
        return parts[0] or "未指定品类", parts[1] or "001"
    return suffix, "001"


def collect_run_dirs(date_dir: Path) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = {}
    if not date_dir.exists():
        return grouped
    workflow_ids = [step["workflow"] for step in STEPS]
    for run_dir in sorted(path for path in date_dir.iterdir() if path.is_dir()):
        for workflow_id in workflow_ids:
            if run_dir.name.startswith(workflow_id + "-") or run_dir.name == workflow_id:
                grouped.setdefault(workflow_id, []).append(run_dir)
                break
    return grouped


def discover_categories(grouped: dict[str, list[Path]]) -> list[str]:
    categories = set()
    for workflow_id, run_dirs in grouped.items():
        for run_dir in run_dirs:
            if workflow_id == "maijing-public-sea-export-execute":
                split_dir = run_dir / "outputs" / "split"
                if split_dir.exists():
                    for path in split_dir.glob("category_*.xlsx"):
                        categories.add(path.stem.replace("category_", "", 1))
                continue
            category, _batch = parse_run_parts(run_dir.name, workflow_id)
            if category:
                categories.add(category)
    return sorted(categories) or ["未指定品类"]


def newest_run_for_category(run_dirs: list[Path], workflow_id: str, category: str) -> Path | None:
    candidates = []
    for run_dir in run_dirs:
        if workflow_id == "maijing-public-sea-export-execute":
            if first_category_file(run_dir, category):
                _run_category, batch = parse_run_parts(run_dir.name, workflow_id)
                candidates.append((batch, run_dir.name, run_dir))
            continue
        run_category, batch = parse_run_parts(run_dir.name, workflow_id)
        if run_category == category:
            candidates.append((batch, run_dir.name, run_dir))
    if not candidates:
        return None
    return sorted(candidates)[-1][2]


def first_category_file(run_dir: Path, category: str) -> Path | None:
    preferred = run_dir / "outputs" / "split" / f"category_{category}.xlsx"
    if preferred.exists():
        return preferred
    split_dir = run_dir / "outputs" / "split"
    if split_dir.exists():
        matches = sorted(split_dir.glob("category_*.xlsx"))
        if matches:
            return matches[0]
    return None


def check_poi_code(path: Path) -> str:
    data = load_json(path) or {}
    phone_list = data.get("phone_list") or []
    if not isinstance(phone_list, list) or not phone_list:
        return "poi?"
    first = phone_list[0]
    return "poi✓" if isinstance(first, dict) and first.get("poi_code") else "poi?"


def output_for_step(run_dir: Path | None, step: dict[str, Any], category: str) -> tuple[str, str]:
    if not run_dir:
        return str(step["output"](category)), "等待"
    if step["workflow"] == "maijing-public-sea-export-execute":
        actual = first_category_file(run_dir, category)
        rel = actual.relative_to(run_dir) if actual else step["output"](category)
        exists = actual is not None and actual.exists()
    else:
        rel = step["output"](category)
        actual = run_dir / rel
        exists = actual.exists()
    if has_failed(run_dir):
        return str(rel), "失败"
    if exists and step.get("check_poi"):
        return f"{rel} ({check_poi_code(actual)})", "完成"
    if exists:
        return str(rel), "完成"
    return str(rel), "等待"


def status_icon(status: str) -> str:
    return {
        "完成": "OK",
        "等待": "WAIT",
        "失败": "FAIL",
    }.get(status, status)


def print_pipeline(date: str, grouped: dict[str, list[Path]]) -> None:
    categories = discover_categories(grouped)
    print(f"SOP 流程进度（{date}）")
    print("=" * 96)
    headers = ["步骤", "Workflow", "品类", "批次", "输出文件", "状态"]
    rows = []
    for category in categories:
        for step in STEPS:
            workflow_id = str(step["workflow"])
            run_dir = newest_run_for_category(grouped.get(workflow_id, []), workflow_id, category)
            _run_category, batch = parse_run_parts(run_dir.name, workflow_id) if run_dir else (category, "-")
            output, status = output_for_step(run_dir, step, category)
            rows.append([
                str(step["index"]),
                workflow_id,
                category,
                batch,
                output,
                status_icon(status),
            ])
    widths = []
    for index, header in enumerate(headers):
        values = [row[index] for row in rows]
        widths.append(min(max([len(header), *(len(value) for value in values)]), 42) if values else len(header))

    def clip(value: str, width: int) -> str:
        return value if len(value) <= width else value[: max(width - 1, 0)] + "…"

    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    for row in rows:
        print("  ".join(clip(row[index], widths[index]).ljust(widths[index]) for index in range(len(headers))))
    print("=" * 96)


def main() -> None:
    parser = argparse.ArgumentParser(description="打印 SOP 端到端流程状态。")
    parser.add_argument("--date", default=today_str(), help="运行日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--base-dir", default=str(ROOT), help="项目根目录，默认 skills 根目录")
    args = parser.parse_args()

    date_dir = Path(args.base_dir).resolve() / "runs" / args.date
    grouped = collect_run_dirs(date_dir)
    print_pipeline(args.date, grouped)


if __name__ == "__main__":
    main()
