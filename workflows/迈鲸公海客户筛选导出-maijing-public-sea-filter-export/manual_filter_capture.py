#!/usr/bin/env python3
"""迈鲸公海客户筛选参数人工捕获。

用于确认页面筛选控件对应的 `/customer/public/list` 查询参数。
脚本打开已登录页面并监听列表请求；由人工在页面上设置筛选条件并点击查询。
脚本只保存请求参数和响应摘要，不保存完整客户明细，不点击导出。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = Path(__file__).resolve().parent
DEFAULT_URL = "https://mj-whale.com/customer/publicSeas"
LIST_PATH = "/prod-api/customer/public/list"


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
plan_mod = load_module(WORKFLOW_DIR / "plan_dry_run.py", "maijing_plan_dry_run_for_capture")


STEPS = [
    checkpoint.StepDef("load_auth_context", "读取迈鲸认证上下文"),
    checkpoint.StepDef("prepare_filter_plan", "准备筛选计划"),
    checkpoint.StepDef("open_public_sea_page", "打开公海客户页面"),
    checkpoint.StepDef("capture_filter_requests", "捕获筛选请求参数"),
    checkpoint.StepDef("write_mapping_evidence", "写入参数映射证据"),
    checkpoint.StepDef("stop_before_export", "停在真实导出前"),
]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_auth_context(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("system") != "maijing":
        raise RuntimeError("认证上下文不是 maijing。")
    token = data.get("cookie", {}).get("value") or ""
    if not token:
        raise RuntimeError("认证上下文缺少 token cookie。")
    return data


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


def parse_query(url: str) -> dict[str, list[str]]:
    parsed = urllib.parse.urlparse(url)
    return {
        key: values
        for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()
    }


def is_public_list_url(url: str) -> bool:
    return LIST_PATH in url


def summarize_response_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"body_type": type(body).__name__, "customer_rows_saved": False}
    rows = body.get("rows")
    if rows is None and isinstance(body.get("data"), dict):
        rows = body["data"].get("rows") or body["data"].get("list")
    total = body.get("total")
    if total is None and isinstance(body.get("data"), dict):
        total = body["data"].get("total")
    return {
        "code": body.get("code"),
        "msg": body.get("msg"),
        "total": total,
        "row_count_in_response": len(rows) if isinstance(rows, list) else None,
        "first_row_keys_only": sorted(rows[0].keys()) if isinstance(rows, list) and rows and isinstance(rows[0], dict) else [],
        "customer_rows_saved": False,
    }


def value_tokens(plan: dict[str, Any]) -> dict[str, list[str]]:
    dynamic = plan.get("dynamic_filters") or {}
    fixed = plan.get("fixed_filters") or {}
    tokens: dict[str, list[str]] = {}
    for field, value in {**dynamic, **fixed}.items():
        values = value if isinstance(value, list) else [value]
        tokens[field] = [str(item) for item in values if item]
    return tokens


def infer_mapping_candidates(plan: dict[str, Any], captured_requests: list[dict[str, Any]]) -> dict[str, Any]:
    tokens = value_tokens(plan)
    candidates: dict[str, list[dict[str, Any]]] = {field: [] for field in tokens}
    for request_index, request in enumerate(captured_requests):
        params = request.get("query_params") or {}
        for param_name, values in params.items():
            flat_values = [str(item) for item in values]
            joined_values = " ".join(flat_values)
            lower_param = param_name.lower()
            for field, expected_values in tokens.items():
                matched_values = [item for item in expected_values if item and item in joined_values]
                keyword_match = any(word in lower_param for word in field.lower().replace("_", " ").split())
                if matched_values or keyword_match:
                    candidates[field].append({
                        "request_index": request_index,
                        "api_param": param_name,
                        "observed_values": flat_values,
                        "matched_expected_values": matched_values,
                    })
    return {
        "status": "needs_human_review",
        "mapping_candidates": candidates,
        "note": "候选映射必须人工确认后才能写入 verified 参数映射。",
    }


def write_operator_instructions(run_dir: Path, plan: dict[str, Any], wait_seconds: int) -> None:
    dynamic = plan.get("dynamic_filters") or {}
    fixed = plan.get("fixed_filters") or {}
    lines = [
        "# 迈鲸筛选参数捕获操作说明",
        "",
        f"请在浏览器打开后的 {wait_seconds} 秒内完成：",
        "",
        "1. 进入公海客户页面。",
        "2. 按下面条件手动设置筛选项。",
        "3. 点击页面上的查询/搜索按钮。",
        "4. 不要点击导出。",
        "",
        "## 动态条件",
        "",
        f"- 城市：{dynamic.get('city') or '待确认'}",
        f"- 区县：{', '.join(dynamic.get('districts') or []) or '待确认'}",
        f"- 品类：{', '.join(dynamic.get('categories') or []) or '待确认'}",
        "",
        "## 固定条件",
        "",
        f"- {json.dumps(fixed, ensure_ascii=False)}",
    ]
    (run_dir / "outputs" / "manual_capture_instructions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="迈鲸公海客户筛选参数人工捕获。")
    parser.add_argument("--auth-context", required=True)
    parser.add_argument("--requirement")
    parser.add_argument("--requirement-file")
    parser.add_argument("--filter-plan")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--batch", default="001")
    parser.add_argument("--wait-seconds", type=int, default=120)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    plan, parsed, requirement = load_filter_plan(args)
    city = (plan.get("dynamic_filters") or {}).get("city") or "参数捕获"
    run_dir = checkpoint.ensure_run_dir(
        base_dir=ROOT,
        workflow_id="maijing-public-sea-filter-param-capture",
        workflow_name_cn="迈鲸公海客户筛选参数捕获",
        city=city,
        batch=args.batch,
        dry_run=True,
        steps=STEPS,
    )

    checkpoint.update_step(run_dir, "load_auth_context", "running", "读取迈鲸认证上下文")
    auth = load_auth_context(Path(args.auth_context).resolve())
    write_json(run_dir / "input" / "capture_input.json", {
        "auth_context_path": str(Path(args.auth_context).resolve()),
        "url": args.url,
        "wait_seconds": args.wait_seconds,
        "headless": args.headless,
    })
    checkpoint.update_step(run_dir, "load_auth_context", "completed", "读取迈鲸认证上下文")

    checkpoint.update_step(run_dir, "prepare_filter_plan", "running", "准备筛选计划")
    if requirement:
        (run_dir / "input" / "requirement.txt").write_text(requirement.strip() + "\n", encoding="utf-8")
    if parsed:
        write_json(run_dir / "input" / "parsed_requirement.json", parsed)
    write_json(run_dir / "input" / "filter_plan.json", plan)
    write_operator_instructions(run_dir, plan, args.wait_seconds)
    checkpoint.update_step(run_dir, "prepare_filter_plan", "completed", "准备筛选计划")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise SystemExit(f"缺少 playwright：{exc}")

    captured_requests: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, slow_mo=100)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_cookies([auth["cookie"]])
        page = context.new_page()

        def on_request(request):
            if request.method == "GET" and is_public_list_url(request.url):
                captured_requests.append({
                    "type": "request",
                    "method": request.method,
                    "url_path": urllib.parse.urlparse(request.url).path,
                    "query_params": parse_query(request.url),
                })

        def on_response(response):
            if response.request.method != "GET" or not is_public_list_url(response.url):
                return
            summary: dict[str, Any] = {"status": response.status}
            try:
                summary.update(summarize_response_body(response.json()))
            except Exception as exc:
                summary["response_summary_error"] = str(exc)
            captured_requests.append({
                "type": "response_summary",
                "url_path": urllib.parse.urlparse(response.url).path,
                "query_params": parse_query(response.url),
                "summary": summary,
            })

        page.on("request", on_request)
        page.on("response", on_response)

        checkpoint.update_step(run_dir, "open_public_sea_page", "running", "打开公海客户页面")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        if "login" in page.url.lower():
            checkpoint.update_step(
                run_dir,
                "open_public_sea_page",
                "failed",
                "打开公海客户页面",
                {
                    "step_name_cn": "打开公海客户页面",
                    "failure_reason": "认证上下文未生效，页面跳转到登录页。",
                    "evidence_paths": ["logs/run.log"],
                    "resume_step": "load_auth_context",
                },
            )
            raise RuntimeError("认证上下文未生效，页面跳转到登录页。")
        checkpoint.update_step(run_dir, "open_public_sea_page", "completed", "打开公海客户页面")

        checkpoint.update_step(run_dir, "capture_filter_requests", "running", "捕获筛选请求参数")
        checkpoint.append_log(run_dir, f"等待人工设置筛选条件并点击查询，等待 {args.wait_seconds} 秒。")
        page.wait_for_timeout(args.wait_seconds * 1000)
        checkpoint.update_step(run_dir, "capture_filter_requests", "completed", "捕获筛选请求参数")
        browser.close()

    checkpoint.update_step(run_dir, "write_mapping_evidence", "running", "写入参数映射证据")
    write_json(run_dir / "evidence" / "captured_public_list_requests.json", captured_requests)
    write_json(
        run_dir / "outputs" / "suggested_param_mapping_candidates.json",
        infer_mapping_candidates(plan, captured_requests),
    )
    checkpoint.update_step(run_dir, "write_mapping_evidence", "completed", "写入参数映射证据")
    checkpoint.update_step(run_dir, "stop_before_export", "pending", "停在真实导出前")
    checkpoint.append_log(run_dir, "迈鲸筛选参数捕获完成，未导出。")

    print(f"迈鲸筛选参数捕获完成，运行目录：{run_dir}")
    print(f"操作说明：{run_dir / 'outputs' / 'manual_capture_instructions.md'}")
    print(f"捕获请求：{run_dir / 'evidence' / 'captured_public_list_requests.json'}")
    print(f"候选映射：{run_dir / 'outputs' / 'suggested_param_mapping_candidates.json'}")


if __name__ == "__main__":
    main()
