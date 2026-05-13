#!/usr/bin/env python3
"""检查迈鲸 session 是否仍然有效。

读取 maijing_auth_context.json，向 /user/info 发一个轻量只读请求，
判断 session 是否过期。过期则提示重新登录。

用法：
    python3 check_session.py \\
        --auth-context runs/2026-05-14/maijing-login-DXZG-1-001/outputs/maijing_auth_context.json

退出码：
    0 = session 有效
    1 = session 过期或无法连接
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


# 用于验活的只读接口候选（依次尝试，第一个 200 即认为有效）
PROBE_ENDPOINTS = [
    "/user/info",
    "/user/current",
    "/common/user/info",
]


def probe_session(base_url: str, headers: dict[str, str]) -> tuple[bool, str]:
    """返回 (is_valid, detail_msg)。"""
    for endpoint in PROBE_ENDPOINTS:
        url = base_url.rstrip("/") + endpoint
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
                code = body.get("code", resp.status)
                if code in (200, 0, "200", "0"):
                    return True, f"接口 {endpoint} 返回 code={code}，session 有效"
                if code in (401, "401"):
                    return False, f"接口 {endpoint} 返回 code={code}，session 已过期"
                # 其他 code 继续尝试下一个接口
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return False, f"接口 {endpoint} 返回 HTTP 401，session 已过期"
            if e.code == 404:
                continue  # 该接口不存在，试下一个
        except urllib.error.URLError as e:
            return False, f"无法连接：{e}"
    return False, "所有探测接口均无法判断，请手动确认"


def main() -> None:
    parser = argparse.ArgumentParser(description="检查迈鲸 session 有效性。")
    parser.add_argument("--auth-context", required=True,
                        help="maijing_auth_context.json 路径")
    args = parser.parse_args()

    auth_path = Path(args.auth_context).resolve()
    if not auth_path.exists():
        print(f"❌ auth_context 不存在：{auth_path}")
        sys.exit(1)

    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    base_url = auth.get("base_url", "")
    headers = dict(auth.get("headers", {}))

    if not base_url:
        print("❌ auth_context 缺少 base_url 字段。")
        sys.exit(1)

    # 打印 auth 基础信息（不输出完整 token）
    created_at = auth.get("created_at", "未知")
    account_ref = auth.get("account_ref", "未知")
    print(f"auth_context：{auth_path.name}")
    print(f"账号引用：{account_ref}")
    print(f"创建时间：{created_at}")
    print(f"Base URL：{base_url}")
    print(f"正在探测 session...")

    valid, detail = probe_session(base_url, headers)

    if valid:
        print(f"\n✅ Session 有效 — {detail}")
        print(f"\n可以继续执行：")
        print(f"  python3 workflows/迈鲸商机导入-maijing-lead-import/import_leads_dry_run.py --execute-import ...")
        sys.exit(0)
    else:
        print(f"\n❌ Session 无效 — {detail}")
        print(f"\n请重新登录：")
        print(f"  python3 login/迈鲸登录-maijing-login/login_api.py --account-ref {account_ref} --batch 002")
        sys.exit(1)


if __name__ == "__main__":
    main()
