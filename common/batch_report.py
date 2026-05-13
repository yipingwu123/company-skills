#!/usr/bin/env python3
"""批量操作摘要报告。

给定日期和品类，扫描 runs 目录中的关键 JSON 文件，生成纯文字批次报告。
缺失数据以“未完成”展示，不抛错。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CN_TZ = timezone(timedelta(hours=8))


def today_str() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")


def load_json(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def newest(pattern: str) -> Path | None:
    matches = sorted(Path().glob(pattern))
    return matches[-1] if matches else None


def newest_in(base: Path, pattern: str) -> Path | None:
    matches = sorted(base.glob(pattern))
    return matches[-1] if matches else None


def percent(part: Any, total: Any) -> str:
    try:
        part_num = float(part)
        total_num = float(total)
    except (TypeError, ValueError):
        return "未完成"
    if total_num <= 0:
        return "0.0%"
    return f"{part_num / total_num * 100:.1f}%"


def value(data: dict[str, Any], *keys: str, default: str = "未完成") -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current if current not in (None, "") else default


def task_info(date_dir: Path, category: str) -> tuple[dict[str, Any], str]:
    direct = date_dir / "volcengine-task-created" / f"task_{category}.json"
    if direct.exists():
        return load_json(direct), str(direct)
    path = newest_in(date_dir, f"volcengine-call-task-create-{category}-*/outputs/created_task.json")
    if not path:
        path = newest_in(date_dir, f"volcengine-call-task-create-{category}-*/outputs/task_plan.json")
    return load_json(path), str(path) if path else "未完成"


def result_summary(date_dir: Path, category: str) -> tuple[dict[str, Any], str]:
    path = newest_in(date_dir, f"volcengine-call-result-export-{category}-*/outputs/result_summary.json")
    return load_json(path), str(path) if path else "未完成"


def parse_summary(date_dir: Path, category: str) -> tuple[dict[str, Any], str]:
    path = newest_in(date_dir, f"volcengine-parse-result-{category}-*/outputs/parse_summary.json")
    return load_json(path), str(path) if path else "未完成"


def import_history(date_dir: Path, category: str) -> tuple[dict[str, Any], str]:
    path = newest_in(date_dir, f"maijing-lead-import-{category}-*/outputs/import_history.json")
    if not path:
        path = newest_in(date_dir, f"maijing-lead-import-{category}-*/outputs/import_summary.json")
    return load_json(path), str(path) if path else "未完成"


def result_csv_path(date_dir: Path, category: str) -> str:
    path = newest_in(date_dir, f"volcengine-call-result-export-{category}-*/outputs/result_{category}.csv")
    return str(path) if path else "未完成"


def leads_path(date_dir: Path, category: str) -> str:
    path = newest_in(date_dir, f"volcengine-parse-result-{category}-*/outputs/leads_for_import_{category}.json")
    return str(path) if path else "未完成"


def report(date: str, category: str, base_dir: Path) -> str:
    date_dir = base_dir / "runs" / date
    task, task_path = task_info(date_dir, category)
    result, result_path = result_summary(date_dir, category)
    parsed, parsed_path = parse_summary(date_dir, category)
    imported, import_path = import_history(date_dir, category)

    planned_count = value(task, "phone_count")
    if planned_count == "未完成":
        planned_count = value(task, "phone_count", default=value(task, "phoneCount"))
    task_id = value(task, "task_id", default=value(task, "TaskId"))
    task_start = value(task, "start_time", default=value(task, "StartTime"))
    task_end = value(task, "end_time", default=value(task, "EndTime"))

    total = value(result, "total_rows", default=value(result, "total_count"))
    answered = value(result, "answered_count", default=value(result, "answer_count"))
    not_answered = value(result, "not_answered_count")
    if not_answered == "未完成" and isinstance(total, int) and isinstance(answered, int):
        not_answered = total - answered

    matched = value(parsed, "matched_with_poi")
    import_file = value(imported, "fileName", default=value(imported, "xlsx_filename"))
    success_count = value(imported, "successCount", default=value(imported, "success_count"))
    fail_count = value(imported, "failCount", default=value(imported, "failed_count"))

    lines = [
        "═══════════════════════════════════════════════",
        f"AI 外呼批次报告 - {date} - {category}",
        "═══════════════════════════════════════════════",
        "【外呼任务】",
        f"  任务 ID：{task_id}",
        f"  计划号码数：{planned_count}",
        f"  任务时段：{task_start} – {task_end}",
        "",
        "【外呼结果】",
        f"  总数：{total}",
        f"  接通：{answered}（{percent(answered, total)}）",
        f"  未接：{not_answered}",
        "",
        "【商机导入】",
        f"  接通匹配 POI：{matched}",
        f"  生成 xlsx：{import_file}",
        f"  导入成功：{success_count}",
        f"  导入失败：{fail_count}",
        "",
        "【文件路径】",
        f"  任务信息：{task_path}",
        f"  结果 CSV：{result_csv_path(date_dir, category)}",
        f"  结果摘要：{result_path}",
        f"  商机名单：{leads_path(date_dir, category)}",
        f"  解析摘要：{parsed_path}",
        f"  导入摘要：{import_path}",
        "═══════════════════════════════════════════════",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 AI 外呼批次操作摘要。")
    parser.add_argument("--date", default=today_str(), help="日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--category", required=True, help="品类名称，如 餐饮")
    parser.add_argument("--base-dir", default=str(ROOT), help="项目根目录，默认 skills 根目录")
    args = parser.parse_args()

    print(report(args.date, args.category, Path(args.base_dir).resolve()))


if __name__ == "__main__":
    main()
