#!/usr/bin/env python3
"""迈鲸公海客户筛选计数 dry-run。

把飞书需求或筛选计划转换为公海客户列表 API 查询参数。
默认只生成本地查询计划；只有显式传入 --execute-readonly 时，才访问真实 API 读取 total。
不保存完整客户明细，不导出文件。
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
LIST_ENDPOINT = "/customer/public/list"


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
plan_mod = load_module(WORKFLOW_DIR / "plan_dry_run.py", "maijing_plan_dry_run")


STEPS = [
    checkpoint.StepDef("parse_or_load_filter_plan", "解析或读取筛选计划"),
    checkpoint.StepDef("build_api_query_plan", "生成 API 查询计划"),
    checkpoint.StepDef("readonly_count_check", "只读读取筛选结果数量"),
    checkpoint.StepDef("human_confirm_filter_count", "人工确认筛选数量"),
    checkpoint.StepDef("stop_before_export", "停在真实导出前"),
]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_auth_context(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("system") != "maijing":
        raise RuntimeError("认证上下文不是 maijing。")
    token = data.get("headers", {}).get("Authorization") or ""
    if not token.startswith("Bearer "):
        raise RuntimeError("认证上下文缺少 Authorization token。")
    return data


def auth_headers(auth: dict[str, Any]) -> dict[str, str]:
    headers = dict(auth.get("headers") or {})
    headers.setdefault("User-Agent", "Mozilla/5.0")
    headers.setdefault("Accept", "application/json, text/plain, */*")
    headers["Content-Type"] = "application/json"
    return headers


def load_requirement(args: argparse.Namespace) -> str | None:
    if args.requirement_file:
        return Path(args.requirement_file).read_text(encoding="utf-8")
    if args.requirement:
        return args.requirement
    return None


def load_filter_plan(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    if args.filter_plan:
        plan = json.loads(Path(args.filter_plan).read_text(encoding="utf-8"))
        return plan, None, None
    requirement = load_requirement(args)
    if not requirement:
        raise SystemExit("必须提供 --requirement、--requirement-file 或 --filter-plan。")
    parsed = parser_mod.parse_requirement(requirement)
    plan = plan_mod.build_filter_plan(parsed)
    return plan, parsed, requirement


def load_param_map(path: Path | None) -> dict[str, Any]:
    map_path = path or WORKFLOW_DIR / "filter_param_map.example.json"
    return json.loads(map_path.read_text(encoding="utf-8"))


def normalize_values(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def add_param(params: dict[str, list[str]], name: str | None, value: Any, mode: str = "single") -> None:
    if not name:
        return
    if value is None or value == "":
        return
    values = normalize_values(value)
    if not values:
        return
    params.setdefault(name, [])
    if mode == "csv":
        params[name].append(",".join(values))
        return
    params[name].extend(values)


def build_query_params(plan: dict[str, Any], param_map: dict[str, Any]) -> dict[str, Any]:
    dynamic = plan.get("dynamic_filters") or {}
    fixed = plan.get("fixed_filters") or {}
    params: dict[str, list[str]] = {
        "pageNum": ["1"],
        "pageSize": ["1"],
    }
    unmapped: list[str] = []
    unverified: list[str] = []

    for field, value in dynamic.items():
        config = (param_map.get("dynamic_filters") or {}).get(field, {})
        api_param = config.get("api_param")
        if not api_param:
            unmapped.append(f"dynamic_filters.{field}")
            continue
        if not config.get("verified"):
            unverified.append(f"dynamic_filters.{field}:{api_param}")
        add_param(params, api_param, value, config.get("mode", "single"))

    for field, value in fixed.items():
        config = (param_map.get("fixed_filters") or {}).get(field, {})
        api_param = config.get("api_param")
        if not api_param:
            unmapped.append(f"fixed_filters.{field}")
            continue
        if not config.get("verified"):
            unverified.append(f"fixed_filters.{field}:{api_param}")
        mapped_value = config.get("value", value)
        add_param(params, api_param, mapped_value, config.get("mode", "single"))

    return {
        "endpoint": LIST_ENDPOINT,
        "method": "GET",
        "params": params,
        "query_string": urllib.parse.urlencode(params, doseq=True),
        "param_map_status": param_map.get("status", "unknown"),
        "unmapped_filters": unmapped,
        "unverified_params": unverified,
        "safe_to_execute_without_confirmation": not unmapped and not unverified and param_map.get("status") == "verified",
    }


def request_json(path: str, headers: dict[str, str], params: dict[str, list[str]]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{BASE_URL}{path}?{query}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def summarize_list_response(value: dict[str, Any]) -> dict[str, Any]:
    rows = value.get("rows")
    if rows is None and isinstance(value.get("data"), dict):
        rows = value["data"].get("rows") or value["data"].get("list")
    total = value.get("total")
    if total is None and isinstance(value.get("data"), dict):
        total = value["data"].get("total")
    return {
        "code": value.get("code"),
        "msg": value.get("msg"),
        "total": total,
        "row_count_in_response": len(rows) if isinstance(rows, list) else None,
        "first_row_keys_only": sorted(rows[0].keys()) if isinstance(rows, list) and rows and isinstance(rows[0], dict) else [],
        "customer_rows_saved": False,
    }


def write_checklist(run_dir: Path, plan: dict[str, Any], query_plan: dict[str, Any], count_summary: dict[str, Any] | None) -> None:
    dynamic = plan.get("dynamic_filters") or {}
    fixed = plan.get("fixed_filters") or {}
    lines = [
        "# 迈鲸公海客户筛选计数 dry-run 确认清单",
        "",
        "## 筛选条件",
        "",
        f"- 城市：{dynamic.get('city') or '待确认'}",
        f"- 区县：{', '.join(dynamic.get('districts') or []) or '待确认'}",
        f"- 品类：{', '.join(dynamic.get('categories') or []) or '待确认'}",
        f"- 固定条件：{json.dumps(fixed, ensure_ascii=False)}",
        "",
        "## API 参数状态",
        "",
        f"- 参数映射状态：{query_plan.get('param_map_status')}",
        f"- 未映射筛选项：{', '.join(query_plan.get('unmapped_filters') or []) or '无'}",
        f"- 未验证参数：{', '.join(query_plan.get('unverified_params') or []) or '无'}",
        "",
    ]
    if count_summary:
        lines.extend([
            "## 只读计数结果",
            "",
            f"- code：{count_summary.get('code')}",
            f"- msg：{count_summary.get('msg')}",
            f"- total：{count_summary.get('total')}",
            "- 未保存完整客户行，未导出文件。",
            "",
        ])
    else:
        lines.extend([
            "## 只读计数结果",
            "",
            "- 本次未访问真实 API，只生成查询计划。",
            "",
        ])
    lines.extend([
        "## 当前停点",
        "",
        "- 停在真实导出前。",
        "- 进入真实导出前必须人工确认筛选条件、参数映射和 total。",
    ])
    (run_dir / "outputs" / "confirmation_checklist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="迈鲸公海客户筛选计数 dry-run。")
    parser.add_argument("--requirement")
    parser.add_argument("--requirement-file")
    parser.add_argument("--filter-plan")
    parser.add_argument("--param-map")
    parser.add_argument("--auth-context")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--execute-readonly", action="store_true", help="访问真实只读 API 读取 total。")
    parser.add_argument("--allow-unverified-params", action="store_true", help="允许使用未验证参数访问只读 API。")
    args = parser.parse_args()

    plan, parsed, requirement = load_filter_plan(args)
    city = (plan.get("dynamic_filters") or {}).get("city") or "未指定城市"
    run_dir = checkpoint.ensure_run_dir(
        base_dir=ROOT,
        workflow_id="maijing-public-sea-filter-count-dry-run",
        workflow_name_cn="迈鲸公海客户筛选计数 dry-run",
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

    checkpoint.update_step(run_dir, "build_api_query_plan", "running", "生成 API 查询计划")
    param_map = load_param_map(Path(args.param_map).resolve() if args.param_map else None)
    query_plan = build_query_params(plan, param_map)
    write_json(run_dir / "outputs" / "filter_api_query_plan.json", query_plan)
    checkpoint.update_step(run_dir, "build_api_query_plan", "completed", "生成 API 查询计划")

    count_summary = None
    if args.execute_readonly:
        if not args.auth_context:
            raise SystemExit("--execute-readonly 必须同时提供 --auth-context。")
        if query_plan.get("unmapped_filters"):
            raise SystemExit("存在未映射筛选项，不能访问真实 API。请先完善 param-map。")
        if query_plan.get("unverified_params") and not args.allow_unverified_params:
            raise SystemExit("存在未验证参数。若只读探测，请显式传入 --allow-unverified-params。")
        checkpoint.update_step(run_dir, "readonly_count_check", "running", "只读读取筛选结果数量")
        auth = load_auth_context(Path(args.auth_context).resolve())
        response = request_json(LIST_ENDPOINT, auth_headers(auth), query_plan["params"])
        count_summary = summarize_list_response(response)
        write_json(run_dir / "evidence" / "api_responses" / "filter_count_summary.json", count_summary)
        checkpoint.update_step(run_dir, "readonly_count_check", "completed", "只读读取筛选结果数量")
    else:
        checkpoint.update_step(run_dir, "readonly_count_check", "skipped", "只读读取筛选结果数量")

    write_checklist(run_dir, plan, query_plan, count_summary)
    checkpoint.update_step(run_dir, "human_confirm_filter_count", "pending", "人工确认筛选数量")
    checkpoint.update_step(run_dir, "stop_before_export", "pending", "停在真实导出前")
    checkpoint.check_contract(run_dir)
    checkpoint.append_log(run_dir, "迈鲸公海客户筛选计数 dry-run 完成，未导出。")

    print(f"迈鲸公海客户筛选计数 dry-run 完成，运行目录：{run_dir}")
    print(f"API 查询计划：{run_dir / 'outputs' / 'filter_api_query_plan.json'}")
    print(f"确认清单：{run_dir / 'outputs' / 'confirmation_checklist.md'}")


if __name__ == "__main__":
    main()
