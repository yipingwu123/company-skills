#!/usr/bin/env python3
"""迈鲸公海客户导出预检 dry-run。

复用已确认的筛选 API 参数，生成导出计划。
默认不访问真实 API；显式传入 --execute-readonly-stat 时，只读取导出统计接口。
不调用导出接口，不创建异步导出任务，不下载客户文件。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = Path(__file__).resolve().parent
BASE_URL = "https://mj-whale.com/prod-api"
EXPORT_STAT_ENDPOINT = "/customer/public/export/stat"
EXPORT_ASYNC_ENDPOINT = "/customer/public/export/async"
EXPORT_DOWNLOAD_ENDPOINT = "/customer/public/export"
ASYNC_EXPORT_THRESHOLD = 10_000


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
filter_count = load_module(WORKFLOW_DIR / "filter_count_dry_run.py", "maijing_filter_count_for_export_preflight")


STEPS = [
    checkpoint.StepDef("parse_or_load_filter_plan", "解析或读取筛选计划"),
    checkpoint.StepDef("build_export_plan", "生成导出预检计划"),
    checkpoint.StepDef("readonly_export_stat", "只读读取导出统计"),
    checkpoint.StepDef("human_confirm_export_plan", "人工确认导出计划"),
    checkpoint.StepDef("stop_before_export", "停在真实导出前"),
]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request_json(path: str, headers: dict[str, str], params: dict[str, list[str]]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{BASE_URL}{path}?{query}" if query else f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=120) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def summarize_export_stat(response: dict[str, Any]) -> dict[str, Any]:
    stat_total = response.get("data")
    if isinstance(stat_total, dict):
        stat_total = stat_total.get("total") or stat_total.get("count")
    try:
        stat_total_int = int(stat_total) if stat_total is not None else None
    except (TypeError, ValueError):
        stat_total_int = None
    return {
        "code": response.get("code"),
        "msg": response.get("msg"),
        "export_stat_total": stat_total_int,
        "raw_data_type": type(response.get("data")).__name__,
        "business_rows_saved": False,
    }


def pick_export_route(total: int | None, threshold: int = ASYNC_EXPORT_THRESHOLD) -> dict[str, Any]:
    if total is None:
        return {
            "route": "unknown",
            "reason_cn": "未读取导出统计，无法判断同步导出或异步导出。",
            "threshold": threshold,
        }
    if total > threshold:
        return {
            "route": "async_task",
            "reason_cn": f"导出数量 {total} 大于 {threshold}，前端会创建异步导出任务。",
            "threshold": threshold,
            "endpoint": EXPORT_ASYNC_ENDPOINT,
            "method": "POST",
            "will_execute_in_dry_run": False,
        }
    return {
        "route": "sync_download",
        "reason_cn": f"导出数量 {total} 不大于 {threshold}，前端会走同步下载。",
        "threshold": threshold,
        "endpoint": EXPORT_DOWNLOAD_ENDPOINT,
        "method": "GET",
        "will_execute_in_dry_run": False,
    }


def build_export_plan(query_plan: dict[str, Any], stat_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    total = stat_summary.get("export_stat_total") if stat_summary else None
    return {
        "system": "maijing",
        "module": "public_sea_customer",
        "source_list_endpoint": query_plan["endpoint"],
        "filter_params": query_plan["params"],
        "filter_query_string": query_plan["query_string"],
        "export_stat": {
            "endpoint": EXPORT_STAT_ENDPOINT,
            "method": "GET",
            "executed": stat_summary is not None,
            "summary": stat_summary,
        },
        "export_routes": {
            "sync_download": {
                "endpoint": EXPORT_DOWNLOAD_ENDPOINT,
                "method": "GET",
                "dry_run_forbidden": True,
            },
            "async_task": {
                "endpoint": EXPORT_ASYNC_ENDPOINT,
                "method": "POST",
                "dry_run_forbidden": True,
            },
        },
        "recommended_route": pick_export_route(total),
        "dry_run": True,
        "export_executed": False,
        "download_executed": False,
        "requires_human_confirmation": True,
    }


def write_checklist(run_dir: Path, plan: dict[str, Any], export_plan: dict[str, Any]) -> None:
    dynamic = plan.get("dynamic_filters") or {}
    fixed = plan.get("fixed_filters") or {}
    stat = (export_plan.get("export_stat") or {}).get("summary") or {}
    route = export_plan.get("recommended_route") or {}
    lines = [
        "# 迈鲸公海客户导出预检 dry-run 确认清单",
        "",
        "## 筛选条件",
        "",
        f"- 城市：{dynamic.get('city') or '待确认'}",
        f"- 区县：{', '.join(dynamic.get('districts') or []) or '待确认'}",
        f"- 品类：{', '.join(dynamic.get('categories') or []) or '待确认'}",
        f"- 固定条件：{json.dumps(fixed, ensure_ascii=False)}",
        "",
        "## 导出预检",
        "",
        f"- 导出统计接口：{EXPORT_STAT_ENDPOINT}",
        f"- 统计是否已读取：{bool((export_plan.get('export_stat') or {}).get('executed'))}",
        f"- 导出统计 total：{stat.get('export_stat_total', '未读取')}",
        f"- 推荐导出路径：{route.get('route')}",
        f"- 推荐原因：{route.get('reason_cn')}",
        "",
        "## 当前停点",
        "",
        "- 已停在真实导出前。",
        "- 未调用 `/customer/public/export/async`。",
        "- 未调用 `/customer/public/export` 下载文件。",
        "- 继续真实导出前必须人工确认筛选条件、导出统计和导出路径。",
    ]
    (run_dir / "outputs" / "export_preflight_checklist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="迈鲸公海客户导出预检 dry-run。")
    parser.add_argument("--requirement")
    parser.add_argument("--requirement-file")
    parser.add_argument("--filter-plan")
    parser.add_argument("--param-map")
    parser.add_argument("--auth-context")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--execute-readonly-stat", action="store_true", help="只读取导出统计接口，不导出。")
    args = parser.parse_args()

    plan, parsed, requirement = filter_count.load_filter_plan(args)
    city = (plan.get("dynamic_filters") or {}).get("city") or "未指定城市"
    run_dir = checkpoint.ensure_run_dir(
        base_dir=ROOT,
        workflow_id="maijing-public-sea-export-preflight-dry-run",
        workflow_name_cn="迈鲸公海客户导出预检 dry-run",
        city=city,
        batch=args.batch,
        dry_run=True,
        steps=STEPS,
    )

    checkpoint.update_step(run_dir, "parse_or_load_filter_plan", "running", "解析或读取筛选计划")
    if requirement:
        (run_dir / "input" / "requirement.txt").write_text(requirement.strip() + "\n", encoding="utf-8")
    if parsed:
        write_json(run_dir / "input" / "parsed_requirement.json", parsed)
    write_json(run_dir / "input" / "filter_plan.json", plan)
    checkpoint.update_step(run_dir, "parse_or_load_filter_plan", "completed", "解析或读取筛选计划")

    checkpoint.update_step(run_dir, "build_export_plan", "running", "生成导出预检计划")
    param_map = filter_count.load_param_map(Path(args.param_map).resolve() if args.param_map else None)
    query_plan = filter_count.build_query_params(plan, param_map)
    if query_plan.get("unmapped_filters") or query_plan.get("unverified_params"):
        raise SystemExit("存在未映射或未验证参数，不能生成导出预检。请先完成筛选参数确认。")
    write_json(run_dir / "outputs" / "filter_api_query_plan.json", query_plan)
    export_plan = build_export_plan(query_plan)
    write_json(run_dir / "outputs" / "export_preflight_plan.json", export_plan)
    checkpoint.update_step(run_dir, "build_export_plan", "completed", "生成导出预检计划")

    stat_summary = None
    if args.execute_readonly_stat:
        if not args.auth_context:
            raise SystemExit("--execute-readonly-stat 必须同时提供 --auth-context。")
        checkpoint.update_step(run_dir, "readonly_export_stat", "running", "只读读取导出统计")
        auth = filter_count.load_auth_context(Path(args.auth_context).resolve())
        response = request_json(EXPORT_STAT_ENDPOINT, filter_count.auth_headers(auth), query_plan["params"])
        stat_summary = summarize_export_stat(response)
        write_json(run_dir / "evidence" / "api_responses" / "export_stat_summary.json", stat_summary)
        export_plan = build_export_plan(query_plan, stat_summary)
        write_json(run_dir / "outputs" / "export_preflight_plan.json", export_plan)
        checkpoint.update_step(run_dir, "readonly_export_stat", "completed", "只读读取导出统计")
    else:
        checkpoint.update_step(run_dir, "readonly_export_stat", "skipped", "只读读取导出统计")

    write_checklist(run_dir, plan, export_plan)
    checkpoint.update_step(run_dir, "human_confirm_export_plan", "pending", "人工确认导出计划")
    checkpoint.update_step(run_dir, "stop_before_export", "pending", "停在真实导出前")
    checkpoint.check_contract(run_dir)
    checkpoint.append_log(run_dir, "迈鲸公海客户导出预检 dry-run 完成，未导出，未下载。")

    print(f"迈鲸公海客户导出预检 dry-run 完成，运行目录：{run_dir}")
    print(f"导出预检计划：{run_dir / 'outputs' / 'export_preflight_plan.json'}")
    print(f"确认清单：{run_dir / 'outputs' / 'export_preflight_checklist.md'}")


if __name__ == "__main__":
    main()
