#!/usr/bin/env python3
"""订客多历史呼叫导出只读侦查脚本。

目标：登录后观察历史呼叫页面、日期控件和网络请求，保存截图与页面状态。
默认不点击导出，不批量下载。
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import sys
from urllib.parse import urlencode
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
excel_validator = load_module(
    ROOT / "common" / "Excel处理-excel-transform" / "excel_validator.py",
    "excel_validator",
)


STEPS = [
    checkpoint.StepDef("open_login_page", "打开订客多登录页"),
    checkpoint.StepDef("login_readonly", "登录订客多"),
    checkpoint.StepDef("open_call_record_page", "打开历史呼叫页面"),
    checkpoint.StepDef("inspect_date_filter", "侦查日期筛选控件"),
    checkpoint.StepDef("probe_list_api", "只读探测列表接口"),
    checkpoint.StepDef("inspect_frontend_endpoints", "侦查前端接口线索"),
    checkpoint.StepDef("stop_before_export", "停在导出前"),
]


def env_or_arg(value: str | None, env_name: str) -> str:
    result = value or os.environ.get(env_name, "")
    if not result:
        raise SystemExit(f"缺少参数或环境变量：{env_name}")
    return result


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def redact_post_data(url: str, post_data: str | None) -> str | None:
    if not post_data:
        return post_data
    if any(key in url for key in ["/login", "need-enter-device-number"]):
        try:
            data = json.loads(post_data)
            for key in ["username", "password", "user", "code", "device"]:
                if key in data and data[key]:
                    data[key] = "***REDACTED***"
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return "***REDACTED***"
    return post_data


def safe_screenshot(page, path: Path, run_dir: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=True, timeout=8000)
    except Exception as exc:
        checkpoint.append_log(run_dir, f"截图失败但继续执行：{path.name}，原因：{exc}")


def summarize_api_json(data: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "type": type(data).__name__,
        "top_level_keys": list(data.keys()) if isinstance(data, dict) else [],
        "row_count": None,
        "row_keys": [],
        "date_samples": [],
        "list_candidates": [],
        "scalar_candidates": [],
    }

    candidates: list[tuple[str, list[Any]]] = []
    if isinstance(data, dict):
        stack = [("$", data)]
        while stack:
            path, item = stack.pop()
            if isinstance(item, dict):
                for key, value in item.items():
                    child_path = f"{path}.{key}"
                    if isinstance(value, list):
                        candidates.append((child_path, value))
                    elif isinstance(value, dict):
                        stack.append((child_path, value))
                    elif any(word in key.lower() for word in ["total", "count", "page", "per"]):
                        summary["scalar_candidates"].append({"path": child_path, "value": value})
    elif isinstance(data, list):
        candidates.append(("$", data))

    rows = []
    for path, candidate in candidates:
        keys = list(candidate[0].keys()) if candidate and isinstance(candidate[0], dict) else []
        summary["list_candidates"].append({
            "path": path,
            "count": len(candidate),
            "first_item_keys": keys,
        })
        if candidate and isinstance(candidate[0], dict) and keys and keys != ["name", "field"]:
            rows = candidate
            break
    summary["row_count"] = len(rows)
    if rows:
        summary["row_keys"] = list(rows[0].keys())
        date_keys = [key for key in rows[0].keys() if any(word in key.lower() for word in ["date", "time", "calldate"])]
        samples = []
        for row in rows[:10]:
            samples.append({key: row.get(key) for key in date_keys})
        summary["date_samples"] = samples
    return summary


def extract_records(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    record_list = data.get("data", {}).get("record_list", {})
    records = record_list.get("data", []) if isinstance(record_list, dict) else []
    return records if isinstance(records, list) else []


def write_sanitized_record_sample(run_dir: Path, records: list[dict[str, Any]]) -> Path | None:
    if not records:
        return None
    fields = ["calldate", "user_name", "departmentName", "disposition_name", "dial_status_name", "format_billsec"]
    out = run_dir / "outputs" / "call_records_date_sample.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in records:
            safe_row = {field: row.get(field, "") for field in fields}
            if re.fullmatch(r"\d{7,}", str(safe_row.get("user_name", ""))):
                safe_row["user_name"] = "***REDACTED***"
            writer.writerow(safe_row)
    return out


def validate_record_sample(run_dir: Path, sample_path: Path, target_date: str) -> None:
    report = excel_validator.validate(
        excel_validator.read_table(sample_path),
        {
            "required_columns": ["calldate"],
            "date_column": "calldate",
            "allowed_dates": [target_date],
            "default_year": int(target_date[:4]),
            "min_rows": 1,
            "non_empty_columns": ["calldate"],
            "unique_columns": [],
        },
    )
    report["source_file"] = str(sample_path)
    report["config"] = {
        "required_columns": ["calldate"],
        "date_column": "calldate",
        "allowed_dates": [target_date],
        "default_year": int(target_date[:4]),
        "min_rows": 1,
        "non_empty_columns": ["calldate"],
        "unique_columns": [],
    }
    write_json(run_dir / "evidence" / "validation_report.json", report)


def endpoint_hints_from_text(text: str) -> list[dict[str, str]]:
    patterns = [
        r"/pbx/[A-Za-z0-9_./?=&%-]+",
        r"/service/[A-Za-z0-9_./?=&%-]+",
        r"/out-call/[A-Za-z0-9_./?=&%-]+",
        r"/common/[A-Za-z0-9_./?=&%-]+",
    ]
    hints = []
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = match.group(0).strip("\\'\"`)")
            lower = value.lower()
            if value in seen:
                continue
            if any(word in lower for word in ["cdr", "record", "export", "download", "call"]):
                seen.add(value)
                start = max(match.start() - 80, 0)
                end = min(match.end() + 80, len(text))
                hints.append({"endpoint": value, "context": text[start:end]})
    return hints[:200]


def main() -> None:
    parser = argparse.ArgumentParser(description="订客多只读侦查。")
    parser.add_argument("--target-date", required=True, help="目标日期 YYYY-MM-DD。")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--url", default="http://dkduo3.rmlx.cc:85/front.html#/service/call-record")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--perpage", type=int, default=10, help="接口每页数量，默认 10。")
    parser.add_argument("--max-pages", type=int, default=1, help="最多探测页数，默认 1。")
    args = parser.parse_args()

    username = env_or_arg(args.username, "DINGKEDUO_USERNAME")
    password = env_or_arg(args.password, "DINGKEDUO_PASSWORD")

    run_dir = checkpoint.ensure_run_dir(
        base_dir=ROOT,
        workflow_id="dingkeduo-call-record-export",
        workflow_name_cn="订客多历史呼叫导出",
        city=args.target_date,
        batch=args.batch,
        dry_run=True,
        steps=STEPS,
    )
    checkpoint.guard_action(run_dir, "parse_requirement")
    write_json(run_dir / "input" / "recon_input.json", {
        "target_date": args.target_date,
        "url": args.url,
        "username_source": "argument_or_env",
        "headless": args.headless,
    })

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise SystemExit(f"缺少 playwright：{exc}")

    network_events = []
    page_state: dict[str, Any] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, slow_mo=100)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            accept_downloads=False,
        )
        page = context.new_page()

        def on_request(request):
            if request.resource_type in {"xhr", "fetch", "document"}:
                network_events.append({
                    "type": "request",
                    "method": request.method,
                    "url": request.url,
                    "resource_type": request.resource_type,
                    "post_data": redact_post_data(request.url, request.post_data),
                })

        def on_response(response):
            req = response.request
            if req.resource_type in {"xhr", "fetch", "document"}:
                network_events.append({
                    "type": "response",
                    "status": response.status,
                    "url": response.url,
                    "resource_type": req.resource_type,
                })

        page.on("request", on_request)
        page.on("response", on_response)

        checkpoint.update_step(run_dir, "open_login_page", "running", "打开订客多登录页")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        safe_screenshot(page, run_dir / "evidence" / "screenshots" / "01-login-page.png", run_dir)
        checkpoint.update_step(run_dir, "open_login_page", "completed", "打开订客多登录页")

        checkpoint.update_step(run_dir, "login_readonly", "running", "登录订客多")
        try:
            page.wait_for_selector('input[placeholder*="账号"], input[type="text"]', timeout=45000)
        except Exception:
            checkpoint.append_log(run_dir, "等待登录输入框超时，继续检查是否已进入应用页。")
            page.wait_for_timeout(5000)
        inputs = page.locator("input")
        input_count = inputs.count()
        if input_count < 2:
            checkpoint.append_log(run_dir, f"未发现登录输入框，按已登录或应用页处理，input_count={input_count}。")
            safe_screenshot(page, run_dir / "evidence" / "screenshots" / "03-no-login-form.png", run_dir)
        else:
            inputs.nth(0).fill(username)
            inputs.nth(1).fill(password)
            safe_screenshot(page, run_dir / "evidence" / "screenshots" / "02-before-login-submit.png", run_dir)
            candidates = [
                page.get_by_role("button", name="登录"),
                page.get_by_text("登录", exact=True),
                page.locator("button").first,
            ]
            clicked = False
            for candidate in candidates:
                try:
                    if candidate.count() > 0:
                        candidate.first.click(timeout=5000)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                raise RuntimeError("未找到登录按钮。")
            try:
                page.wait_for_url(lambda url: "#/login" not in url, timeout=20000)
            except Exception:
                page.wait_for_timeout(5000)
            safe_screenshot(page, run_dir / "evidence" / "screenshots" / "03-after-login.png", run_dir)
        checkpoint.update_step(run_dir, "login_readonly", "completed", "登录订客多")

        checkpoint.update_step(run_dir, "open_call_record_page", "running", "打开历史呼叫页面")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        safe_screenshot(page, run_dir / "evidence" / "screenshots" / "04-call-record-page.png", run_dir)
        login_markers = page.locator('input[placeholder*="账号"], input[type="password"]').count()
        if "#/login" in page.url or login_markers >= 2:
            checkpoint.update_step(
                run_dir,
                "open_call_record_page",
                "failed",
                "打开历史呼叫页面",
                {
                    "step_name_cn": "打开历史呼叫页面",
                    "failure_reason": "页面仍停留在登录页，未进入历史呼叫页面。",
                    "evidence_paths": [
                        "evidence/screenshots/04-call-record-page.png",
                        "logs/run.log",
                    ],
                    "resume_step": "login_readonly",
                },
            )
            raise RuntimeError("页面仍停留在登录页，未进入历史呼叫页面。")
        checkpoint.update_step(run_dir, "open_call_record_page", "completed", "打开历史呼叫页面")

        checkpoint.update_step(run_dir, "inspect_date_filter", "running", "侦查日期筛选控件")
        page_state = page.evaluate(
            """() => {
              const pick = (el) => ({
                tag: el.tagName,
                text: (el.innerText || el.textContent || '').trim().slice(0, 120),
                placeholder: el.getAttribute('placeholder'),
                type: el.getAttribute('type'),
                value: el.value || el.getAttribute('value'),
                className: el.className,
                id: el.id,
                name: el.getAttribute('name'),
                ariaLabel: el.getAttribute('aria-label')
              });
              const nodes = Array.from(document.querySelectorAll('input,button,[role=button],.el-date-editor,.ant-picker,.ivu-date-picker'));
              const keywordNodes = Array.from(document.querySelectorAll('body *'))
                .filter(el => /呼叫时间|日期|导出|筛选|查询|搜索/.test((el.innerText || el.textContent || '').trim()))
                .slice(0, 80)
                .map(pick);
              return {
                url: location.href,
                title: document.title,
                inputs_buttons: nodes.slice(0, 160).map(pick),
                keyword_nodes: keywordNodes
              };
            }"""
        )
        write_json(run_dir / "evidence" / "page_state.json", page_state)
        safe_screenshot(page, run_dir / "evidence" / "screenshots" / "05-date-filter-inspection.png", run_dir)
        checkpoint.update_step(run_dir, "inspect_date_filter", "completed", "侦查日期筛选控件")

        checkpoint.update_step(run_dir, "probe_list_api", "running", "只读探测列表接口")
        probe_results = []
        all_records = []
        for page_num in range(1, max(args.max_pages, 1) + 1):
            params = {
                "duration_start": "",
                "duration_end": "",
                "caller": "",
                "callee": "",
                "calldate_start": f"{args.target_date} 00:00:00",
                "calldate_end": f"{args.target_date} 23:59:59",
                "direct": "0",
                "page": str(page_num),
                "perpage": str(args.perpage),
                "caller_or_callee": "",
                "call_name": "",
                "remark": "",
                "uniqueid": "",
                "disposition": "",
                "dial_status": "",
                "area_code": "",
                "call_project_id": "",
                "analysis_status": "",
            }
            api_path = f"/pbx/cdr-record-list?{urlencode(params)}"
            api_result = page.evaluate(
                """async (path) => {
                  const res = await fetch(path, { credentials: 'include' });
                  const text = await res.text();
                  let json = null;
                  try { json = JSON.parse(text); } catch (e) {}
                  return { status: res.status, url: res.url, json, text_length: text.length };
                }""",
                api_path,
            )
            records = extract_records(api_result.get("json"))
            all_records.extend(records)
            probe_results.append({
                "page": page_num,
                "request_path": api_path,
                "status": api_result.get("status"),
                "url": api_result.get("url"),
                "text_length": api_result.get("text_length"),
                "summary": summarize_api_json(api_result.get("json")),
            })
        write_json(run_dir / "evidence" / "api_responses" / "cdr_record_list_summary.json", {
            "request": {
                "target_date": args.target_date,
                "perpage": args.perpage,
                "max_pages": args.max_pages,
            },
            "pages": probe_results,
        })
        sample_path = write_sanitized_record_sample(run_dir, all_records)
        if sample_path:
            validate_record_sample(run_dir, sample_path, args.target_date)
            checkpoint.append_log(run_dir, f"已生成脱敏日期样本并完成日期校验：{sample_path}")
        checkpoint.update_step(run_dir, "probe_list_api", "completed", "只读探测列表接口")

        checkpoint.update_step(run_dir, "inspect_frontend_endpoints", "running", "侦查前端接口线索")
        scripts = page.evaluate(
            """async () => {
              const scriptUrls = Array.from(document.scripts).map(s => s.src).filter(Boolean);
              const resourceUrls = performance.getEntriesByType('resource')
                .map(e => e.name)
                .filter(name => /\\.js(\\?|$)/.test(name));
              const urls = Array.from(new Set([...scriptUrls, ...resourceUrls]))
                .filter(src => src && src.startsWith(location.origin));
              const result = [];
              for (const url of urls.slice(0, 80)) {
                try {
                  const res = await fetch(url, { credentials: 'include' });
                  const text = await res.text();
                  result.push({ url, status: res.status, text });
                } catch (e) {
                  result.push({ url, status: 'ERROR', error: String(e) });
                }
              }
              return result;
            }"""
        )
        endpoint_hints = []
        for script in scripts:
            if script.get("text"):
                for hint in endpoint_hints_from_text(script["text"]):
                    hint["script_url"] = script.get("url")
                    endpoint_hints.append(hint)
        write_json(run_dir / "evidence" / "frontend_endpoint_hints.json", {
            "script_count": len(scripts),
            "scripts": [{"url": item.get("url"), "status": item.get("status"), "error": item.get("error")} for item in scripts],
            "hints": endpoint_hints[:300],
        })
        checkpoint.update_step(run_dir, "inspect_frontend_endpoints", "completed", "侦查前端接口线索")

        write_json(run_dir / "evidence" / "network_requests.json", network_events)
        checkpoint.update_step(run_dir, "stop_before_export", "pending", "停在导出前")
        checkpoint.append_log(run_dir, "订客多只读侦查完成，未点击导出。")
        browser.close()

    print(f"订客多只读侦查完成，运行目录：{run_dir}")
    print(f"页面状态：{run_dir / 'evidence' / 'page_state.json'}")
    print(f"网络请求：{run_dir / 'evidence' / 'network_requests.json'}")


if __name__ == "__main__":
    main()
