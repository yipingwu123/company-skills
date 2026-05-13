#!/usr/bin/env python3
"""订客多历史呼叫分页拉取 dry-run。

生成内部流通用正式 CSV 和日期校验报告。
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_URL = "http://dkduo3.rmlx.cc:85/front.html#/service/call-record"


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
    checkpoint.StepDef("login_readonly", "登录订客多"),
    checkpoint.StepDef("fetch_pages", "分页拉取历史呼叫"),
    checkpoint.StepDef("write_output_file", "生成内部导出文件"),
    checkpoint.StepDef("validate_date", "校验呼叫日期"),
    checkpoint.StepDef("human_confirm_result", "人工确认导出结果"),
]


OUTPUT_FIELDS = [
    "pbxid",
    "caller",
    "callee",
    "direct",
    "uniqueid",
    "calldate",
    "dnid",
    "billsec",
    "disposition",
    "from",
    "monitor",
    "disposition_name",
    "dial_status_name",
    "service_object_name",
    "detail_service_object_name",
    "service_object_id",
    "user_name",
    "departmentName",
    "format_billsec",
]


def env_or_arg(value: str | None, env_name: str) -> str:
    result = value or os.environ.get(env_name, "")
    if not result:
        raise SystemExit(f"缺少参数或环境变量：{env_name}")
    return result


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_list_path(target_date: str, page: int, perpage: int) -> str:
    params = {
        "duration_start": "",
        "duration_end": "",
        "caller": "",
        "callee": "",
        "calldate_start": f"{target_date} 00:00:00",
        "calldate_end": f"{target_date} 23:59:59",
        "direct": "0",
        "page": str(page),
        "perpage": str(perpage),
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
    return f"/pbx/cdr-record-list?{urlencode(params)}"


def extract_record_list(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("列表接口返回不是 JSON 对象。")
    record_list = payload.get("data", {}).get("record_list", {})
    if not isinstance(record_list, dict):
        raise RuntimeError("列表接口缺少 data.record_list。")
    records = record_list.get("data", [])
    if not isinstance(records, list):
        raise RuntimeError("data.record_list.data 不是列表。")
    return record_list


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            out = {}
            for field in fields:
                out[field] = row.get(field, "")
            writer.writerow(out)


def validate_output(run_dir: Path, csv_path: Path, target_date: str) -> dict[str, Any]:
    config = {
        "required_columns": ["calldate"],
        "date_column": "calldate",
        "allowed_dates": [target_date],
        "default_year": int(target_date[:4]),
        "min_rows": 1,
        "non_empty_columns": ["calldate"],
        "unique_columns": [],
    }
    report = excel_validator.validate(excel_validator.read_table(csv_path), config)
    report["source_file"] = str(csv_path)
    report["config"] = config
    write_json(run_dir / "evidence" / "validation_report.json", report)
    return report


def write_confirmation_checklist(run_dir: Path, output_path: Path, fetch_summary: dict[str, Any], report: dict[str, Any]) -> None:
    fetched_rows = fetch_summary.get("fetched_rows")
    expected_total = fetch_summary.get("expected_total")
    expected_last_page = fetch_summary.get("expected_last_page")
    pages = fetch_summary.get("pages", [])
    lines = [
        "# 订客多历史呼叫导出 dry-run 确认清单",
        "",
        "## 拉取结果",
        "",
        f"- 目标日期：{fetch_summary.get('target_date')}",
        f"- 已拉取行数：{fetched_rows}",
        f"- 接口返回总数：{expected_total}",
        f"- 接口返回总页数：{expected_last_page}",
        f"- 本次拉取页数：{len(pages)}",
        f"- 内部导出文件：{output_path}",
        "",
        "## 日期校验",
        "",
        f"- 校验结果：{'通过' if report.get('ok') else '失败'}",
        f"- 校验文件行数：{report.get('row_count')}",
        f"- 是否需要人工复核：{'是' if report.get('needs_human_review') else '否'}",
        "",
        "## 下一步",
        "",
        "- 当前停在：人工确认导出结果",
        "- 如需全量拉取，请确认是否允许按接口总页数继续分页拉取。",
    ]
    (run_dir / "outputs" / "confirmation_checklist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def login_and_open_context(username: str, password: str, headless: bool):
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=headless, slow_mo=100)
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        accept_downloads=False,
    )
    page = context.new_page()
    page.goto(DEFAULT_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector('input[placeholder*="账号"], input[type="text"]', timeout=45000)
    except Exception:
        page.wait_for_timeout(5000)
    inputs = page.locator("input")
    if inputs.count() >= 2:
        inputs.nth(0).fill(username)
        inputs.nth(1).fill(password)
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
    page.goto(DEFAULT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    if "#/login" in page.url or page.locator('input[placeholder*="账号"], input[type="password"]').count() >= 2:
        raise RuntimeError("登录失败：页面仍停留在登录页。")
    return pw, browser, context, page


def fetch_pages(page, target_date: str, perpage: int, max_pages: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    pages = []
    expected_last_page = None
    expected_total = None
    page_limit = max(1, max_pages)

    for page_num in range(1, page_limit + 1):
        path = build_list_path(target_date, page_num, perpage)
        result = page.evaluate(
            """async (path) => {
              const res = await fetch(path, { credentials: 'include' });
              const text = await res.text();
              let json = null;
              try { json = JSON.parse(text); } catch (e) {}
              return { status: res.status, url: res.url, json, text_length: text.length };
            }""",
            path,
        )
        record_list = extract_record_list(result.get("json"))
        page_records = record_list.get("data", [])
        records.extend(page_records)
        expected_last_page = record_list.get("last_page", expected_last_page)
        expected_total = record_list.get("total", expected_total)
        pages.append({
            "page": page_num,
            "status": result.get("status"),
            "url": result.get("url"),
            "row_count": len(page_records),
            "current_page": record_list.get("current_page"),
            "last_page": record_list.get("last_page"),
            "total": record_list.get("total"),
            "per_page": record_list.get("per_page"),
        })
        if not page_records:
            break
        if expected_last_page and page_num >= int(expected_last_page):
            break

    return records, {
        "target_date": target_date,
        "perpage": perpage,
        "max_pages": max_pages,
        "fetched_rows": len(records),
        "expected_total": expected_total,
        "expected_last_page": expected_last_page,
        "pages": pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="订客多历史呼叫分页拉取 dry-run。")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--batch", default="001")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--perpage", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=1)
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
    write_json(run_dir / "input" / "export_dry_run_input.json", {
        "target_date": args.target_date,
        "perpage": args.perpage,
        "max_pages": args.max_pages,
        "headless": args.headless,
    })

    pw = browser = context = None
    try:
        checkpoint.update_step(run_dir, "login_readonly", "running", "登录订客多")
        pw, browser, context, page = login_and_open_context(username, password, args.headless)
        checkpoint.update_step(run_dir, "login_readonly", "completed", "登录订客多")

        checkpoint.update_step(run_dir, "fetch_pages", "running", "分页拉取历史呼叫")
        records, fetch_summary = fetch_pages(page, args.target_date, args.perpage, args.max_pages)
        write_json(run_dir / "evidence" / "api_responses" / "fetch_summary.json", fetch_summary)
        checkpoint.update_step(run_dir, "fetch_pages", "completed", "分页拉取历史呼叫")

        checkpoint.update_step(run_dir, "write_output_file", "running", "生成内部导出文件")
        output_path = run_dir / "outputs" / f"dingkeduo_call_records_{args.target_date}.csv"
        write_csv(output_path, records, OUTPUT_FIELDS)
        checkpoint.update_step(run_dir, "write_output_file", "completed", "生成内部导出文件")

        checkpoint.update_step(run_dir, "validate_date", "running", "校验呼叫日期")
        report = validate_output(run_dir, output_path, args.target_date)
        if not report.get("ok"):
            checkpoint.update_step(
                run_dir,
                "validate_date",
                "failed",
                "校验呼叫日期",
                {
                    "step_name_cn": "校验呼叫日期",
                    "failure_reason": "导出文件日期校验失败。",
                    "evidence_paths": ["evidence/validation_report.json"],
                    "resume_step": "fetch_pages",
                },
            )
            raise SystemExit("日期校验失败。")
        checkpoint.update_step(run_dir, "validate_date", "completed", "校验呼叫日期")
        write_confirmation_checklist(run_dir, output_path, fetch_summary, report)
        checkpoint.update_step(run_dir, "human_confirm_result", "pending", "人工确认导出结果")
        checkpoint.append_log(run_dir, "分页拉取 dry-run 完成，已停在人工确认导出结果。")

        print(f"分页拉取 dry-run 完成，运行目录：{run_dir}")
        print(f"内部导出文件：{output_path}")
        print(f"校验报告：{run_dir / 'evidence' / 'validation_report.json'}")
    finally:
        if browser:
            browser.close()
        if pw:
            pw.stop()


if __name__ == "__main__":
    main()
