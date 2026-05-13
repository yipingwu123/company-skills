#!/usr/bin/env python3
"""火山外呼任务创建 dry-run。

根据迈鲸导出的客户文件（按品类分割后），生成任务创建计划和人工确认清单。
默认只生成计划，不调用真实 CreateTask API。

手机号来源两种方式（二选一，优先 --phone-list-json）：
  1. --phone-list-json：fetch_phone_by_id.py 输出的 mobile_list_{品类}.json（含真实号码）
  2. --export-file：按品类拆分后的 xlsx（号码已脱敏，仅用于 dry-run 统计）

真实创建时必须用 --phone-list-json 提供真实号码，否则脱敏号码无效。

用法（dry-run 生成计划）：
    python3 create_task_dry_run.py \\
        --phone-list-json runs/YYYY-MM-DD/.../outputs/mobile_list_餐饮.json \\
        --category 餐饮 \\
        --task-date 2026-05-14 \\
        --number-pool 塔外 \\
        --batch 001

用法（真实创建，需人工确认）：
    python3 create_task_dry_run.py \\
        --phone-list-json runs/.../outputs/mobile_list_餐饮.json \\
        --category 餐饮 \\
        --task-date 2026-05-14 \\
        --number-pool 塔外 \\
        --auth-context runs/.../outputs/volcengine_auth_context.json \\
        --confirmation-json runs/.../input/human_confirmation.json \\
        --execute-create \\
        --batch 001
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_MAP_PATH = Path(__file__).parent / "script_map.json"


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
secrets_loader = load_module(ROOT / "common" / "secrets_loader.py", "secrets_loader")
excel_validator = load_module(
    ROOT / "common" / "Excel处理-excel-transform" / "excel_validator.py",
    "excel_validator",
)


STEPS = [
    checkpoint.StepDef("load_script_map", "加载品类话术映射"),
    checkpoint.StepDef("read_export_file", "读取导出文件"),
    checkpoint.StepDef("build_phone_list", "构建手机号列表"),
    checkpoint.StepDef("generate_task_plan", "生成任务创建计划"),
    checkpoint.StepDef("write_confirmation", "写入人工确认清单"),
    checkpoint.StepDef("validate_human_confirmation", "校验人工确认"),
    checkpoint.StepDef("create_volcengine_task", "调用 CreateTask API"),
    checkpoint.StepDef("verify_task_created", "验证任务已创建"),
]


def load_script_map() -> dict[str, Any]:
    with open(SCRIPT_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


def find_phone_col(headers: list[str], records: list[dict[str, Any]]) -> str | None:
    """按优先级找有效号码列：精确匹配 > 含关键字 > 有实际值。"""
    preferred = ["联系电话", "手机号", "手机", "电话"]
    for name in preferred:
        if name in headers:
            if any(r.get(name, "").strip() for r in records[:10]):
                return name
    # fallback：找第一个含关键字且有值的列
    for h in headers:
        if "手机" in h or "电话" in h or "phone" in h.lower():
            if any(r.get(h, "").strip() for r in records[:10]):
                return h
    return None


def read_phones_from_file(file_path: Path) -> list[str]:
    """读取文件中的手机号列表，复用 excel_validator.read_table。"""
    records = excel_validator.read_table(file_path)
    if not records:
        raise RuntimeError(f"文件无数据行：{file_path}")
    headers = list(records[0].keys())
    phone_col = find_phone_col(headers, records)
    if not phone_col:
        raise RuntimeError(f"未找到手机号列（列头含'手机'或'电话'）。可用列：{headers}")
    phones = [r[phone_col].strip() for r in records if r.get(phone_col, "").strip()]
    if not phones:
        raise RuntimeError(f"列 '{phone_col}' 中没有有效号码。")
    return phones


def read_phones_from_json(json_path: Path) -> list[dict[str, str]]:
    """读取 mobile_list_{category}.json，返回 [{Phone, store_name}, ...]。"""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("phone_list", [])
    if not entries:
        raise RuntimeError(f"phone_list 为空：{json_path}")
    return [{"Phone": e["Phone"], "store_name": e.get("store_name", "")} for e in entries]


def build_phone_list(
    export_file: Path | None,
    phone_list_json: Path | None,
    store_name_col: str | None,
    requires_params: bool,
) -> list[dict[str, Any]]:
    """构建 CreateTask PhoneList 格式。优先使用 phone_list_json（真实号码）。"""
    if phone_list_json is not None:
        entries = read_phones_from_json(phone_list_json)
        phone_list = []
        for e in entries:
            item: dict[str, Any] = {"Phone": e["Phone"]}
            if requires_params:
                item["Params"] = {store_name_col or "name": e.get("store_name", "")}
            phone_list.append(item)
        return phone_list

    if export_file is not None:
        phones = read_phones_from_file(export_file)
        if not phones:
            raise RuntimeError(f"从 {export_file} 未读取到任何手机号。")
        phone_list = []
        for p in phones:
            entry: dict[str, Any] = {"Phone": p}
            if requires_params:
                entry["Params"] = {store_name_col or "name": ""}
            phone_list.append(entry)
        return phone_list

    raise RuntimeError("必须提供 --phone-list-json 或 --export-file。")


def build_task_body(
    task_name: str,
    script_id: str,
    phone_list: list[dict[str, Any]],
    pool_no: str,
    number_id: str,
    task_date: str,
    concurrency: int,
) -> dict[str, Any]:
    start_time = f"{task_date}T09:00:00+08:00"
    end_time = f"{task_date}T20:00:00+08:00"
    return {
        "Name": task_name,
        "Script": script_id,
        "PhoneList": phone_list,
        "DefaultPhoneParams": {},
        "NumberPoolNo": pool_no,
        "NumberList": [number_id],
        "StartTime": start_time,
        "EndTime": end_time,
        "RingAgainTimes": 2,
        "RingAgainInterval": 30,
        "ForbidTimeList": [],
        "Concurrency": concurrency,
        "InPausedStatus": False,
        "EnableDynamicAppend": False,
        "CallOverStopTask": False,
        "ConcurrentModel": 1,
    }


def write_confirmation_checklist(run_dir: Path, plan: dict[str, Any]) -> Path:
    checklist_path = run_dir / "outputs" / "confirmation_checklist.md"
    lines = [
        "# 火山外呼任务创建 人工确认清单",
        "",
        f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 任务参数",
        "",
        f"- 任务名称：{plan['task_name']}",
        f"- 品类：{plan['category']}",
        f"- 话术：{plan['script_name']}（ID: `{plan['script_id']}`）",
        f"- 号码池：{plan['number_pool_name']}（编号: {plan['pool_no']}）",
        f"- 执行日期：{plan['task_date']}",
        f"- 开始时间：{plan['start_time']}",
        f"- 结束时间：{plan['end_time']}",
        f"- 并发数：{plan['concurrency']}",
        f"- 客户数量：{plan['phone_count']}",
        "",
        "## 确认步骤",
        "",
        "- [ ] 话术 ID 正确（与迈鲸品类对应）",
        "- [ ] 号码池正确（塔外/塔思奇）",
        "- [ ] 执行日期正确",
        "- [ ] 客户数量合理",
        "- [ ] 已确认迈鲸导出文件来源正确",
        "",
        "## 确认后操作",
        "",
        "将以下内容保存为 `input/human_confirmation.json`：",
        "",
        "```json",
        json.dumps({
            "approved": True,
            "task_name": plan["task_name"],
            "category": plan["category"],
            "script_id": plan["script_id"],
            "pool_no": plan["pool_no"],
            "task_date": plan["task_date"],
            "phone_count": plan["phone_count"],
            "confirmed_by": "操作人姓名",
            "confirmed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=2),
        "```",
    ]
    checklist_path.write_text("\n".join(lines), encoding="utf-8")
    return checklist_path


def call_create_task(auth_context: dict[str, Any], task_body: dict[str, Any]) -> dict[str, Any]:
    base_url = auth_context["base_url"]
    api_base = auth_context["api_base"]
    headers = dict(auth_context["headers"])
    cookie = auth_context.get("cookie_header", "")
    if cookie:
        headers["Cookie"] = cookie

    url = f"{base_url}{api_base}/CreateTask"
    payload = json.dumps(task_body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser(description="火山外呼任务创建 dry-run。")
    parser.add_argument("--phone-list-json", help="mobile_list_{品类}.json 路径（fetch_phone_by_id 输出，含真实号码）")
    parser.add_argument("--export-file", help="迈鲸导出 xlsx 路径（号码已脱敏，仅 dry-run 用）")
    parser.add_argument("--category", required=True, help="品类名称（如：餐饮、休闲娱乐）")
    parser.add_argument("--task-date", required=True, help="任务执行日期 YYYY-MM-DD")
    parser.add_argument("--number-pool", default="塔外", help="号码池名称")
    parser.add_argument("--concurrency", type=int, default=10, help="并发数")
    parser.add_argument("--auth-context", help="volcengine_auth_context.json 路径")
    parser.add_argument("--confirmation-json", help="人工确认 JSON 路径")
    parser.add_argument("--execute-create", action="store_true", help="真实调用 CreateTask API（默认 dry-run）")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--base-dir", default=str(ROOT))
    args = parser.parse_args()

    dry_run = not args.execute_create

    run_dir = checkpoint.ensure_run_dir(
        base_dir=Path(args.base_dir).resolve(),
        workflow_id="volcengine-call-task-create",
        workflow_name_cn="火山外呼任务创建",
        city=f"{args.category}",
        batch=args.batch,
        dry_run=dry_run,
        steps=STEPS,
    )

    try:
        # 1. 加载话术映射
        checkpoint.update_step(run_dir, "load_script_map", "running", "加载品类话术映射")
        script_map = load_script_map()
        category_scripts = script_map["category_to_script"]
        if args.category not in category_scripts:
            available = list(category_scripts.keys())
            raise SystemExit(f"品类 '{args.category}' 不在映射表中。可用品类：{available}")
        script_info = category_scripts[args.category]
        pool_config = script_map["number_pools"].get(args.number_pool)
        if not pool_config:
            raise SystemExit(f"号码池 '{args.number_pool}' 不在映射表中。")
        checkpoint.update_step(run_dir, "load_script_map", "completed", "加载品类话术映射")

        # 2. 读取手机号来源文件
        checkpoint.update_step(run_dir, "read_export_file", "running", "读取手机号来源文件")
        phone_list_json = Path(args.phone_list_json) if args.phone_list_json else None
        export_file = Path(args.export_file) if args.export_file else None

        if phone_list_json is None and export_file is None:
            raise SystemExit("必须提供 --phone-list-json（推荐）或 --export-file。")
        if phone_list_json is not None and not phone_list_json.exists():
            raise SystemExit(f"phone-list-json 文件不存在：{phone_list_json}")
        if export_file is not None and not export_file.exists():
            raise SystemExit(f"导出文件不存在：{export_file}")

        source_desc = str(phone_list_json or export_file)
        if phone_list_json is None:
            print("警告：未提供 --phone-list-json，使用 xlsx 中的脱敏号码，真实创建时将失败。")
        checkpoint.update_step(run_dir, "read_export_file", "completed", f"来源：{source_desc}")

        # 3. 构建手机号列表
        checkpoint.update_step(run_dir, "build_phone_list", "running", "构建手机号列表")
        phone_list = build_phone_list(
            export_file=export_file,
            phone_list_json=phone_list_json,
            store_name_col=script_info["dynamic_params"].get("store_name_col"),
            requires_params=script_info["requires_params"],
        )
        checkpoint.update_step(run_dir, "build_phone_list", "completed", f"构建手机号列表，共 {len(phone_list)} 条")

        # 4. 生成任务计划
        checkpoint.update_step(run_dir, "generate_task_plan", "running", "生成任务创建计划")
        task_name = f"{args.category}-{args.task_date}-{args.batch}"
        task_body = build_task_body(
            task_name=task_name,
            script_id=script_info["script_id"],
            phone_list=phone_list,
            pool_no=pool_config["pool_no"],
            number_id=pool_config["number_id"],
            task_date=args.task_date,
            concurrency=args.concurrency,
        )
        plan = {
            "task_name": task_name,
            "category": args.category,
            "script_id": script_info["script_id"],
            "script_name": script_info["name"],
            "pool_no": pool_config["pool_no"],
            "number_pool_name": args.number_pool,
            "task_date": args.task_date,
            "start_time": task_body["StartTime"],
            "end_time": task_body["EndTime"],
            "concurrency": args.concurrency,
            "phone_count": len(phone_list),
            "dry_run": dry_run,
        }
        checkpoint.write_json(run_dir / "outputs" / "task_plan.json", plan)

        # 保存脱敏的手机号列表摘要（不保存完整号码）
        checkpoint.write_json(run_dir / "outputs" / "phone_list_summary.json", {
            "count": len(phone_list),
            "sample_masked": [secrets_loader.mask_secret(p["Phone"]) for p in phone_list[:3]],
        })

        checkpoint.update_step(run_dir, "generate_task_plan", "completed", "生成任务创建计划")

        # 5. 写确认清单
        checkpoint.update_step(run_dir, "write_confirmation", "running", "写入人工确认清单")
        checklist_path = write_confirmation_checklist(run_dir, plan)
        checkpoint.update_step(run_dir, "write_confirmation", "completed", "写入人工确认清单")

        if dry_run:
            checkpoint.update_step(run_dir, "validate_human_confirmation", "skipped", "dry-run 跳过")
            checkpoint.update_step(run_dir, "create_volcengine_task", "skipped", "dry-run 跳过")
            checkpoint.update_step(run_dir, "verify_task_created", "skipped", "dry-run 跳过")
            print(f"\ndry-run 完成，运行目录：{run_dir}")
            print(f"确认清单：{checklist_path}")
            print("\n请人工确认以下内容后，填写 human_confirmation.json 并使用 --execute-create 执行真实创建。")
            print(f"  品类：{args.category}，话术：{script_info['name']}，客户数：{len(phone_list)}")
            return

        # 6. 校验人工确认
        checkpoint.update_step(run_dir, "validate_human_confirmation", "running", "校验人工确认")
        if not args.confirmation_json:
            raise SystemExit("--execute-create 模式必须提供 --confirmation-json。")
        if not args.auth_context:
            raise SystemExit("--execute-create 模式必须提供 --auth-context。")

        confirmation_path = Path(args.confirmation_json)
        if not confirmation_path.exists():
            raise SystemExit(f"人工确认文件不存在：{confirmation_path}")
        with open(confirmation_path, encoding="utf-8") as f:
            confirmation = json.load(f)

        if not confirmation.get("approved"):
            raise SystemExit("人工确认 JSON 中 approved 不为 true，终止执行。")
        if confirmation.get("script_id") != script_info["script_id"]:
            raise SystemExit(f"确认 JSON 中 script_id 与计划不符。期望：{script_info['script_id']}")
        if confirmation.get("phone_count") != len(phone_list):
            raise SystemExit(f"确认 JSON 中 phone_count={confirmation.get('phone_count')}，实际={len(phone_list)}，不符。")
        checkpoint.update_step(run_dir, "validate_human_confirmation", "completed", "校验人工确认")

        # 7. 调用 CreateTask
        checkpoint.update_step(run_dir, "create_volcengine_task", "running", "调用 CreateTask API")
        auth_context_path = Path(args.auth_context)
        with open(auth_context_path, encoding="utf-8") as f:
            auth_context = json.load(f)

        result = call_create_task(auth_context, task_body)
        result_summary = {
            "response_code": result.get("ResponseMetadata", {}).get("Error"),
            "task_id": result.get("Result", {}).get("TaskId"),
            "raw_keys": list(result.keys()),
        }
        checkpoint.write_json(run_dir / "evidence" / "api_responses" / "create_task_result.json", result_summary)

        if result.get("ResponseMetadata", {}).get("Error"):
            raise RuntimeError(f"CreateTask 返回错误：{result['ResponseMetadata']['Error']}")
        task_id = result.get("Result", {}).get("TaskId")
        if not task_id:
            raise RuntimeError(f"CreateTask 未返回 TaskId。响应键：{list(result.keys())}")

        checkpoint.update_step(run_dir, "create_volcengine_task", "completed", f"任务已创建，TaskId={task_id}")

        # 8. 验证任务已创建
        checkpoint.update_step(run_dir, "verify_task_created", "running", "验证任务已创建")
        checkpoint.write_json(run_dir / "outputs" / "created_task.json", {
            "task_id": task_id,
            "task_name": task_name,
            "category": args.category,
            "phone_count": len(phone_list),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        checkpoint.update_step(run_dir, "verify_task_created", "completed", "验证任务已创建")

        checkpoint.append_log(run_dir, f"火山外呼任务创建完成，TaskId={task_id}。")
        print(f"\n任务创建成功！TaskId：{task_id}")
        print(f"运行目录：{run_dir}")

    except Exception as exc:
        checkpoint.update_step(
            run_dir, "create_volcengine_task", "failed", "调用 CreateTask API",
            {"failure_reason": str(exc), "resume_step": "create_volcengine_task"},
        )
        raise


if __name__ == "__main__":
    main()
