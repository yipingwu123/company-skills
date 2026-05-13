#!/usr/bin/env python3
"""火山外呼结果导出 workflow。

默认 dry-run：只生成导出计划和人工确认清单，不调用任何火山 API。
execute 模式中的 API 函数保留为占位实现，因为火山控制台依赖 httpOnly cookie；
Python urllib 直接调用通常会 401，实际执行需使用 agent-browser eval。
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ID = "volcengine-call-result-export"
WORKFLOW_NAME_CN = "火山外呼结果导出"


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
    "checkpoint_runner_volcengine_result_export",
)


STEPS = [
    checkpoint.StepDef("query_task_status", "查询任务状态"),
    checkpoint.StepDef("submit_export", "提交导出任务"),
    checkpoint.StepDef("poll_export_status", "轮询导出状态"),
    checkpoint.StepDef("download_result", "下载结果文件"),
    checkpoint.StepDef("parse_result", "解析结果"),
    checkpoint.StepDef("write_summary", "写入摘要"),
]


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_name(value: str) -> str:
    return checkpoint.clean_part(value, "未指定品类")


def load_auth_context(path: str | None) -> dict[str, Any]:
    if not path:
        raise SystemExit("execute 模式必须提供 --auth-context。")
    auth_path = Path(path).resolve()
    if not auth_path.exists():
        raise SystemExit(f"auth_context 不存在：{auth_path}")
    return json.loads(auth_path.read_text(encoding="utf-8"))


def call_api(auth_context: dict[str, Any], method: str, endpoint: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """调用火山控制台 API。

    重要：火山控制台接口依赖浏览器 httpOnly cookie。Python urllib 直接调用通常会 401。
    请使用 agent-browser eval 执行此调用。
    这里保留 urllib 拼接方式作为接口形状说明，但故意不真实执行。
    """
    base_url = auth_context.get("base_url", "https://console.volcengine.com")
    api_base = auth_context["api_base"]
    url = f"{base_url}{api_base}{endpoint}"
    headers = dict(auth_context.get("headers") or {})
    if method.upper() == "GET" and body:
        url = f"{url}?{urllib.parse.urlencode(body)}"
    _request = urllib.request.Request(
        url,
        data=json.dumps(body or {}).encode("utf-8") if method.upper() != "GET" else None,
        headers=headers,
        method=method.upper(),
    )
    print("请使用 agent-browser eval 执行此调用")
    raise NotImplementedError("请使用 agent-browser eval 执行此调用")


def query_task(auth_context: dict[str, Any], task_id: str) -> dict[str, Any]:
    return call_api(auth_context, "GET", "/QueryTask", {"TaskId": task_id})


def submit_export(auth_context: dict[str, Any], task_id: str) -> dict[str, Any]:
    return call_api(auth_context, "POST", "/ExportTask", {"TaskId": task_id})


def query_export_status(auth_context: dict[str, Any], export_id: str) -> dict[str, Any]:
    return call_api(auth_context, "GET", "/QueryExportStatus", {"ExportId": export_id})


def poll_export_ready(
    auth_context: dict[str, Any],
    export_id: str,
    max_wait_seconds: int = 300,
    interval_seconds: int = 5,
) -> str:
    """轮询导出状态，返回 DownloadUrl。超时或失败抛出 RuntimeError。

    注意：此函数内部调用 call_api()，实际执行需 agent-browser eval。
    """
    deadline = time.monotonic() + max_wait_seconds
    attempt = 0
    status = ""
    while time.monotonic() < deadline:
        attempt += 1
        resp = query_export_status(auth_context, export_id)
        result = resp.get("Result") or resp
        status = result.get("Status", "")
        download_url = result.get("DownloadUrl", "")
        print(f"  轮询 #{attempt}：状态={status}")
        if status == "SUCCESS" and download_url:
            return download_url
        if status == "FAILED":
            raise RuntimeError(f"导出任务失败：{result}")
        time.sleep(interval_seconds)
    raise RuntimeError(f"导出轮询超时（{max_wait_seconds}s），最后状态：{status}")


def download_result_file(download_url: str, output_path: Path) -> Path:
    print("请使用 agent-browser eval 执行此调用")
    raise NotImplementedError("请使用 agent-browser eval 执行此调用")


def confirmation_payload(task_id: str, category: str) -> dict[str, Any]:
    return {
        "approved": True,
        "task_id": task_id,
        "category": category,
        "confirmed_by": "操作人姓名",
        "confirmed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def write_confirmation_checklist(run_dir: Path, task_id: str, category: str, mode: str) -> Path:
    path = run_dir / "outputs" / "confirmation_checklist.md"
    lines = [
        "# 火山外呼结果导出 人工确认清单",
        "",
        f"- 任务 ID：`{task_id}`",
        f"- 品类：{category}",
        f"- 当前模式：{mode}",
        "- dry-run 不调用任何火山 API。",
        "- 真实导出前必须确认任务已完成、任务 ID 正确、品类正确。",
        "",
        "## 人工确认 JSON 模板",
        "",
        "```json",
        json.dumps(confirmation_payload(task_id, category), ensure_ascii=False, indent=2),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def summarize_task_status(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("Result") or response.get("result") or response
    return {
        "status": result.get("Status"),
        "total_count": result.get("TotalCount"),
        "answer_count": result.get("AnswerCount"),
        "connected_count": result.get("ConnectedCount"),
        "raw_keys": sorted(result.keys()) if isinstance(result, dict) else [],
    }


def parse_result_csv(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "total_rows": 0, "answered_count": 0, "not_answered_count": 0, "converted_count": 0}
    total_rows = 0
    answered_count = 0
    converted_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            text = json.dumps(row, ensure_ascii=False)
            if any(word in text for word in ["接通", "已接", "connected", "ANSWERED"]):
                answered_count += 1
            if any(word in text for word in ["有意向", "感兴趣", "转化", "回调"]):
                converted_count += 1
    return {
        "exists": True,
        "total_rows": total_rows,
        "answered_count": answered_count,
        "not_answered_count": max(total_rows - answered_count, 0),
        "converted_count": converted_count,
    }


def validate_confirmation(path: str | None, task_id: str, category: str) -> dict[str, Any]:
    if not path:
        raise SystemExit("--execute-export 必须提供 --confirmation-json。")
    confirmation_path = Path(path).resolve()
    if not confirmation_path.exists():
        raise SystemExit(f"人工确认文件不存在：{confirmation_path}")
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    if confirmation.get("approved") is not True:
        raise SystemExit("人工确认 JSON 中 approved 必须为 true。")
    if confirmation.get("task_id") != task_id:
        raise SystemExit("人工确认 JSON 中 task_id 与参数不一致。")
    if confirmation.get("category") != category:
        raise SystemExit("人工确认 JSON 中 category 与参数不一致。")
    return confirmation


def main() -> None:
    parser = argparse.ArgumentParser(description="火山外呼结果导出 dry-run。")
    parser.add_argument("--task-id", required=True, help="火山任务 ID")
    parser.add_argument("--category", required=True, help="品类名称")
    parser.add_argument("--auth-context", help="volcengine_auth_context.json 路径")
    parser.add_argument("--execute-readonly", action="store_true", help="调用只读 QueryTask 接口")
    parser.add_argument("--execute-export", action="store_true", help="提交导出并下载结果文件")
    parser.add_argument("--confirmation-json", help="人工确认 JSON 路径")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--base-dir", default=str(ROOT))
    args = parser.parse_args()

    dry_run = not args.execute_readonly and not args.execute_export
    run_dir = checkpoint.ensure_run_dir(
        base_dir=Path(args.base_dir).resolve(),
        workflow_id=WORKFLOW_ID,
        workflow_name_cn=WORKFLOW_NAME_CN,
        city=safe_name(args.category),
        batch=args.batch,
        dry_run=dry_run,
        steps=STEPS,
    )

    write_json(run_dir / "input" / "export_request.json", {
        "task_id": args.task_id,
        "category": args.category,
        "execute_readonly": args.execute_readonly,
        "execute_export": args.execute_export,
    })
    checklist_path = write_confirmation_checklist(run_dir, args.task_id, args.category, "dry-run" if dry_run else "execute")

    if dry_run:
        for step in STEPS:
            checkpoint.update_step(run_dir, step.step_id, "skipped", f"dry-run 跳过：{step.name_cn}")
        write_json(run_dir / "outputs" / "result_summary.json", {
            "category": args.category,
            "task_id": args.task_id,
            "dry_run": True,
            "api_called": False,
        })
        checkpoint.check_contract(run_dir)
        print(f"dry-run 完成，运行目录：{run_dir}")
        print(f"确认清单：{checklist_path}")
        return

    auth_context = load_auth_context(args.auth_context)
    task_status: dict[str, Any] | None = None

    if args.execute_readonly or args.execute_export:
        checkpoint.update_step(run_dir, "query_task_status", "running", "查询任务状态")
        task_status = query_task(auth_context, args.task_id)
        status_summary = summarize_task_status(task_status)
        write_json(run_dir / "outputs" / "task_status.json", status_summary)
        write_json(run_dir / "evidence" / "api_responses" / "query_task_response.json", status_summary)
        checkpoint.update_step(run_dir, "query_task_status", "completed", "查询任务状态")

    if args.execute_readonly and not args.execute_export:
        for step_id, name_cn in [
            ("submit_export", "提交导出任务"),
            ("poll_export_status", "轮询导出状态"),
            ("download_result", "下载结果文件"),
            ("parse_result", "解析结果"),
            ("write_summary", "写入摘要"),
        ]:
            checkpoint.update_step(run_dir, step_id, "skipped", f"只读模式跳过：{name_cn}")
        checkpoint.check_contract(run_dir)
        print(f"只读查询完成，运行目录：{run_dir}")
        return

    validate_confirmation(args.confirmation_json, args.task_id, args.category)

    checkpoint.update_step(run_dir, "submit_export", "running", "提交导出任务")
    export_response = submit_export(auth_context, args.task_id)
    export_id = (export_response.get("Result") or {}).get("ExportId") or export_response.get("ExportId")
    if not export_id:
        raise RuntimeError("导出接口未返回 ExportId。")
    checkpoint.update_step(run_dir, "submit_export", "completed", "提交导出任务")

    checkpoint.update_step(run_dir, "poll_export_status", "running", "轮询导出状态")
    download_url = poll_export_ready(auth_context, str(export_id))
    checkpoint.update_step(run_dir, "poll_export_status", "completed", "导出就绪，URL 已获取")

    checkpoint.update_step(run_dir, "download_result", "running", "下载结果文件")
    result_file = run_dir / "outputs" / f"result_{safe_name(args.category)}.csv"
    download_result_file(download_url, result_file)
    checkpoint.update_step(run_dir, "download_result", "completed", "下载结果文件")

    checkpoint.update_step(run_dir, "parse_result", "running", "解析结果")
    summary = parse_result_csv(result_file)
    checkpoint.update_step(run_dir, "parse_result", "completed", "解析结果")

    checkpoint.update_step(run_dir, "write_summary", "running", "写入摘要")
    summary.update({"category": args.category, "task_id": args.task_id, "task_status": summarize_task_status(task_status or {})})
    write_json(run_dir / "outputs" / "result_summary.json", summary)
    checkpoint.update_step(run_dir, "write_summary", "completed", "写入摘要")
    checkpoint.check_contract(run_dir)
    print(f"火山外呼结果导出完成，运行目录：{run_dir}")


if __name__ == "__main__":
    main()
