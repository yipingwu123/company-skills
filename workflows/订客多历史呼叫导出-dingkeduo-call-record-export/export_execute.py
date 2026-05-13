#!/usr/bin/env python3
"""订客多历史呼叫全量导出执行脚本。

默认（不加 --execute-export）：查询第 1 页获取总数，生成确认清单，停止。
加 --execute-export --confirmation-json <路径> 后：拉取所有页，写完整 CSV，校验，写摘要。
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone, timedelta
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
    checkpoint.StepDef("login",               "登录订客多"),
    checkpoint.StepDef("probe_total",         "探测总记录数"),
    checkpoint.StepDef("write_confirmation",  "写入确认清单"),
    checkpoint.StepDef("validate_confirmation", "校验人工确认"),
    checkpoint.StepDef("fetch_all_pages",     "全量分页拉取"),
    checkpoint.StepDef("write_csv",           "写入完整 CSV"),
    checkpoint.StepDef("validate_output",     "校验导出文件"),
    checkpoint.StepDef("write_summary",       "写入摘要"),
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


# ---------------------------------------------------------------------------
# 复用自 export_dry_run.py（不修改原文件）
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 本脚本新增函数
# ---------------------------------------------------------------------------

def now_cn() -> str:
    """返回北京时间 ISO 字符串（秒精度）。"""
    cn_tz = timezone(timedelta(hours=8))
    return datetime.now(cn_tz).strftime("%Y-%m-%d %H:%M:%S")


def probe_first_page(page, target_date: str, perpage: int) -> dict[str, Any]:
    """拉取第 1 页，返回 record_list 字典（含 total / last_page 等）。"""
    path = build_list_path(target_date, 1, perpage)
    result = page.evaluate(
        """async (path) => {
          const res = await fetch(path, { credentials: 'include' });
          const text = await res.text();
          let json = null;
          try { json = JSON.parse(text); } catch(e) {}
          return { status: res.status, json, text_length: text.length };
        }""",
        path,
    )
    record_list = extract_record_list(result.get("json"))
    return record_list


def fetch_all_pages(page, target_date: str, perpage: int) -> tuple[list, dict]:
    """全量分页拉取，不限页数，循环直到 page_num >= last_page 或无数据。"""
    records = []
    pages_info = []
    page_num = 1
    last_page = None

    while True:
        path = build_list_path(target_date, page_num, perpage)
        result = page.evaluate(
            """async (path) => {
              const res = await fetch(path, { credentials: 'include' });
              const text = await res.text();
              let json = null;
              try { json = JSON.parse(text); } catch(e) {}
              return { status: res.status, json, text_length: text.length };
            }""",
            path,
        )
        record_list = extract_record_list(result.get("json"))
        page_records = record_list.get("data", [])
        records.extend(page_records)
        if last_page is None:
            last_page = record_list.get("last_page", 1)
        pages_info.append({"page": page_num, "row_count": len(page_records), "last_page": last_page})
        print(f"  第 {page_num}/{last_page} 页，本页 {len(page_records)} 条，累计 {len(records)} 条")
        if not page_records or page_num >= int(last_page):
            break
        page_num += 1

    return records, {"total_fetched": len(records), "total_pages": page_num, "pages": pages_info}


def write_confirmation_checklist(run_dir: Path, target_date: str, total: int, last_page: int, perpage: int) -> None:
    """生成 outputs/confirmation_checklist.md。"""
    est_seconds = last_page * 2
    lines = [
        "# 订客多历史呼叫全量导出 确认清单",
        "",
        f"- 目标日期：{target_date}",
        f"- 接口返回总数：{total}",
        f"- 预计总页数：{last_page}（每页 {perpage} 条）",
        f"- 预计拉取时长：约 {est_seconds} 秒",
        "",
        "## 下一步",
        "",
        "1. 确认以上信息无误后，在 `input/human_confirmation.json` 中将 `approved` 改为 `true`，",
        "   填写 `confirmed_by` 和 `confirmed_at`。",
        "2. 使用以下命令执行全量导出：",
        "",
        "   ```bash",
        "   python3 export_execute.py \\",
        f"     --target-date {target_date} \\",
        "     --execute-export \\",
        "     --confirmation-json <run_dir>/input/human_confirmation.json",
        "   ```",
    ]
    path = run_dir / "outputs" / "confirmation_checklist.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_confirmation_template(run_dir: Path, target_date: str, expected_total: int) -> Path:
    """生成 input/human_confirmation.json 模板（approved: false，让用户填写）。"""
    template = {
        "approved": False,
        "target_date": target_date,
        "expected_total": expected_total,
        "confirmed_by": "操作人姓名",
        "confirmed_at": "YYYY-MM-DD HH:MM:SS",
    }
    path = run_dir / "input" / "human_confirmation.json"
    write_json(path, template)
    return path


def validate_confirmation_json(confirmation: dict[str, Any], target_date: str) -> list[str]:
    """校验人工确认 JSON，返回错误列表（空列表表示通过）。"""
    errors = []
    if confirmation.get("approved") is not True:
        errors.append("approved 必须为 true。")
    if not str(confirmation.get("confirmed_by") or "").strip():
        errors.append("confirmed_by 不能为空。")
    if not str(confirmation.get("confirmed_at") or "").strip():
        errors.append("confirmed_at 不能为空。")
    if confirmation.get("target_date") != target_date:
        errors.append(f"target_date 与命令行 --target-date 不一致：确认={confirmation.get('target_date')}，命令行={target_date}。")
    return errors


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="订客多历史呼叫全量导出执行脚本。")
    parser.add_argument("--target-date", required=True, help="要导出的日期 YYYY-MM-DD。")
    parser.add_argument("--batch", default="001", help="批次号（默认 001）。")
    parser.add_argument("--username", help="订客多账号（或环境变量 DINGKEDUO_USERNAME）。")
    parser.add_argument("--password", help="订客多密码（或环境变量 DINGKEDUO_PASSWORD）。")
    parser.add_argument("--headless", action="store_true", help="无头模式（默认 False）。")
    parser.add_argument("--perpage", type=int, default=100, help="每页条数（默认 100）。")
    parser.add_argument(
        "--execute-export",
        action="store_true",
        help="真实全量拉取（须同时提供 --confirmation-json）。",
    )
    parser.add_argument("--confirmation-json", help="人工确认 JSON 路径（--execute-export 时必填）。")
    parser.add_argument("--base-dir", help="skills 根目录（默认自动推导）。")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve() if args.base_dir else ROOT

    # 在获取账号密码之前先检查 --execute-export 约束，避免无谓的网络连接
    if args.execute_export and not args.confirmation_json:
        raise SystemExit("--execute-export 必须同时提供 --confirmation-json。")

    username = env_or_arg(args.username, "DINGKEDUO_USERNAME")
    password = env_or_arg(args.password, "DINGKEDUO_PASSWORD")

    run_dir = checkpoint.ensure_run_dir(
        base_dir=base_dir,
        workflow_id="dingkeduo-call-record-export-execute",
        workflow_name_cn="订客多历史呼叫导出",
        city=args.target_date,
        batch=args.batch,
        dry_run=not args.execute_export,
        steps=STEPS,
    )

    # 保存入参（不含账号密码）
    write_json(run_dir / "input" / "export_execute_input.json", {
        "target_date": args.target_date,
        "perpage": args.perpage,
        "headless": args.headless,
        "execute_export": args.execute_export,
        "batch": args.batch,
    })

    pw = browser = context = None
    try:
        # ------------------------------------------------------------------
        # Step: login
        # ------------------------------------------------------------------
        checkpoint.update_step(run_dir, "login", "running", "登录订客多")
        pw, browser, context, page = login_and_open_context(username, password, args.headless)
        checkpoint.update_step(run_dir, "login", "completed", "登录订客多")

        # ------------------------------------------------------------------
        # Step: probe_total — 拉取第 1 页获取总数
        # ------------------------------------------------------------------
        checkpoint.update_step(run_dir, "probe_total", "running", "探测总记录数")
        record_list = probe_first_page(page, args.target_date, args.perpage)
        total = record_list.get("total", 0)
        last_page = record_list.get("last_page", 1)
        probe_result = {
            "target_date": args.target_date,
            "perpage": args.perpage,
            "total": total,
            "last_page": last_page,
            "current_page": record_list.get("current_page"),
            "per_page": record_list.get("per_page"),
            "first_page_row_count": len(record_list.get("data", [])),
        }
        write_json(run_dir / "evidence" / "api_responses" / "probe_result.json", probe_result)
        checkpoint.update_step(run_dir, "probe_total", "completed", "探测总记录数")

        # ------------------------------------------------------------------
        # Step: write_confirmation — 写入确认清单和模板
        # ------------------------------------------------------------------
        checkpoint.update_step(run_dir, "write_confirmation", "running", "写入确认清单")
        write_confirmation_checklist(run_dir, args.target_date, total, int(last_page), args.perpage)
        confirmation_template_path = write_confirmation_template(run_dir, args.target_date, total)
        checkpoint.update_step(run_dir, "write_confirmation", "completed", "写入确认清单")

        # ------------------------------------------------------------------
        # dry-run 分支：标记后续步骤为 skipped/pending，退出
        # ------------------------------------------------------------------
        if not args.execute_export:
            checkpoint.update_step(run_dir, "validate_confirmation", "skipped", "校验人工确认")
            checkpoint.update_step(run_dir, "fetch_all_pages", "skipped", "全量分页拉取")
            checkpoint.update_step(run_dir, "write_csv", "skipped", "写入完整 CSV")
            checkpoint.update_step(run_dir, "validate_output", "skipped", "校验导出文件")
            checkpoint.update_step(run_dir, "write_summary", "skipped", "写入摘要")
            checkpoint.append_log(
                run_dir,
                f"dry-run 完成：total={total}，last_page={last_page}。等待人工确认后执行 --execute-export。",
            )
            print(f"\n探测完成，运行目录：{run_dir}")
            print(f"  接口返回总数：{total}")
            print(f"  预计总页数：{last_page}（每页 {args.perpage} 条）")
            print(f"  确认清单：{run_dir / 'outputs' / 'confirmation_checklist.md'}")
            print(f"  确认模板：{confirmation_template_path}")
            print("\n请确认后用 --execute-export --confirmation-json <路径> 运行。")
            return

        # ------------------------------------------------------------------
        # Step: validate_confirmation — 校验人工确认 JSON
        # ------------------------------------------------------------------
        checkpoint.update_step(run_dir, "validate_confirmation", "running", "校验人工确认")
        confirmation_path = Path(args.confirmation_json).resolve()
        if not confirmation_path.exists():
            checkpoint.update_step(
                run_dir, "validate_confirmation", "failed", "校验人工确认",
                error={"failure_reason": f"confirmation-json 文件不存在：{confirmation_path}"},
            )
            raise SystemExit(f"confirmation-json 文件不存在：{confirmation_path}")
        confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
        # 保存到 input 目录留档（不含账号密码，确认 JSON 本身不含敏感信息）
        write_json(run_dir / "input" / "human_confirmation.json", confirmation)
        errors = validate_confirmation_json(confirmation, args.target_date)
        if errors:
            checkpoint.update_step(
                run_dir, "validate_confirmation", "failed", "校验人工确认",
                error={"failure_reason": "人工确认不满足执行条件", "details": errors},
            )
            raise SystemExit(f"人工确认不满足执行条件：{errors}")
        checkpoint.update_step(run_dir, "validate_confirmation", "completed", "校验人工确认")

        # ------------------------------------------------------------------
        # Step: fetch_all_pages — 全量分页拉取
        # ------------------------------------------------------------------
        checkpoint.update_step(run_dir, "fetch_all_pages", "running", "全量分页拉取")
        print(f"\n开始全量分页拉取（目标日期：{args.target_date}，预计 {last_page} 页）…")
        records, fetch_summary = fetch_all_pages(page, args.target_date, args.perpage)
        write_json(run_dir / "evidence" / "api_responses" / "fetch_summary.json", fetch_summary)
        checkpoint.update_step(run_dir, "fetch_all_pages", "completed", "全量分页拉取")

        # ------------------------------------------------------------------
        # Step: write_csv — 写入完整 CSV
        # ------------------------------------------------------------------
        checkpoint.update_step(run_dir, "write_csv", "running", "写入完整 CSV")
        csv_path = run_dir / "outputs" / f"dingkeduo_call_records_{args.target_date}.csv"
        write_csv(csv_path, records, OUTPUT_FIELDS)
        checkpoint.update_step(run_dir, "write_csv", "completed", "写入完整 CSV")

        # ------------------------------------------------------------------
        # Step: validate_output — 校验导出文件
        # ------------------------------------------------------------------
        checkpoint.update_step(run_dir, "validate_output", "running", "校验导出文件")
        report = validate_output(run_dir, csv_path, args.target_date)
        if not report.get("ok"):
            checkpoint.update_step(
                run_dir, "validate_output", "failed", "校验导出文件",
                error={
                    "failure_reason": "导出文件日期校验失败。",
                    "evidence_paths": ["evidence/validation_report.json"],
                    "resume_step": "fetch_all_pages",
                },
            )
            raise SystemExit("日期校验失败，请检查 evidence/validation_report.json。")
        checkpoint.update_step(run_dir, "validate_output", "completed", "校验导出文件")

        # ------------------------------------------------------------------
        # Step: write_summary — 写入摘要
        # ------------------------------------------------------------------
        checkpoint.update_step(run_dir, "write_summary", "running", "写入摘要")
        summary = {
            "target_date": args.target_date,
            "total_records": fetch_summary["total_fetched"],
            "total_pages": fetch_summary["total_pages"],
            "csv_path": str(csv_path),
            "validation_ok": report.get("ok"),
            "exported_at": now_cn(),
        }
        write_json(run_dir / "outputs" / "export_summary.json", summary)
        checkpoint.update_step(run_dir, "write_summary", "completed", "写入摘要")

        checkpoint.append_log(
            run_dir,
            f"全量导出完成：total_records={fetch_summary['total_fetched']}，total_pages={fetch_summary['total_pages']}。",
        )
        print(f"\n全量导出完成，运行目录：{run_dir}")
        print(f"  CSV 文件：{csv_path}")
        print(f"  总记录数：{fetch_summary['total_fetched']}")
        print(f"  总页数：{fetch_summary['total_pages']}")
        print(f"  校验报告：{run_dir / 'evidence' / 'validation_report.json'}")
        print(f"  导出摘要：{run_dir / 'outputs' / 'export_summary.json'}")

    finally:
        if browser:
            browser.close()
        if pw:
            pw.stop()


if __name__ == "__main__":
    main()
