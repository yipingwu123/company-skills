#!/usr/bin/env python3
"""迈鲸 API 登录。

只负责登录并生成认证上下文文件，不执行任何业务动作。
账号密码从 .secrets/automation_accounts.json 或环境变量读取。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://mj-whale.com/prod-api"


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
    checkpoint.StepDef("get_captcha", "获取验证码参数"),
    checkpoint.StepDef("api_login", "API 登录迈鲸"),
    checkpoint.StepDef("write_auth_context", "写入认证上下文"),
]


def read_account(account_ref: str, username: str | None, password: str | None) -> dict[str, str]:
    env_user = os.environ.get("MAIJING_USERNAME")
    env_pass = os.environ.get("MAIJING_PASSWORD")
    if username or password or env_user or env_pass:
        final_user = username or env_user
        final_pass = password or env_pass
        if not final_user or not final_pass:
            raise SystemExit("用户名和密码必须同时提供。")
        return {"username": final_user, "password": final_pass}
    return secrets_loader.get_account("maijing", account_ref)


def request_json(url: str, data: bytes | None = None, headers: dict[str, str] | None = None, method: str | None = None) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers or {"User-Agent": "Mozilla/5.0"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read())


def get_captcha() -> dict[str, Any]:
    return request_json(f"{BASE_URL}/captchaImage")


def login_with_captcha(username: str, password: str, captcha: dict[str, Any]) -> dict[str, Any]:
    uuid = captcha.get("uuid")
    if not uuid:
        raise RuntimeError("验证码接口未返回 uuid。")
    payload = json.dumps({
        "username": username,
        "password": password,
        "code": "1",
        "uuid": uuid,
    }).encode()
    data = request_json(
        f"{BASE_URL}/login",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    if data.get("code") != 200 or not data.get("token"):
        raise RuntimeError(f"迈鲸登录失败：code={data.get('code')}, msg={data.get('msg') or data.get('message')}")
    return {"token": data["token"], "captcha_uuid": uuid}


def write_auth_context(run_dir: Path, account_ref: str, token: str) -> Path:
    auth_path = run_dir / "outputs" / "maijing_auth_context.json"
    checkpoint.write_json(auth_path, {
        "system": "maijing",
        "account_ref": account_ref,
        "base_url": BASE_URL,
        "headers": {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        "cookie": {
            "name": "Admin-Token",
            "value": token,
            "domain": "mj-whale.com",
            "path": "/",
        },
    })
    checkpoint.write_json(run_dir / "evidence" / "api_responses" / "login_summary.json", {
        "system": "maijing",
        "account_ref": account_ref,
        "token_masked": secrets_loader.mask_secret(token),
        "auth_context_path": str(auth_path),
    })
    return auth_path


def main() -> None:
    parser = argparse.ArgumentParser(description="迈鲸 API 登录。")
    parser.add_argument("--account-ref", default="admin")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--base-dir", default=str(ROOT))
    args = parser.parse_args()

    run_dir = checkpoint.ensure_run_dir(
        base_dir=Path(args.base_dir).resolve(),
        workflow_id="maijing-login",
        workflow_name_cn="迈鲸登录",
        city=args.account_ref,
        batch=args.batch,
        dry_run=False,
        steps=STEPS,
    )

    try:
        checkpoint.update_step(run_dir, "load_account", "running", "读取账号引用")
        account = read_account(args.account_ref, args.username, args.password)
        checkpoint.update_step(run_dir, "load_account", "completed", "读取账号引用")

        checkpoint.update_step(run_dir, "get_captcha", "running", "获取验证码参数")
        captcha = get_captcha()
        checkpoint.update_step(run_dir, "get_captcha", "completed", "获取验证码参数")

        checkpoint.update_step(run_dir, "api_login", "running", "API 登录迈鲸")
        result = login_with_captcha(account["username"], account["password"], captcha)
        checkpoint.update_step(run_dir, "api_login", "completed", "API 登录迈鲸")

        checkpoint.update_step(run_dir, "write_auth_context", "running", "写入认证上下文")
        auth_path = write_auth_context(run_dir, args.account_ref, result["token"])
        checkpoint.update_step(run_dir, "write_auth_context", "completed", "写入认证上下文")
        checkpoint.append_log(run_dir, "迈鲸 API 登录完成。")
        print(f"迈鲸登录完成，运行目录：{run_dir}")
        print(f"认证上下文：{auth_path}")
    except Exception as exc:
        checkpoint.update_step(
            run_dir,
            "api_login",
            "failed",
            "API 登录迈鲸",
            {
                "step_name_cn": "API 登录迈鲸",
                "failure_reason": str(exc),
                "evidence_paths": ["logs/run.log", "evidence/api_responses/login_summary.json"],
                "resume_step": "api_login",
            },
        )
        raise


if __name__ == "__main__":
    main()
