#!/usr/bin/env python3
"""将火山引擎外呼结果 CSV 发送到飞书群，供人工审核后触发自动匹配导入。

步骤：
  1. 从 secrets 读取飞书 app 配置
  2. 获取 tenant_access_token
  3. 读取 CSV，过滤接通行
  4. 构建摘要文本
  5. 上传接通明细 CSV 为飞书文件
  6. 发送文字摘要消息到飞书群
  7. 发送文件消息到飞书群
  8. 写入 send_state.json

用法：
    python3 send_result_to_feishu.py \\
        --result-csv runs/2026-05-14/volcengine-call-result-export-丽人-001/outputs/result_丽人.csv \\
        --category 丽人

    python3 send_result_to_feishu.py \\
        --result-csv /path/to/result.csv \\
        --category 餐饮 \\
        --account-ref DXZG-1 \\
        --run-dir /path/to/run_dir
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ID = "volcengine-result-feishu-send"
WORKFLOW_NAME_CN = "火山结果飞书推送"

FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_FILE_UPLOAD_URL = "https://open.feishu.cn/open-apis/im/v1/files"
FEISHU_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"

# 接通状态判断：列名候选 → 关键词或数值判断
CALL_STATUS_COLS = ["通话状态", "呼叫状态"]
BILLSEC_COLS = ["billsec", "通话时长(秒)"]
ANSWERED_KEYWORDS = ["接通"]


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


secrets_loader = load_module(ROOT / "common" / "secrets_loader.py", "secrets_loader")


# ── token ────────────────────────────────────────────────────────────────────

def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    """获取飞书 tenant_access_token，不在日志中打印完整 token。"""
    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    req = urllib.request.Request(
        FEISHU_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        body = json.loads(r.read())

    if body.get("code") != 0:
        raise RuntimeError(f"获取 token 失败：code={body.get('code')} msg={body.get('msg')}")

    token = body["tenant_access_token"]
    expire = body.get("expire", "?")
    masked = token[:4] + "..." if len(token) > 4 else "***"
    print(f"[token] 已获取 tenant_access_token（{masked}，有效期 {expire}s）")
    return token


# ── CSV 解析 ─────────────────────────────────────────────────────────────────

def _try_parse_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    """尝试逗号分隔，失败则回退 tab，返回 (rows, delimiter)。"""
    for delim in (",", "\t"):
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f, delimiter=delim)
                rows = list(reader)
                if rows and len(list(rows[0].keys())) > 1:
                    return rows, delim
        except Exception:
            continue
    # 最终回退：强制用逗号
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=",")
        return list(reader), ","


def is_answered(row: dict[str, str]) -> bool:
    """判断一行是否为接通记录。"""
    # 方法1：通话状态 / 呼叫状态列含"接通"
    for col in CALL_STATUS_COLS:
        val = row.get(col, "")
        if any(kw in val for kw in ANSWERED_KEYWORDS):
            return True

    # 方法2：billsec / 通话时长(秒) > 0
    for col in BILLSEC_COLS:
        val = row.get(col, "").strip()
        if val:
            try:
                if float(val) > 0:
                    return True
            except ValueError:
                pass

    return False


def filter_answered(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """过滤接通行，找不到相关列时打印警告并返回空列表。"""
    if not rows:
        return []

    fieldnames = list(rows[0].keys())
    has_status = any(c in fieldnames for c in CALL_STATUS_COLS)
    has_billsec = any(c in fieldnames for c in BILLSEC_COLS)

    if not has_status and not has_billsec:
        print(f"[警告] CSV 中未找到通话状态列（{CALL_STATUS_COLS}）或通话时长列（{BILLSEC_COLS}），"
              f"实际列名：{fieldnames}")
        print("[警告] 无法判断接通，接通行数将为 0。")
        return []

    return [r for r in rows if is_answered(r)]


def rows_to_csv_bytes(rows: list[dict[str, str]], fieldnames: list[str]) -> bytes:
    """将行列表序列化为 UTF-8 BOM CSV 字节。"""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\r\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


# ── 飞书文件上传 ──────────────────────────────────────────────────────────────

def upload_file_to_feishu(token: str, filename: str, file_bytes: bytes) -> str:
    """上传文件到飞书，返回 file_key。手动构造 multipart/form-data。"""
    boundary = uuid.uuid4().hex

    def _part_header(name: str, extra: str = "") -> bytes:
        return f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"{extra}\r\n\r\n".encode("utf-8")

    body_parts: list[bytes] = []

    # file_type 字段
    body_parts.append(_part_header("file_type"))
    body_parts.append(b"stream\r\n")

    # file_name 字段
    body_parts.append(_part_header("file_name"))
    body_parts.append(filename.encode("utf-8") + b"\r\n")

    # file 字段（二进制）
    body_parts.append(
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
    )
    body_parts.append(file_bytes)
    body_parts.append(b"\r\n")

    # 结束分隔符
    body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))

    body = b"".join(body_parts)

    req = urllib.request.Request(
        FEISHU_FILE_UPLOAD_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"文件上传 HTTP 错误 {exc.code}：{err_body}") from exc

    if resp.get("code") != 0:
        raise RuntimeError(f"文件上传失败：code={resp.get('code')} msg={resp.get('msg')}")

    file_key = resp["data"]["file_key"]
    print(f"[上传] 文件上传成功，file_key={file_key}")
    return file_key


# ── 飞书消息发送 ──────────────────────────────────────────────────────────────

def send_text_message(token: str, chat_id: str, text: str) -> str:
    """发送文字消息到飞书群，返回 message_id。"""
    content = json.dumps({"text": text}, ensure_ascii=False)
    payload = json.dumps({
        "receive_id": chat_id,
        "msg_type": "text",
        "content": content,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        FEISHU_MESSAGE_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"文字消息发送 HTTP 错误 {exc.code}：{err_body}") from exc

    if resp.get("code") != 0:
        raise RuntimeError(f"文字消息发送失败：code={resp.get('code')} msg={resp.get('msg')}")

    msg_id = resp.get("data", {}).get("message_id", "")
    print(f"[消息] 文字消息已发送，message_id={msg_id}")
    return msg_id


def send_file_message(token: str, chat_id: str, file_key: str) -> str:
    """发送文件消息到飞书群，返回 message_id。"""
    content = json.dumps({"file_key": file_key}, ensure_ascii=False)
    payload = json.dumps({
        "receive_id": chat_id,
        "msg_type": "file",
        "content": content,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        FEISHU_MESSAGE_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"文件消息发送 HTTP 错误 {exc.code}：{err_body}") from exc

    if resp.get("code") != 0:
        raise RuntimeError(f"文件消息发送失败：code={resp.get('code')} msg={resp.get('msg')}")

    msg_id = resp.get("data", {}).get("message_id", "")
    print(f"[消息] 文件消息已发送，message_id={msg_id}")
    return msg_id


# ── 主逻辑 ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="将火山引擎外呼结果 CSV 发送到飞书群。")
    parser.add_argument("--result-csv", required=True, help="火山外呼结果 CSV 文件路径")
    parser.add_argument("--category", required=True, help="品类名称（如 丽人）")
    parser.add_argument("--account-ref", default="DXZG-1", help="飞书账号引用（默认 DXZG-1）")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="输出目录（默认 runs/{today}/volcengine-result-feishu-send-{category}-001/）",
    )
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    date_compact = datetime.now().strftime("%Y%m%d")

    # 确定 run_dir
    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
    else:
        safe_cat = "".join(c if (c.isalnum() or c in "-_") else "_" for c in args.category)
        run_dir = ROOT / "runs" / today / f"{WORKFLOW_ID}-{safe_cat}-001"

    outputs_dir = run_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    print(f"[初始化] 运行目录：{run_dir}")

    # ── 1. 读取 secrets ───────────────────────────────────────────────────────
    print(f"\n[步骤 1] 读取飞书 secrets（account_ref={args.account_ref}）")
    accounts = secrets_loader.load_accounts()
    feishu_accounts = accounts.get("feishu_app", {})
    if args.account_ref not in feishu_accounts:
        raise SystemExit(
            f"feishu_app 中找不到 account_ref={args.account_ref}，"
            f"可用账号：{list(feishu_accounts.keys())}"
        )
    feishu_conf = feishu_accounts[args.account_ref]
    app_id = feishu_conf["app_id"]
    app_secret = feishu_conf["app_secret"]
    chat_id = feishu_conf["chat_id"]
    print(f"[secrets] app_id={app_id}，chat_id={chat_id}")

    # ── 2. 获取 tenant_access_token ──────────────────────────────────────────
    print(f"\n[步骤 2] 获取 tenant_access_token")
    token = get_tenant_access_token(app_id, app_secret)

    # ── 3. 读取 CSV，过滤接通行 ───────────────────────────────────────────────
    print(f"\n[步骤 3] 读取 CSV 并过滤接通行")
    result_path = Path(args.result_csv).resolve()
    if not result_path.exists():
        raise SystemExit(f"result-csv 文件不存在：{result_path}")

    all_rows, delimiter = _try_parse_csv(result_path)
    total_count = len(all_rows)
    print(f"[CSV] 读取 {total_count} 行（分隔符={'逗号' if delimiter == ',' else 'Tab'}）")

    answered_rows = filter_answered(all_rows)
    answered_count = len(answered_rows)
    rate = f"{answered_count / total_count * 100:.1f}%" if total_count > 0 else "0%"
    print(f"[过滤] 接通：{answered_count}/{total_count}（{rate}）")

    # ── 4. 构建摘要文本 ───────────────────────────────────────────────────────
    print(f"\n[步骤 4] 构建摘要文本")
    summary_text = (
        f"【外呼明细通知】{args.category} - {today}\n"
        f"总呼叫：{total_count} 条\n"
        f"接通：{answered_count} 条（{rate}）\n"
        f"请核对以下明细，确认无误后回复「确认」以触发自动匹配导入。"
    )
    print(f"[摘要]\n{summary_text}")

    # ── 5. 上传接通明细 CSV ───────────────────────────────────────────────────
    print(f"\n[步骤 5] 上传接通明细 CSV 到飞书")
    if answered_rows:
        fieldnames = list(answered_rows[0].keys())
        csv_bytes = rows_to_csv_bytes(answered_rows, fieldnames)
    else:
        # 即使没有接通行也上传原始表头（空明细）
        if all_rows:
            fieldnames = list(all_rows[0].keys())
        else:
            fieldnames = []
        csv_bytes = rows_to_csv_bytes([], fieldnames)
        print("[警告] 接通行为空，上传空明细 CSV。")

    upload_filename = f"result_{args.category}_{date_compact}.csv"
    print(f"[上传] 文件名：{upload_filename}，大小：{len(csv_bytes)} bytes")
    file_key = upload_file_to_feishu(token, upload_filename, csv_bytes)

    # ── 6. 发送文字摘要消息 ───────────────────────────────────────────────────
    print(f"\n[步骤 6] 发送文字摘要消息到飞书群（chat_id={chat_id}）")
    text_msg_id = send_text_message(token, chat_id, summary_text)

    # ── 7. 发送文件消息 ───────────────────────────────────────────────────────
    print(f"\n[步骤 7] 发送文件消息到飞书群")
    file_msg_id = send_file_message(token, chat_id, file_key)

    # ── 8. 写入 send_state.json ───────────────────────────────────────────────
    print(f"\n[步骤 8] 写入 send_state.json")
    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    send_state = {
        "sent_at": sent_at,
        "file_key": file_key,
        "message_ids": {
            "text_message": text_msg_id,
            "file_message": file_msg_id,
        },
        "category": args.category,
        "answered_count": answered_count,
        "total_count": total_count,
        "answer_rate": rate,
        "account_ref": args.account_ref,
        "result_csv": str(result_path),
    }
    state_path = outputs_dir / "send_state.json"
    state_path.write_text(
        json.dumps(send_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[输出] send_state.json → {state_path}")

    print(f"\n[完成]")
    print(f"品类：{args.category}，接通 {answered_count}/{total_count}（{rate}）")
    print(f"飞书消息已发送至 chat_id={chat_id}")
    print(f"运行目录：{run_dir}")


if __name__ == "__main__":
    main()
