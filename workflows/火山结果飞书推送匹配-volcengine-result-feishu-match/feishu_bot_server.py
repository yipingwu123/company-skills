#!/usr/bin/env python3
"""飞书机器人本地 HTTP 服务器。

监听飞书事件回调，当群内有人发送确认关键词时，自动触发 match_by_phone.py 脚本。
只使用 Python 标准库，无需额外安装依赖。

用法示例：
    python3 feishu_bot_server.py \\
        --result-csv /path/to/result.csv \\
        --mobile-list-json /path/to/mobile_list.json \\
        --maijing-xlsx /path/to/maijing.xlsx \\
        --category 丽人 \\
        --batch 001
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# 将 common/ 目录加入路径，以便导入 secrets_loader
_SKILLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_SKILLS_ROOT))

from common.secrets_loader import load_accounts, mask_secret  # noqa: E402


# ---------------------------------------------------------------------------
# 飞书 API 工具函数
# ---------------------------------------------------------------------------

def _get_tenant_access_token(app_id: str, app_secret: str) -> str:
    """通过 app_id + app_secret 获取 tenant_access_token。"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"获取 tenant_access_token 失败：{e}") from e

    if body.get("code") != 0:
        raise RuntimeError(f"飞书 API 返回错误：{body.get('msg')} (code={body.get('code')})")

    token = body.get("tenant_access_token", "")
    print(f"[飞书] 获取 tenant_access_token 成功（末尾4位：...{token[-4:] if len(token) > 4 else '****'}）")
    return token


