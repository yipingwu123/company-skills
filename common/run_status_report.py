#!/usr/bin/env python3
"""运行状态总览脚本。

扫描指定日期的 runs 目录，读取 state/run_state.json，打印各 workflow 的步骤状态。
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


def load_state(run_dir: Path) -> dict[str, Any] | None:
    state_path = run_dir / "state" / "run_state.json"
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def iter_steps(state: dict[str, Any]) -> list[dict[str, Any]]:
    steps = state.get("steps") or []
    if isinstance(steps, dict):
        result = []
        for step_id, step in steps.items():
            item = dict(step) if isinstance(step, dict) else {}
            item.setdefault("step_id", step_id)
            result.append(item)
        return result
    if isinstance(steps, list):
        return [step for step in steps if isinstance(step, dict)]
    return []


def summarize_run(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    steps = iter_steps(state)
    completed_count = sum(1 for step in steps if step.get("status") in {"completed", "skipped"})
    failed_count = sum(1 for step in steps if step.get("status") == "failed")
    latest_step = state.get("current_step_cn") or state.get("current_step") or "-"
    dry_run = bool(state.get("dry_run", True))
    if failed_count:
        status = "失败"
    elif any(step.get("status") == "running" for step in steps):
        status = "运行中"
    elif dry_run:
        status = "dry-run"
    elif steps and completed_count == len(steps):
        status = "完成"
    else:
        status = "待处理"
    return {
        "run_name": run_dir.name,
        "step_count": len(steps),
        "completed_count": completed_count,
        "failed_count": failed_count,
        "latest_step": latest_step,
        "status": status,
    }


def collect_runs(date_dir: Path, workflow_filter: str | None) -> list[dict[str, Any]]:
    rows = []
    if not date_dir.exists():
        return rows
    for run_dir in sorted(path for path in date_dir.iterdir() if path.is_dir()):
        if workflow_filter and workflow_filter not in run_dir.name:
            continue
        state = load_state(run_dir)
        if not state:
            continue
        rows.append(summarize_run(run_dir, state))
    return rows


def status_label(status: str) -> str:
    labels = {
        "完成": "完成",
        "失败": "失败",
        "运行中": "运行中",
        "dry-run": "dry-run",
        "待处理": "待处理",
    }
    return labels.get(status, status)


def print_table(date: str, rows: list[dict[str, Any]]) -> None:
    print(f"{date} 运行状态（共 {len(rows)} 个目录）")
    print("-" * 88)
    headers = ["目录名", "步数", "完成", "失败", "最新步骤", "状态"]
    table_rows = [
        [
            row["run_name"],
            str(row["step_count"]),
            str(row["completed_count"]),
            str(row["failed_count"]),
            str(row["latest_step"]),
            status_label(str(row["status"])),
        ]
        for row in rows
    ]
    widths = []
    for index, header in enumerate(headers):
        values = [item[index] for item in table_rows]
        widths.append(min(max([len(header), *(len(value) for value in values)]), 42) if values else len(header))

    def clip(value: str, width: int) -> str:
        return value if len(value) <= width else value[: max(width - 1, 0)] + "…"

    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    for item in table_rows:
        print("  ".join(clip(item[index], widths[index]).ljust(widths[index]) for index in range(len(headers))))


def main() -> None:
    parser = argparse.ArgumentParser(description="打印指定日期的 runs 运行状态总览。")
    parser.add_argument("--date", default=today_str(), help="运行日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--base-dir", default=str(ROOT / "runs"), help="runs 根目录")
    parser.add_argument("--workflow", help="只显示目录名包含此字符串的 workflow")
    args = parser.parse_args()

    date_dir = Path(args.base_dir).resolve() / args.date
    rows = collect_runs(date_dir, args.workflow)
    print_table(args.date, rows)


if __name__ == "__main__":
    main()
