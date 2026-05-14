#!/usr/bin/env python3
"""查询飞书机器人所在群的 chat_id。

用法：
    python3 get_chat_id.py --account-ref DXZG-1
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


secrets_loader = load_module(ROOT / "common" / "secrets_loader.py", "secrets_loader")

FEISHU_API = "https://open.feishu.cn/open-apis"


def get_token(app_id: str, app_secret: str) -> str:
    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("code") != 0:
        raise RuntimeError(f"获取 token 失败：{data}")
    return data["tenant_access_token"]


def list_chats(token: str) -> list[dict]:
    chats = []
    page_token = ""
    while True:
        url = f"{FEISHU_API}/im/v1/chats?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("code") != 0:
            raise RuntimeError(f"列举群失败：{data}")
        chats.extend(data.get("data", {}).get("items", []))
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data["data"].get("page_token", "")
    return chats


def main() -> None:
    parser = argparse.ArgumentParser(description="查询飞书机器人所在群的 chat_id")
    parser.add_argument("--account-ref", default="DXZG-1")
    args = parser.parse_args()

    accounts = secrets_loader.load_accounts()
    try:
        app = accounts["feishu_app"][args.account_ref]
    except KeyError:
        print(f"[错误] secrets 里找不到 feishu_app/{args.account_ref}")
        sys.exit(1)

    app_id = app["app_id"]
    app_secret = app["app_secret"]

    print("获取 token...")
    token = get_token(app_id, app_secret)
    print("查询机器人所在群...")
    chats = list_chats(token)

    if not chats:
        print("机器人还没有加入任何群，请先把机器人拉入目标群。")
        return

    print(f"\n共找到 {len(chats)} 个群：\n")
    for c in chats:
        name = c.get("name") or c.get("description") or "(无名)"
        chat_id = c.get("chat_id", "")
        print(f"  群名：{name}")
        print(f"  chat_id：{chat_id}")
        print()

    print("将 chat_id 填入 .secrets/automation_accounts.json 的 feishu_app/DXZG-1.chat_id 字段即可。")


if __name__ == "__main__":
    main()