def _send_text_to_chat(chat_id: str, text: str, app_id: str, app_secret: str) -> None:
    """向指定飞书群发送文本消息。"""
    token = _get_tenant_access_token(app_id, app_secret)
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    payload = json.dumps({
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"[警告] 发送飞书消息失败：{e}")
        return

    if body.get("code") != 0:
        print(f"[警告] 飞书消息 API 返回错误：{body.get('msg')} (code={body.get('code')})")
    else:
        print(f"[飞书] 消息已发送到群：{chat_id}")


# ---------------------------------------------------------------------------
# HTTPServer 子类（携带服务器级别状态）
# ---------------------------------------------------------------------------

class FeishuBotServer(HTTPServer):
    """带额外配置属性的 HTTPServer，用于跨请求共享状态。"""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class,
        *,
        secrets: dict,
        result_csv: str,
        mobile_list_json: str,
        maijing_xlsx: str,
        category: str,
        batch: str,
        confirm_keyword: str,
        run_dir: str | None,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.secrets = secrets                      # 飞书 app 配置（含敏感字段，勿打印）
        self.result_csv = result_csv
        self.mobile_list_json = mobile_list_json
        self.maijing_xlsx = maijing_xlsx
        self.category = category
        self.batch = batch
        self.confirm_keyword = confirm_keyword
        self.run_dir = run_dir
        self.confirm_triggered = False              # 防止重复触发


# ---------------------------------------------------------------------------
# 请求处理器
# ---------------------------------------------------------------------------

class FeishuEventHandler(BaseHTTPRequestHandler):
    """处理飞书事件回调的 HTTP 请求处理器。"""

    # 覆盖 log_message 避免每次请求都打印访问日志（飞书重试会刷屏）
    def log_message(self, format, *args):  # noqa: A002
        pass

    def do_POST(self):  # noqa: N802
        """处理所有 POST 请求（飞书事件回调均为 POST）。"""
        # 读取请求体
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[警告] 无法解析请求体 JSON：{e}")
            self._respond_200("{}")
            return

        # 仅处理飞书 2.0 schema
        if data.get("schema") != "2.0":
            print(f"[忽略] 非 2.0 schema 请求，schema={data.get('schema')!r}")
            self._respond_200("{}")
            return

        header = data.get("header", {})
        event_type = header.get("event_type", "")
        token = header.get("token", "")

        # Token 校验（不匹配仍响应 200，否则飞书会不停重试）
        expected_token = self.server.secrets.get("verification_token", "")
        if token != expected_token:
            print(f"[警告] verification_token 不匹配，忽略此事件（收到末尾4位：...{token[-4:] if len(token) > 4 else '????'}）")
            # 仍需响应 200，防止飞书反复重试
            self._respond_200("{}")
            return

        # ----------------------------------------------------------------
        # URL 验证
        # ----------------------------------------------------------------
        if event_type == "url_verification":
            event = data.get("event", {})
            challenge = event.get("challenge", "")
            print(f"[飞书] 收到 URL 验证请求，challenge={challenge!r}")
            self._respond_200(json.dumps({"challenge": challenge}))
            return

        # ----------------------------------------------------------------
        # 消息接收
        # ----------------------------------------------------------------
        if event_type == "im.message.receive_v1":
            event = data.get("event", {})
            message = event.get("message", {})
            msg_type = message.get("message_type", "")

            if msg_type != "text":
                # 非文字消息，直接忽略
                self._respond_200("{}")
                return

            # content 是 JSON 字符串，形如 '{"text": "确认"}'
            raw_content = message.get("content", "{}")
            try:
                content_obj = json.loads(raw_content)
                text = content_obj.get("text", "").strip()
            except (json.JSONDecodeError, AttributeError):
                text = ""

            confirm_keyword = self.server.confirm_keyword

            if text == confirm_keyword:
                if self.server.confirm_triggered:
                    print(f"[忽略] 再次收到「{confirm_keyword}」，但匹配任务已触发过，跳过。")
                    self._respond_200("{}")
                    return

                print(f"收到确认，开始匹配...")

                # 设置标志，防止重复触发
                self.server.confirm_triggered = True

                # 立即响应 200，不等待子进程结束
                self._respond_200("{}")

                # 启动 match_by_phone.py 子进程
                self._spawn_match_subprocess()

                # 向飞书群发送确认回复
                self._notify_feishu_chat()
                return

            else:
                # 其他文字消息，忽略
                self._respond_200("{}")
                return

        # 其他事件类型，忽略
        print(f"[忽略] 未知事件类型：{event_type!r}")
        self._respond_200("{}")

    # ----------------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------------

    def _respond_200(self, body: str) -> None:
        """发送 HTTP 200 响应。"""
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _spawn_match_subprocess(self) -> None:
        """在后台启动 match_by_phone.py 子进程。"""
        script_dir = Path(__file__).resolve().parent
        script_path = script_dir / "match_by_phone.py"

        cmd = [
            sys.executable,
            str(script_path),
            "--result-csv", self.server.result_csv,
            "--mobile-list-json", self.server.mobile_list_json,
            "--maijing-xlsx", self.server.maijing_xlsx,
            "--category", self.server.category,
            "--batch", self.server.batch,
        ]

        if self.server.run_dir:
            cmd += ["--run-dir", self.server.run_dir]

        print(f"[子进程] 启动命令：{' '.join(cmd)}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            print(f"[子进程] match_by_phone.py 已启动，PID={proc.pid}")
        except Exception as e:  # noqa: BLE001
            print(f"[错误] 启动 match_by_phone.py 失败：{e}")

    def _notify_feishu_chat(self) -> None:
        """向飞书群发送"已收到确认"通知。"""
        secrets = self.server.secrets
        app_id = secrets.get("app_id", "")
        app_secret = secrets.get("app_secret", "")
        chat_id = secrets.get("chat_id", "")

        if not all([app_id, app_secret, chat_id]):
            print("[警告] 飞书 app 配置不完整，跳过发送确认通知。")
            return

        # 拼接输出路径提示
        if self.server.run_dir:
            output_hint = f"{self.server.run_dir}/outputs/"
        else:
            output_hint = "当前目录下的 outputs/"

        notice_text = f"已收到确认，正在运行匹配，完成后输出文件在 {output_hint}"

        try:
            _send_text_to_chat(chat_id, notice_text, app_id, app_secret)
        except Exception as e:  # noqa: BLE001
            print(f"[警告] 发送飞书通知时出错：{e}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="飞书机器人本地 HTTP 服务器，监听「确认」关键词后自动触发匹配脚本",
    )
    parser.add_argument("--port", type=int, default=8088, help="监听端口（默认 8088）")
    parser.add_argument("--account-ref", default="DXZG-1", help="飞书账号引用名（默认 DXZG-1）")
    parser.add_argument("--result-csv", required=True, help="火山 result CSV 路径")
    parser.add_argument("--mobile-list-json", required=True, help="mobile_list JSON 路径")
    parser.add_argument("--maijing-xlsx", required=True, help="迈鲸导出 xlsx 路径")
    parser.add_argument("--category", required=True, help="行业类目，例如：丽人")
    parser.add_argument("--batch", default="001", help="批次号（默认 001）")
    parser.add_argument("--confirm-keyword", default="确认", help="触发匹配的关键词（默认：确认）")
    parser.add_argument("--run-dir", default=None, help="匹配结果输出目录（可选）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # 加载飞书 app 配置
    try:
        accounts = load_accounts()
        secrets = accounts["feishu_app"][args.account_ref]
    except (FileNotFoundError, KeyError) as e:
        print(f"[错误] 加载飞书账号配置失败：{e}")
        sys.exit(1)

    # 简单验证必要字段存在（不打印值）
    required_keys = ["app_id", "app_secret", "verification_token", "chat_id"]
    missing = [k for k in required_keys if not secrets.get(k)]
    if missing:
        print(f"[错误] 飞书账号配置缺少字段：{missing}，请检查 .secrets/automation_accounts.json")
        sys.exit(1)

    print(f"[配置] account_ref={args.account_ref}, category={args.category}, batch={args.batch}")
    print(f"[配置] result_csv={args.result_csv}")
    print(f"[配置] mobile_list_json={args.mobile_list_json}")
    print(f"[配置] maijing_xlsx={args.maijing_xlsx}")
    if args.run_dir:
        print(f"[配置] run_dir={args.run_dir}")

    # 创建服务器
    server = FeishuBotServer(
        ("", args.port),
        FeishuEventHandler,
        secrets=secrets,
        result_csv=args.result_csv,
        mobile_list_json=args.mobile_list_json,
        maijing_xlsx=args.maijing_xlsx,
        category=args.category,
        batch=args.batch,
        confirm_keyword=args.confirm_keyword,
        run_dir=args.run_dir,
    )

    print(f"\n飞书机器人服务启动，监听端口 {args.port}")
    print(f"ngrok 命令：ngrok http {args.port}")
    print("请将 ngrok URL 配置到飞书应用事件订阅回调地址")
    print(f"等待「{args.confirm_keyword}」关键词...\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[退出] 收到 Ctrl+C，服务器已停止。")
        server.server_close()


if __name__ == "__main__":
    main()
