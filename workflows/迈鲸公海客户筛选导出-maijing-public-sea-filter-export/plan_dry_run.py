#!/usr/bin/env python3
"""迈鲸公海客户筛选导出 dry-run 计划生成。

只解析需求并生成筛选计划，不登录迈鲸，不导出文件。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checkpoint = load_module(ROOT / "common" / "断点续跑-checkpoint-runner" / "checkpoint_runner.py", "checkpoint_runner")
parser_mod = load_module(ROOT / "common" / "需求解析-feishu-requirement-parser" / "parse_requirement.py", "parse_requirement")


STEPS = [
    checkpoint.StepDef("parse_requirement", "解析飞书需求"),
    checkpoint.StepDef("build_filter_plan", "生成筛选计划"),
    checkpoint.StepDef("human_confirm_filter_plan", "人工确认筛选计划"),
    checkpoint.StepDef("stop_before_real_export", "停在真实导出前"),
]


FIXED_FILTERS = {
    "store_entry_status": "未进店",
    "claim_status": "待认领",
    "has_phone": "有号码",
    "store_filter": ["有效", "误杀"],
    "follow_progress": ["未接通", "未跟进"],
    "store_status": "营业中",
}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_filter_plan(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "system": "maijing",
        "module": "public_sea_customer",
        "dynamic_filters": {
            "city": parsed.get("city") or "",
            "districts": parsed.get("districts") or [],
            "categories": parsed.get("categories") or [],
        },
        "fixed_filters": FIXED_FILTERS,
        "needs_human_review": bool(parsed.get("needs_human_review")),
        "questions": parsed.get("questions") or [],
    }


def write_checklist(run_dir: Path, plan: dict[str, Any]) -> None:
    dynamic = plan["dynamic_filters"]
    fixed = plan["fixed_filters"]
    lines = [
        "# 迈鲸公海客户筛选导出 dry-run 确认清单",
        "",
        "## 动态筛选条件",
        "",
        f"- 城市：{dynamic.get('city') or '待确认'}",
        f"- 区县：{', '.join(dynamic.get('districts') or []) or '待确认'}",
        f"- 品类：{', '.join(dynamic.get('categories') or []) or '待确认'}",
        "",
        "## 固定筛选条件",
        "",
        f"- 进店状态：{fixed['store_entry_status']}",
        f"- 认领状态：{fixed['claim_status']}",
        f"- 有无号码：{fixed['has_phone']}",
        f"- 门店筛选：{', '.join(fixed['store_filter'])}",
        f"- 跟进进度：{', '.join(fixed['follow_progress'])}",
        f"- 门店状态：{fixed['store_status']}",
        "",
        "## 需要确认的问题",
        "",
    ]
    questions = plan.get("questions") or []
    lines.extend([f"- {q}" for q in questions] if questions else ["- 无。"])
    lines.extend([
        "",
        "## 当前停点",
        "",
        "- dry-run 已停在真实迈鲸导出前。",
        "- 下一步需要人工确认筛选计划。",
    ])
    (run_dir / "outputs" / "confirmation_checklist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="迈鲸公海客户筛选导出 dry-run。")
    parser.add_argument("--requirement", help="飞书需求原文。")
    parser.add_argument("--requirement-file")
    parser.add_argument("--batch", default="001")
    args = parser.parse_args()

    if args.requirement_file:
        requirement = Path(args.requirement_file).read_text(encoding="utf-8")
    elif args.requirement:
        requirement = args.requirement
    else:
        raise SystemExit("必须提供 --requirement 或 --requirement-file。")

    parsed = parser_mod.parse_requirement(requirement)
    city = parsed.get("city") or "未指定城市"
    run_dir = checkpoint.ensure_run_dir(
        base_dir=ROOT,
        workflow_id="maijing-public-sea-filter-export",
        workflow_name_cn="迈鲸公海客户筛选导出",
        city=city,
        batch=args.batch,
        dry_run=True,
        steps=STEPS,
    )
    (run_dir / "input" / "requirement.txt").write_text(requirement.strip() + "\n", encoding="utf-8")
    write_json(run_dir / "input" / "parsed_requirement.json", parsed)

    checkpoint.update_step(run_dir, "parse_requirement", "completed", "解析飞书需求")
    checkpoint.update_step(run_dir, "build_filter_plan", "running", "生成筛选计划")
    plan = build_filter_plan(parsed)
    write_json(run_dir / "outputs" / "filter_plan.json", plan)
    write_checklist(run_dir, plan)
    checkpoint.update_step(run_dir, "build_filter_plan", "completed", "生成筛选计划")

    checkpoint.update_step(run_dir, "human_confirm_filter_plan", "pending", "人工确认筛选计划")
    checkpoint.update_step(run_dir, "stop_before_real_export", "pending", "停在真实导出前")
    checkpoint.append_log(run_dir, "迈鲸公海筛选计划 dry-run 完成，未登录迈鲸，未导出。")
    print(f"迈鲸公海筛选计划已生成，运行目录：{run_dir}")
    print(f"确认清单：{run_dir / 'outputs' / 'confirmation_checklist.md'}")


if __name__ == "__main__":
    main()
