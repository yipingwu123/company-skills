#!/usr/bin/env python3
"""火山引擎控制台 browser 登录。

使用 Playwright 完成 IAM 子用户登录，提取 csrfToken，
生成 volcengine_auth_context.json 供后续 skill 复用。

账号通过环境变量或 secrets 文件读取，不硬编码。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://console.volcengine.com"
API_BASE = "/console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01"


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
    checkpoint.StepDef("load_account", "读取账号引用"),
    checkpoint.StepDef("browser_login", "浏览器登录火山引擎"),
    checkpoint.StepDef("extract_csrf", "提取 csrfToken"),
    checkpoint.StepDef("write_auth_context", "写入认证上下文"),
]


def read_account(account_ref: str) -> dict[str, str]:
    env_main = os.environ.get("VOLCENGINE_MAIN_ACCOUNT")
    env_user = os.environ.get("VOLCENGINE_USERNAME")
    env_pass = os.environ.get("VOLCENGINE_PASSWORD")
    if env_main or env_user or env_pass:
        if not (env_main and env_user and env_pass):
            raise SystemExit("VOLCENGINE_MAIN_ACCOUNT、VOLCENGINE_USERNAME、VOLCENGINE_PASSWORD 必须同时提供。")
        return {"main_account": env_main, "username": env_user, "password": env_pass}
    data = secrets_loader.get_account("volcengine", account_ref)
    # secrets 格式: {"main_account": "...", "username": "...", "password": "..."}
    return data


def login_and_extract_csrf(account: dict[str, str], headless: bool, run_dir: Path) -> dict[str, str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("缺少 playwright。请运行: pip install playwright && playwright install chromium")

    evidence_dir = run_dir / "evidence" / "screenshots"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()

        page.goto(f"{BASE_URL}/auth/login", timeout=30000)
        page.screenshot(path=str(evidence_dir / "01_login_page.png"))

        # 选择 IAM 子用户登录标签
        # 页面有多个 tab，找到 IAM 子用户 tab
        iam_tab = page.locator("text=IAM用户").first
        if iam_tab.count() == 0:
            iam_tab = page.locator("text=子用户").first
        iam_tab.click()
        page.screenshot(path=str(evidence_dir / "02_iam_tab.png"))

        # 填写主账号 ID
        main_input = page.locator("input[placeholder*='主账号']").first
        if main_input.count() == 0:
            main_input = page.locator("input").nth(0)
        main_input.fill(account["main_account"])

        # 填写子用户名
        user_input = page.locator("input[placeholder*='用户名']").first
        if user_input.count() == 0:
            user_input = page.locator("input").nth(1)
        user_input.fill(account["username"])

        # 填写密码
        pass_input = page.locator("input[type='password']").first
        pass_input.fill(account["password"])

        page.screenshot(path=str(evidence_dir / "03_filled_form.png"))

        # 点击登录
        login_btn = page.locator("button[type='submit']").first
        if login_btn.count() == 0:
            login_btn = page.locator("button:has-text('登录')").first
        login_btn.click()

        # 等待跳转到控制台
        page.wait_for_url(f"{BASE_URL}/home**", timeout=30000)
        page.screenshot(path=str(evidence_dir / "04_after_login.png"))

        # 提取 csrfToken cookie
        cookies = ctx.cookies()
        csrf_token = None
        for cookie in cookies:
            if cookie["name"] == "csrfToken":
                import urllib.parse
                csrf_token = urllib.parse.unquote(cookie["value"])
                break

        if not csrf_token:
            raise RuntimeError("登录后未找到 csrfToken cookie。")

        # 提取所有 cookies 供后续请求使用
        cookie_header = "; ".join(
            f"{c['name']}={c['value']}" for c in cookies if BASE_URL.split("//")[1] in c.get("domain", "")
        )

        browser.close()

        return {
            "csrf_token": csrf_token,
            "cookie_header": cookie_header,
        }


def write_auth_context(run_dir: Path, account_ref: str, auth: dict[str, str]) -> Path:
    auth_path = run_dir / "outputs" / "volcengine_auth_context.json"
    checkpoint.write_json(auth_path, {
        "system": "volcengine",
        "account_ref": account_ref,
        "base_url": BASE_URL,
        "api_base": API_BASE,
        "headers": {
            "X-Csrf-Token": auth["csrf_token"],
            "Content-Type": "application/json",
        },
        "cookie_header": auth["cookie_header"],
    })
    checkpoint.write_json(run_dir / "evidence" / "api_responses" / "login_summary.json", {
        "system": "volcengine",
        "account_ref": account_ref,
        "csrf_token_masked": secrets_loader.mask_secret(auth["csrf_token"]),
        "auth_context_path": str(auth_path),
    })
    return auth_path


def main() -> None:
    parser = argparse.ArgumentParser(description="火山引擎浏览器登录。")
    parser.add_argument("--account-ref", default="DXZG-1")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--base-dir", default=str(ROOT))
    args = parser.parse_args()

    run_dir = checkpoint.ensure_run_dir(
        base_dir=Path(args.base_dir).resolve(),
        workflow_id="volcengine-login",
        workflow_name_cn="火山登录",
        city=args.account_ref,
        batch=args.batch,
        dry_run=False,
        steps=STEPS,
    )

    try:
        checkpoint.update_step(run_dir, "load_account", "running", "读取账号引用")
        account = read_account(args.account_ref)
        checkpoint.update_step(run_dir, "load_account", "completed", "读取账号引用")

        checkpoint.update_step(run_dir, "browser_login", "running", "浏览器登录火山引擎")
        auth = login_and_extract_csrf(account, args.headless, run_dir)
        checkpoint.update_step(run_dir, "browser_login", "completed", "浏览器登录火山引擎")

        checkpoint.update_step(run_dir, "extract_csrf", "running", "提取 csrfToken")
        checkpoint.update_step(run_dir, "extract_csrf", "completed", "提取 csrfToken")

        checkpoint.update_step(run_dir, "write_auth_context", "running", "写入认证上下文")
        auth_path = write_auth_context(run_dir, args.account_ref, auth)
        checkpoint.update_step(run_dir, "write_auth_context", "completed", "写入认证上下文")

        checkpoint.append_log(run_dir, "火山引擎登录完成。")
        print(f"火山登录完成，运行目录：{run_dir}")
        print(f"认证上下文：{auth_path}")

    except Exception as exc:
        checkpoint.update_step(
            run_dir, "browser_login", "failed", "浏览器登录火山引擎",
            {"failure_reason": str(exc), "resume_step": "browser_login"},
        )
        raise


if __name__ == "__main__":
    main()
