#!/usr/bin/env python3
"""本地 secrets 读取工具。

默认读取 .secrets/automation_accounts.json。不要在日志中输出返回值。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRETS_PATH = ROOT / ".secrets" / "automation_accounts.json"


def load_accounts(path: Path | None = None) -> dict[str, Any]:
    target = path or Path(os.environ.get("AUTOMATION_ACCOUNTS_FILE", DEFAULT_SECRETS_PATH))
    if not target.exists():
        raise FileNotFoundError(f"secrets 文件不存在：{target}")
    return json.loads(target.read_text(encoding="utf-8"))


def get_account(system: str, account_ref: str, path: Path | None = None) -> dict[str, str]:
    accounts = load_accounts(path)
    try:
        account = accounts[system][account_ref]
    except KeyError as exc:
        raise KeyError(f"账号引用不存在：system={system}, account_ref={account_ref}") from exc
    if not account.get("username") or not account.get("password"):
        raise ValueError(f"账号缺少 username 或 password：system={system}, account_ref={account_ref}")
    return {
        "username": str(account["username"]),
        "password": str(account["password"]),
    }


def mask_secret(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "***REDACTED***"
    return f"{value[:keep]}...{value[-keep:]}"
