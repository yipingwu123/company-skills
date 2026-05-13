#!/usr/bin/env python3
"""迈鲸公海客户页面/API 只读侦查。

使用 maijing-login 生成的 auth_context 打开公海客户页面，保存页面状态和网络请求线索。
不点击导出，不下载文件，不写入业务数据。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_URL = "https://mj-whale.com/customer/publicSeas"


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checkpoint = load_module(ROOT / "common" / "断点续跑-checkpoint-runner" / "checkpoint_runner.py", "checkpoint_runner")


STEPS = [
    checkpoint.StepDef("load_auth_context", "读取迈鲸认证上下文"),
    checkpoint.StepDef("open_public_sea_page", "打开公海客户页面"),
    checkpoint.StepDef("inspect_page_state", "侦查页面筛选控件"),
    checkpoint.StepDef("inspect_network", "侦查网络请求"),
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


def redact_headers_or_url(value: str | None) -> str | None:
    if not value:
        return value
    value = re.sub(r"(Authorization=Bearer%20)[^&]+", r"\1***REDACTED***", value)
    value = re.sub(r"(Admin-Token=)[^;&]+", r"\1***REDACTED***", value)
    return value


def safe_screenshot(page, path: Path, run_dir: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=True, timeout=8000)
    except Exception as exc:
        checkpoint.append_log(run_dir, f"截图失败但继续执行：{path.name}，原因：{exc}")


def endpoint_hints(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints = []
    for event in events:
        url = event.get("url", "")
        if any(word in url.lower() for word in ["public", "sea", "customer", "client", "export", "list"]):
            hints.append(event)
    return hints[:200]


def main() -> None:
    parser = argparse.ArgumentParser(description="迈鲸公海客户只读侦查。")
    parser.add_argument("--auth-context", required=True)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--batch", default="001")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    run_dir = checkpoint.ensure_run_dir(
        base_dir=ROOT,
        workflow_id="maijing-public-sea-filter-export",
        workflow_name_cn="迈鲸公海客户筛选导出",
        city="接口侦查",
        batch=args.batch,
        dry_run=True,
        steps=STEPS,
    )

    checkpoint.update_step(run_dir, "load_auth_context", "running", "读取迈鲸认证上下文")
    auth = load_auth_context(Path(args.auth_context).resolve())
    write_json(run_dir / "input" / "recon_input.json", {
        "auth_context_path": str(Path(args.auth_context).resolve()),
        "url": args.url,
        "headless": args.headless,
    })
    checkpoint.update_step(run_dir, "load_auth_context", "completed", "读取迈鲸认证上下文")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise SystemExit(f"缺少 playwright：{exc}")

    network_events: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, slow_mo=100)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_cookies([auth["cookie"]])
        page = context.new_page()

        def on_request(request):
            if request.resource_type in {"xhr", "fetch", "document"}:
                network_events.append({
                    "type": "request",
                    "method": request.method,
                    "url": redact_headers_or_url(request.url),
                    "resource_type": request.resource_type,
                    "post_data": "***REDACTED***" if request.post_data else None,
                })

        def on_response(response):
            req = response.request
            if req.resource_type in {"xhr", "fetch", "document"}:
                network_events.append({
                    "type": "response",
                    "status": response.status,
                    "url": redact_headers_or_url(response.url),
                    "resource_type": req.resource_type,
                })

        page.on("request", on_request)
        page.on("response", on_response)

        checkpoint.update_step(run_dir, "open_public_sea_page", "running", "打开公海客户页面")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)
        safe_screenshot(page, run_dir / "evidence" / "screenshots" / "01-public-sea-page.png", run_dir)
        if "login" in page.url.lower():
            checkpoint.update_step(
                run_dir,
                "open_public_sea_page",
                "failed",
                "打开公海客户页面",
                {
                    "step_name_cn": "打开公海客户页面",
                    "failure_reason": "认证上下文未生效，页面跳转到登录页。",
                    "evidence_paths": ["evidence/screenshots/01-public-sea-page.png", "logs/run.log"],
                    "resume_step": "load_auth_context",
                },
            )
            raise RuntimeError("认证上下文未生效，页面跳转到登录页。")
        checkpoint.update_step(run_dir, "open_public_sea_page", "completed", "打开公海客户页面")

        checkpoint.update_step(run_dir, "inspect_page_state", "running", "侦查页面筛选控件")
        page_state = page.evaluate(
            """() => {
              const pick = (el) => ({
                tag: el.tagName,
                text: (el.innerText || el.textContent || '').trim().slice(0, 160),
                placeholder: el.getAttribute('placeholder'),
                type: el.getAttribute('type'),
                value: el.value || el.getAttribute('value'),
                className: el.className,
                id: el.id,
                name: el.getAttribute('name'),
                ariaLabel: el.getAttribute('aria-label')
              });
              const nodes = Array.from(document.querySelectorAll('input,button,[role=button],.el-select,.el-cascader,.el-date-editor'));
              const keywordNodes = Array.from(document.querySelectorAll('body *'))
                .filter(el => /客户|公海|城市|区县|品类|号码|导出|筛选|查询|搜索|认领|进店|门店|跟进/.test((el.innerText || el.textContent || '').trim()))
                .slice(0, 120)
                .map(pick);
              return {
                url: location.href,
                title: document.title,
                inputs_buttons: nodes.slice(0, 220).map(pick),
                keyword_nodes: keywordNodes
              };
            }"""
        )
        write_json(run_dir / "evidence" / "page_state.json", page_state)
        checkpoint.update_step(run_dir, "inspect_page_state", "completed", "侦查页面筛选控件")

        checkpoint.update_step(run_dir, "inspect_network", "running", "侦查网络请求")
        write_json(run_dir / "evidence" / "network_requests.json", network_events)
        write_json(run_dir / "evidence" / "api_endpoint_hints.json", {
            "hints": endpoint_hints(network_events),
        })
        checkpoint.update_step(run_dir, "inspect_network", "completed", "侦查网络请求")
        checkpoint.update_step(run_dir, "stop_before_export", "pending", "停在真实导出前")
        checkpoint.append_log(run_dir, "迈鲸公海客户只读侦查完成，未导出。")
        browser.close()

    print(f"迈鲸公海客户只读侦查完成，运行目录：{run_dir}")
    print(f"页面状态：{run_dir / 'evidence' / 'page_state.json'}")
    print(f"接口线索：{run_dir / 'evidence' / 'api_endpoint_hints.json'}")


if __name__ == "__main__":
    main()
