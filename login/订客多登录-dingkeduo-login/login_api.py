#!/usr/bin/env python3
"""订客多 Playwright 登录。

只负责登录并生成认证上下文文件，不执行任何业务动作。
账号密码从 .secrets/automation_accounts.json 或环境变量读取。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "http://dkduo3.rmlx.cc:85"
LOGIN_URL = f"{BASE_URL}/front.html"


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


STEPS = [
    checkpoint.StepDef("load_account",       "读取账号引用"),
    checkpoint.StepDef("browser_login",      "浏览器登录订客多"),
    checkpoint.StepDef("extract_cookies",    "提取 session cookies"),
    checkpoint.StepDef("write_auth_context", "写入认证上下文"),
]


def now_cn() -> str:
    cn_tz = timezone(timedelta(hours=8))
    return datetime.now(cn_tz).strftime("%Y-%m-%d %H:%M:%S")


def read_account(account_ref: str) -> dict[str, str]:
    """优先读 secrets 文件，不存在则回退环境变量。"""
    secrets_path = ROOT / ".secrets" / "automation_accounts.json"
    if secrets_path.exists():
        try:
            return secrets_loader.get_account("dingkeduo", account_ref)
        except (KeyError, ValueError):
            pass

    env_user = os.environ.get("DINGKEDUO_USERNAME")
    env_pass = os.environ.get("DINGKEDUO_PASSWORD")
    if env_user and env_pass:
        return {"username": env_user, "password": env_pass}

    raise SystemExit(
        f"找不到账号：account_ref={account_ref}。"
        "请在 .secrets/automation_accounts.json 配置，"
        "或设置环境变量 DINGKEDUO_USERNAME / DINGKEDUO_PASSWORD。"
    )


def browser_login(username: str, password: str, headless: bool):
    """打开浏览器，完成登录，返回 (pw, browser, context, page)。"""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=headless, slow_mo=100)
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        accept_downloads=False,
    )
    page = context.new_page()
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

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
    else:
        raise RuntimeError("登录页面未找到输入框。")

    if "#/login" in page.url or page.locator('input[placeholder*="账号"], input[type="password"]').count() >= 2:
        raise RuntimeError("登录失败：页面仍停留在登录页。")

    return pw, browser, context, page


def write_auth_context(run_dir: Path, account_ref: str, cookies: list[dict[str, Any]]) -> Path:
    auth_path = run_dir / "outputs" / "dingkeduo_auth_context.json"
    checkpoint.write_json(auth_path, {
        "account_ref": account_ref,
        "base_url": BASE_URL,
        "cookies": cookies,
        "created_at": now_cn(),
    })
    return auth_path


def main() -> None:
    parser = argparse.ArgumentParser(description="订客多 Playwright 登录，生成认证上下文文件。")
    parser.add_argument("--account-ref", default="default", help="账号引用（如 DXZG-1），默认 default")
    parser.add_argument("--batch", default="001", help="批次号，默认 001")
    parser.add_argument("--headless", action="store_true", default=False, help="无头模式（调试时不加）")
    parser.add_argument("--base-dir", default=str(ROOT), help="runs 根目录，默认项目根目录")
    args = parser.parse_args()

    run_dir = checkpoint.ensure_run_dir(
        base_dir=Path(args.base_dir).resolve(),
        workflow_id="dingkeduo-login",
        workflow_name_cn="订客多登录",
        city=args.account_ref,
        batch=args.batch,
        dry_run=False,
        steps=STEPS,
    )

    pw = browser = context = None
    try:
        checkpoint.update_step(run_dir, "load_account", "running", "读取账号引用")
        account = read_account(args.account_ref)
        checkpoint.update_step(run_dir, "load_account", "completed", "读取账号引用")

        checkpoint.update_step(run_dir, "browser_login", "running", "浏览器登录订客多")
        pw, browser, context, page = browser_login(account["username"], account["password"], args.headless)
        checkpoint.update_step(run_dir, "browser_login", "completed", "浏览器登录订客多")

        checkpoint.update_step(run_dir, "extract_cookies", "running", "提取 session cookies")
        cookies = context.cookies()
        checkpoint.update_step(run_dir, "extract_cookies", "completed", "提取 session cookies")

        checkpoint.update_step(run_dir, "write_auth_context", "running", "写入认证上下文")
        auth_path = write_auth_context(run_dir, args.account_ref, cookies)
        checkpoint.update_step(run_dir, "write_auth_context", "completed", "写入认证上下文")

        checkpoint.append_log(run_dir, f"订客多登录完成，共保存 {len(cookies)} 个 cookies。")
        print(f"登录成功，共保存 {len(cookies)} 个 cookies。")
        print(f"认证上下文：{auth_path}")
        sys.exit(0)

    except Exception as exc:
        checkpoint.update_step(
            run_dir,
            "browser_login",
            "failed",
            "浏览器登录订客多",
            {
                "step_name_cn": "浏览器登录订客多",
                "failure_reason": str(exc),
                "evidence_paths": ["logs/run.log"],
                "resume_step": "browser_login",
            },
        )
        print(f"登录失败：{exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if browser:
            browser.close()
        if pw:
            pw.stop()


if __name__ == "__main__":
    main()
