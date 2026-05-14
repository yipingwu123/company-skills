#!/usr/bin/env python3
"""等待飞书群里有人回复「确认」，然后自动触发 match_by_phone.py。

用法：
    python3 wait_for_confirm.py \
        --result-csv runs/.../result_丽人.csv \
        --mobile-list-json runs/.../mobile_list_丽人.json \
        --maijing-xlsx runs/.../长沙市_公海客户_*.xlsx \
        --category 丽人
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEISHU_API = "https://open.feishu.cn/open-apis"
CN_TZ = timezone(timedelta(hours=8))
HERE = Path(__file__).resolve().parent


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


secrets_loader = load_module(ROOT / "common" / "secrets_loader.py", "secrets_loader")


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


def fetch_recent_messages(token: str, chat_id: str, since_ms: int) -> list[dict]:
    """拉取 chat_id 群里 since_ms 之后的消息（毫秒时间戳）。"""
    url = (
        f"{FEISHU_API}/im/v1/messages"
        f"?container_id={chat_id}&container_id_type=chat"
        f"&sort_type=ByCreateTimeDesc&page_size=20"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  [警告] 拉取消息失败：{e}")
        return []
    items = data.get("data", {}).get("items", [])
    # 只保留 since_ms 之后的消息
    return [m for m in items if int(m.get("create_time", "0")) > since_ms]


def extract_text(message: dict) -> str:
    """从消息对象里取出文本内容。"""
    try:
        content = json.loads(message.get("body", {}).get("content", "{}"))
        return content.get("text", "").strip()
    except Exception:
        return ""


def trigger_match(args: argparse.Namespace) -> None:
    script = HERE / "match_by_phone.py"
    cmd = [
        sys.executable, str(script),
        "--result-csv", args.result_csv,
        "--mobile-list-json", args.mobile_list_json,
        "--maijing-xlsx", args.maijing_xlsx,
        "--category", args.category,
        "--batch", args.batch,
        "--customer-source", args.customer_source,
    ]
    if args.run_dir:
        cmd += ["--run-dir", args.run_dir]
    print(f"\n[触发] 开始运行匹配脚本...")
    proc = subprocess.run(cmd)
    if proc.returncode == 0:
        print("[完成] 匹配脚本执行成功。")
    else:
        print(f"[错误] 匹配脚本退出码 {proc.returncode}。")


def main() -> None:
    parser = argparse.ArgumentParser(description="轮询飞书群，检测到「确认」后触发匹配")
    parser.add_argument("--result-csv", required=True)
    parser.add_argument("--mobile-list-json", required=True)
    parser.add_argument("--maijing-xlsx", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--batch", default="001")
    parser.add_argument("--customer-source", default="AI外呼")
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--account-ref", default="DXZG-1")
    parser.add_argument("--confirm-keyword", default="确认")
    parser.add_argument("--interval", type=int, default=15, help="轮询间隔秒数（默认 15）")
    args = parser.parse_args()

    accounts = secrets_loader.load_accounts()
    try:
        app = accounts["feishu_app"][args.account_ref]
    except KeyError:
        print(f"[错误] secrets 里找不到 feishu_app/{args.account_ref}")
        sys.exit(1)

    app_id = app["app_id"]
    app_secret = app["app_secret"]
    chat_id = app["chat_id"]

    # 往前回溯 5 分钟，避免发完 CSV 立即启动时漏掉刚发的「确认」
    since_ms = int((time.time() - 300) * 1000)

    print(f"[等待] 监听群：{chat_id}")
    print(f"[等待] 关键词：「{args.confirm_keyword}」，轮询间隔：{args.interval}s")
    print(f"[等待] 在飞书群里回复「{args.confirm_keyword}」即可触发匹配...")
    print("（Ctrl+C 退出）\n")

    token = get_token(app_id, app_secret)
    token_refreshed_at = time.time()

    try:
        while True:
            # token 有效期 2 小时，提前 10 分钟刷新
            if time.time() - token_refreshed_at > 6600:
                token = get_token(app_id, app_secret)
                token_refreshed_at = time.time()
                print("  [token 已刷新]")

            messages = fetch_recent_messages(token, chat_id, since_ms)
            for msg in messages:
                text = extract_text(msg)
                msg_time = datetime.fromtimestamp(
                    int(msg.get("create_time", "0")) / 1000, tz=CN_TZ
                ).strftime("%H:%M:%S")
                # 支持「确认」或「@机器人 确认」两种形式
                if args.confirm_keyword in text:
                    print(f"  [{msg_time}] 收到「{args.confirm_keyword}」，触发匹配！")
                    trigger_match(args)
                    return
                elif text:
                    print(f"  [{msg_time}] 忽略消息：{text[:30]}")

            # 更新 since_ms，避免重复检测同一批消息
            if messages:
                since_ms = max(int(m.get("create_time", "0")) for m in messages)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[退出] 已手动停止。")


if __name__ == "__main__":
    main()
