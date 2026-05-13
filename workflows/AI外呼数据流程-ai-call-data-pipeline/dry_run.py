#!/usr/bin/env python3
"""AI外呼数据流程 dry-run 编排入口。

本脚本只创建运行目录、解析需求、写状态和确认清单，不访问真实系统。
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


checkpoint = load_module(
    ROOT / "common" / "断点续跑-checkpoint-runner" / "checkpoint_runner.py",
    "checkpoint_runner",
)
parser_mod = load_module(
    ROOT / "common" / "需求解析-feishu-requirement-parser" / "parse_requirement.py",
    "parse_requirement",
)


STEPS = [
    checkpoint.StepDef("parse_requirement", "解析飞书需求"),
    checkpoint.StepDef("human_confirm_requirement", "人工确认筛选条件"),
    checkpoint.StepDef("prepare_run_plan", "生成运行计划"),
    checkpoint.StepDef("stop_before_real_system", "停在真实系统前"),
]


def build_checklist(parsed: dict[str, Any], run_dir: Path, current_step_cn: str) -> str:
    lines = [
        "# AI外呼数据流程 dry-run 确认清单",
        "",
        "## 解析结果",
        "",
        f"- 城市：{parsed.get('city') or '待确认'}",
        f"- 区县：{', '.join(parsed.get('districts') or []) or '待确认'}",
        f"- 品类：{', '.join(parsed.get('categories') or []) or '待确认'}",
        f"- 日期：{', '.join(parsed.get('dates') or []) or '未指定'}",
        f"- 是否需要人工确认：{'是' if parsed.get('needs_human_review') else '否'}",
        "",
        "## 需要确认的问题",
        "",
    ]
    questions = parsed.get("questions") or []
    if questions:
        lines.extend([f"- {q}" for q in questions])
    else:
        lines.append("- 无。")

    lines.extend(
        [
            "",
            "## 当前执行边界",
            "",
            "- 本次为 dry-run。",
            "- 不登录真实系统。",
            "- 不导出真实业务文件。",
            "- 不上传或导入客户数据。",
            "- 不创建火山外呼任务。",
            "",
            "## 下次恢复点",
            "",
            f"- 运行目录：{run_dir}",
            "- 状态文件：state/run_state.json",
            f"- 当前停在：{current_step_cn}",
        ]
    )
    return "\n".join(lines) + "\n"


def write_checklist(run_dir: Path, parsed: dict[str, Any], current_step_cn: str) -> None:
    checklist = build_checklist(parsed, run_dir, current_step_cn)
    (run_dir / "outputs" / "confirmation_checklist.md").write_text(checklist, encoding="utf-8")


def merge_confirmation(parsed: dict[str, Any], confirmation_path: Path | None) -> dict[str, Any]:
    if confirmation_path is None:
        return parsed
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    merged = dict(parsed)
    for key in ["city", "districts", "categories", "dates"]:
        if key in confirmation:
            merged[key] = confirmation[key]

    missing = []
    if not merged.get("city"):
        missing.append("城市")
    if not merged.get("districts"):
        missing.append("区县")
    if not merged.get("categories"):
        missing.append("品类")
    merged["missing_fields"] = missing
    merged["human_confirmation"] = confirmation
    merged["needs_human_review"] = bool(missing)
    if not missing:
        merged["questions"] = []
    return merged


def resume_run(run_dir: Path, confirm_requirement: bool, confirmation_path: Path | None) -> None:
    state = checkpoint.read_json(run_dir / "state" / "run_state.json")
    parsed = checkpoint.read_json(run_dir / "input" / "parsed_requirement.json")
    contract = checkpoint.check_contract(run_dir)
    if not contract["ok"]:
        print(json.dumps(contract, ensure_ascii=False, indent=2))
        raise SystemExit("执行契约检查未通过，已停止。")

    current_step = state.get("current_step")
    if current_step == "human_confirm_requirement" and confirm_requirement:
        parsed = merge_confirmation(parsed, confirmation_path)
        if parsed.get("missing_fields"):
            write_checklist(run_dir, parsed, "人工确认筛选条件")
            checkpoint.append_log(run_dir, "人工确认信息仍缺少字段，流程继续停在人工确认筛选条件。")
            raise SystemExit(f"仍缺少字段：{', '.join(parsed.get('missing_fields') or [])}")
        (run_dir / "input" / "parsed_requirement.json").write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        checkpoint.update_step(run_dir, "human_confirm_requirement", "completed", "人工确认筛选条件")
        checkpoint.update_step(run_dir, "prepare_run_plan", "completed", "生成运行计划")
        checkpoint.update_step(run_dir, "stop_before_real_system", "pending", "停在真实系统前")
        write_checklist(run_dir, parsed, "停在真实系统前")
        checkpoint.append_log(run_dir, "人工确认已通过，dry-run 已推进到真实系统前。")
    else:
        checkpoint.append_log(run_dir, "resume 检查完成，未推进步骤。")

    print(f"resume 完成，当前步骤：{checkpoint.read_json(run_dir / 'state' / 'run_state.json').get('current_step_cn')}")
    print(f"运行目录：{run_dir}")


def main() -> None:
    argp = argparse.ArgumentParser(description="AI外呼数据流程 dry-run。")
    argp.add_argument("--requirement", help="飞书需求原文。")
    argp.add_argument("--requirement-file", help="飞书需求文本文件。")
    argp.add_argument("--batch", default="001", help="批次号。")
    argp.add_argument("--base-dir", default=str(ROOT), help="skills 根目录。")
    argp.add_argument("--resume-run-dir", help="从已有运行目录继续 dry-run。")
    argp.add_argument("--confirm-requirement", action="store_true", help="确认需求解析结果无误，推进到真实系统前。")
    argp.add_argument("--confirmation-json", help="人工确认后的 JSON 文件，用于补充缺失字段。")
    args = argp.parse_args()

    if args.resume_run_dir:
        confirmation_path = Path(args.confirmation_json).resolve() if args.confirmation_json else None
        resume_run(Path(args.resume_run_dir).resolve(), args.confirm_requirement, confirmation_path)
        return

    if args.requirement_file:
        requirement_text = Path(args.requirement_file).read_text(encoding="utf-8")
    elif args.requirement:
        requirement_text = args.requirement
    else:
        raise SystemExit("必须提供 --requirement 或 --requirement-file。")

    parsed = parser_mod.parse_requirement(requirement_text)
    city = parsed.get("city") or "未指定城市"
    run_dir = checkpoint.ensure_run_dir(
        base_dir=Path(args.base_dir).resolve(),
        workflow_id="ai-call-data-pipeline",
        workflow_name_cn="AI外呼数据流程",
        city=str(city),
        batch=args.batch,
        dry_run=True,
        steps=STEPS,
    )

    (run_dir / "input" / "requirement.txt").write_text(requirement_text.strip() + "\n", encoding="utf-8")
    (run_dir / "input" / "parsed_requirement.json").write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    checkpoint.update_step(run_dir, "parse_requirement", "completed", "解析飞书需求")
    if parsed.get("needs_human_review"):
        checkpoint.update_step(run_dir, "human_confirm_requirement", "pending", "人工确认筛选条件")
        checkpoint.append_log(run_dir, "需求需要人工确认，流程停在人工确认筛选条件。")
        current_step_cn = "人工确认筛选条件"
    else:
        checkpoint.update_step(run_dir, "human_confirm_requirement", "completed", "人工确认筛选条件")
        checkpoint.update_step(run_dir, "prepare_run_plan", "completed", "生成运行计划")
        checkpoint.update_step(run_dir, "stop_before_real_system", "pending", "停在真实系统前")
        current_step_cn = "停在真实系统前"

    write_checklist(run_dir, parsed, current_step_cn)
    checkpoint.append_log(run_dir, "dry-run 完成。")

    print(f"dry-run 完成，运行目录：{run_dir}")
    print(f"确认清单：{run_dir / 'outputs' / 'confirmation_checklist.md'}")


if __name__ == "__main__":
    main()
