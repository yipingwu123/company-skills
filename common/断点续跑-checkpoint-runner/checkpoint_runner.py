#!/usr/bin/env python3
"""自动化断点续跑工具。

只使用 Python 标准库。负责创建运行目录、写入状态文件、追加中文日志。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


CN_TZ = timezone(timedelta(hours=8))


STATUS_VALUES = {
    "not_started",
    "running",
    "completed",
    "pending",
    "failed",
    "skipped",
}


@dataclass
class StepDef:
    step_id: str
    name_cn: str
    status: str = "not_started"


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")


def clean_part(value: Optional[str], fallback: str) -> str:
    if not value:
        return fallback
    blocked = set('/\\:*?"<>|')
    cleaned = "".join("-" if ch in blocked else ch for ch in str(value).strip())
    cleaned = "-".join(part for part in cleaned.split() if part)
    return cleaned or fallback


def make_run_id(workflow_id: str, city: Optional[str], batch: Optional[str]) -> str:
    return "-".join(
        [
            clean_part(workflow_id, "workflow"),
            clean_part(city, "未指定城市"),
            clean_part(batch, "001"),
        ]
    )


def ensure_run_dir(
    base_dir: Path,
    workflow_id: str,
    workflow_name_cn: str,
    city: Optional[str] = None,
    batch: Optional[str] = None,
    dry_run: bool = True,
    steps: Optional[Iterable[StepDef]] = None,
) -> Path:
    run_id = make_run_id(workflow_id, city, batch)
    run_dir = base_dir / "runs" / today_str() / run_id

    for name in ["input", "state", "outputs", "evidence", "logs"]:
        (run_dir / name).mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence" / "screenshots").mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence" / "api_responses").mkdir(parents=True, exist_ok=True)

    state_path = run_dir / "state" / "run_state.json"
    if not state_path.exists():
        state = {
            "run_id": run_id,
            "workflow_id": workflow_id,
            "workflow_name_cn": workflow_name_cn,
            "dry_run": dry_run,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "current_step": None,
            "current_step_cn": None,
            "steps": {},
        }
        for step in steps or []:
            state["steps"][step.step_id] = {
                "name_cn": step.name_cn,
                "status": step.status,
            }
        write_json(state_path, state)
        append_log(run_dir, f"创建运行目录：{run_dir}")
    return run_dir


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_log(run_dir: Path, message: str) -> None:
    log_path = run_dir / "logs" / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{now_iso()}] {message}\n")


def update_step(
    run_dir: Path,
    step_id: str,
    status: str,
    name_cn: Optional[str] = None,
    error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if status not in STATUS_VALUES:
        raise ValueError(f"非法状态：{status}")

    state_path = run_dir / "state" / "run_state.json"
    state = read_json(state_path)
    step = state.setdefault("steps", {}).setdefault(step_id, {})
    if name_cn:
        step["name_cn"] = name_cn
    step.setdefault("name_cn", step_id)
    step["status"] = status
    if status == "running":
        step["started_at"] = now_iso()
    if status in {"completed", "pending", "failed", "skipped"}:
        step["finished_at"] = now_iso()
    if error:
        step["error"] = error

    state["current_step"] = step_id
    state["current_step_cn"] = step.get("name_cn")
    state["updated_at"] = now_iso()
    write_json(state_path, state)
    append_log(run_dir, f"步骤状态更新：{step.get('name_cn')} -> {status}")
    return state


def first_unfinished_step(run_dir: Path) -> Optional[str]:
    state = read_json(run_dir / "state" / "run_state.json")
    for step_id, step in state.get("steps", {}).items():
        if step.get("status") not in {"completed", "skipped"}:
            return step_id
    return None


def check_contract(run_dir: Path, contract_path: Optional[Path] = None) -> Dict[str, Any]:
    if contract_path is None:
        contract_path = Path(__file__).resolve().parents[2] / "automation_contract.json"
    contract = read_json(contract_path)
    missing = []
    warnings = []

    for dirname in contract.get("required_run_directories", []):
        if not (run_dir / dirname).is_dir():
            missing.append(f"缺少目录：{dirname}")

    state_rel = contract.get("required_state_file", "state/run_state.json")
    state_path = run_dir / state_rel
    state = {}
    if not state_path.exists():
        missing.append(f"缺少状态文件：{state_rel}")
    else:
        state = read_json(state_path)
        if "workflow_id" not in state:
            missing.append("状态文件缺少 workflow_id")
        if "dry_run" not in state:
            missing.append("状态文件缺少 dry_run")
        if "steps" not in state or not isinstance(state.get("steps"), dict):
            missing.append("状态文件缺少 steps")
        for step_id, step in state.get("steps", {}).items():
            status = step.get("status")
            if status not in STATUS_VALUES:
                missing.append(f"步骤 {step_id} 状态非法：{status}")
            if not step.get("name_cn"):
                warnings.append(f"步骤 {step_id} 缺少中文名称")

    result = {
        "run_dir": str(run_dir),
        "contract_path": str(contract_path),
        "ok": not missing,
        "missing_items": missing,
        "warnings": warnings,
        "current_step": state.get("current_step"),
        "current_step_cn": state.get("current_step_cn"),
        "next_unfinished_step": first_unfinished_step(run_dir) if state else None,
    }
    if state:
        append_log(run_dir, f"执行契约检查：{'通过' if result['ok'] else '未通过'}")
    return result


def guard_action(run_dir: Path, action: str, contract_path: Optional[Path] = None) -> Dict[str, Any]:
    if contract_path is None:
        contract_path = Path(__file__).resolve().parents[2] / "automation_contract.json"
    contract = read_json(contract_path)
    state = read_json(run_dir / contract.get("required_state_file", "state/run_state.json"))
    dry_run = bool(state.get("dry_run", True))
    forbidden = set(contract.get("dry_run_forbidden_actions", []))
    requires_confirmation = set(contract.get("always_require_human_confirmation", []))

    allowed = True
    reasons = []
    if dry_run and action in forbidden:
        allowed = False
        reasons.append(f"当前 dry_run=true，禁止动作：{action}")
    if action in requires_confirmation:
        allowed = False
        reasons.append(f"动作需要人工确认后才能执行：{action}")

    result = {
        "run_dir": str(run_dir),
        "action": action,
        "dry_run": dry_run,
        "allowed": allowed,
        "reasons": reasons,
    }
    append_log(run_dir, f"动作保护检查：{action} -> {'允许' if allowed else '禁止'}")
    return result


def parse_steps(raw_steps: str) -> list[StepDef]:
    result = []
    for item in raw_steps.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            step_id, name_cn = item.split(":", 1)
        else:
            step_id, name_cn = item, item
        result.append(StepDef(step_id=step_id.strip(), name_cn=name_cn.strip()))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="创建或更新自动化运行状态。")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="创建运行目录和初始状态。")
    create.add_argument("--base-dir", default=".", help="skills 根目录。")
    create.add_argument("--workflow-id", required=True)
    create.add_argument("--workflow-name-cn", required=True)
    create.add_argument("--city")
    create.add_argument("--batch", default="001")
    create.add_argument("--dry-run", action="store_true", default=True)
    create.add_argument("--steps", default="")

    update = sub.add_parser("update-step", help="更新步骤状态。")
    update.add_argument("--run-dir", required=True)
    update.add_argument("--step-id", required=True)
    update.add_argument("--name-cn")
    update.add_argument("--status", required=True, choices=sorted(STATUS_VALUES))

    next_step = sub.add_parser("next-step", help="输出第一个未完成步骤。")
    next_step.add_argument("--run-dir", required=True)

    check = sub.add_parser("check-contract", help="检查运行目录是否符合执行契约。")
    check.add_argument("--run-dir", required=True)
    check.add_argument("--contract")

    guard = sub.add_parser("guard-action", help="检查某个动作在当前运行状态下是否允许。")
    guard.add_argument("--run-dir", required=True)
    guard.add_argument("--action", required=True)
    guard.add_argument("--contract")

    args = parser.parse_args()

    if args.command == "create":
        run_dir = ensure_run_dir(
            base_dir=Path(args.base_dir).resolve(),
            workflow_id=args.workflow_id,
            workflow_name_cn=args.workflow_name_cn,
            city=args.city,
            batch=args.batch,
            dry_run=args.dry_run,
            steps=parse_steps(args.steps),
        )
        print(run_dir)
    elif args.command == "update-step":
        update_step(Path(args.run_dir).resolve(), args.step_id, args.status, args.name_cn)
        print(Path(args.run_dir).resolve())
    elif args.command == "next-step":
        print(first_unfinished_step(Path(args.run_dir).resolve()) or "")
    elif args.command == "check-contract":
        contract_path = Path(args.contract).resolve() if args.contract else None
        print(json.dumps(check_contract(Path(args.run_dir).resolve(), contract_path), ensure_ascii=False, indent=2))
    elif args.command == "guard-action":
        contract_path = Path(args.contract).resolve() if args.contract else None
        result = guard_action(Path(args.run_dir).resolve(), args.action, contract_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["allowed"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
