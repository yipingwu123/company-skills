#!/usr/bin/env python3
"""迈鲸公海客户 API 只读侦查。

读取 maijing-login 生成的认证上下文，调用公海客户相关只读接口，
只保存接口结构、分页信息和选项摘要，不保存完整客户明细。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import urllib.parse
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


STEPS = [
    checkpoint.StepDef("load_auth_context", "读取迈鲸认证上下文"),
    checkpoint.StepDef("call_option_apis", "调用筛选选项接口"),
    checkpoint.StepDef("call_public_list_summary", "调用公海列表结构摘要"),
    checkpoint.StepDef("write_recon_report", "写入接口侦查报告"),
    checkpoint.StepDef("stop_before_export", "停在真实导出前"),
]


READONLY_ENDPOINTS = {
    "source_clues_dict": "/system/dict/data/listDict",
    "history_tag_filter_options": "/customer/public/historyTagFilterOptions",
    "region_options": "/customer/public/regionOptions",
    "sync_detail_status": "/customer/sync/detail/status/detail",
    "public_list": "/customer/public/list",
}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_auth_context(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("system") != "maijing":
        raise RuntimeError("认证上下文不是 maijing。")
    token = data.get("headers", {}).get("Authorization") or ""
    if not token.startswith("Bearer "):
        raise RuntimeError("认证上下文缺少 Authorization token。")
    return data


def auth_headers(auth: dict[str, Any]) -> dict[str, str]:
    headers = dict(auth.get("headers") or {})
    headers.setdefault("User-Agent", "Mozilla/5.0")
    headers.setdefault("Accept", "application/json, text/plain, */*")
    headers["Content-Type"] = "application/json"
    return headers


def request_json(path: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = urllib.parse.urlencode(params or {}, doseq=True)
    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{query}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def shape_of(value: Any, depth: int = 0) -> Any:
    """返回数据结构形状，不返回具体业务值。"""
    if depth >= 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {
            key: shape_of(item, depth + 1)
            for key, item in list(value.items())[:80]
        }
    if isinstance(value, list):
        if not value:
            return {"type": "list", "length": 0, "item_shape": None}
        return {
            "type": "list",
            "length": len(value),
            "item_shape": shape_of(value[0], depth + 1),
        }
    return type(value).__name__


def summarize_options(value: Any, limit: int = 30) -> dict[str, Any]:
    """提取非敏感选项摘要：字段名、数量、少量标签。

    这里用于城市、区县、字典值等筛选项，不用于客户列表行。
    """
    labels: list[str] = []

    def walk(node: Any) -> None:
        if len(labels) >= limit:
            return
        if isinstance(node, dict):
            for key in ("label", "name", "dictLabel", "city", "regionName", "value"):
                item = node.get(key)
                if isinstance(item, str) and item and item not in labels:
                    labels.append(item)
                    break
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return {
        "shape": shape_of(value),
        "sample_labels": labels,
        "sample_label_count": len(labels),
    }


def summarize_public_list(value: dict[str, Any]) -> dict[str, Any]:
    rows = value.get("rows")
    if rows is None:
        rows = value.get("data", {}).get("rows") if isinstance(value.get("data"), dict) else None
    if rows is None:
        rows = value.get("data", {}).get("list") if isinstance(value.get("data"), dict) else None

    row_count = len(rows) if isinstance(rows, list) else None
    first_row_keys = sorted(rows[0].keys()) if isinstance(rows, list) and rows and isinstance(rows[0], dict) else []
    total = value.get("total")
    if total is None and isinstance(value.get("data"), dict):
        total = value["data"].get("total")
    return {
        "code": value.get("code"),
        "msg": value.get("msg"),
        "total": total,
        "row_count_in_response": row_count,
        "first_row_keys_only": first_row_keys,
        "response_shape": shape_of(value),
        "customer_rows_saved": False,
    }


def write_report(run_dir: Path, summaries: dict[str, Any]) -> None:
    lines = [
        "# 迈鲸公海客户 API 只读侦查报告",
        "",
        "## 结论",
        "",
        "- 已验证登录上下文可以访问公海客户只读接口。",
        "- 本次只保存接口结构、分页信息、筛选选项摘要；未保存完整客户行，未导出文件。",
        "- 下一步应根据筛选控件交互或前端代码确认查询参数名，再做带条件的 dry-run 计数校验。",
        "",
        "## 已验证接口",
        "",
    ]
    for name, summary in summaries.items():
        lines.append(f"- `{name}`：code={summary.get('code')}，说明={summary.get('note', '已记录结构摘要')}")
    lines.extend([
        "",
        "## 停点",
        "",
        "- 已停在真实导出前。",
        "- 未点击导出，未下载客户文件。",
    ])
    (run_dir / "outputs" / "api_recon_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="迈鲸公海客户 API 只读侦查。")
    parser.add_argument("--auth-context", required=True)
    parser.add_argument("--batch", default="001")
    parser.add_argument("--page-size", type=int, default=10)
    args = parser.parse_args()

    run_dir = checkpoint.ensure_run_dir(
        base_dir=ROOT,
        workflow_id="maijing-public-sea-api-recon",
        workflow_name_cn="迈鲸公海客户 API 侦查",
        city="接口侦查",
        batch=args.batch,
        dry_run=True,
        steps=STEPS,
    )

    checkpoint.update_step(run_dir, "load_auth_context", "running", "读取迈鲸认证上下文")
    auth_context_path = Path(args.auth_context).resolve()
    auth = load_auth_context(auth_context_path)
    headers = auth_headers(auth)
    write_json(run_dir / "input" / "api_recon_input.json", {
        "auth_context_path": str(auth_context_path),
        "page_size": args.page_size,
        "readonly_only": True,
    })
    checkpoint.update_step(run_dir, "load_auth_context", "completed", "读取迈鲸认证上下文")

    summaries: dict[str, Any] = {}
    raw_dir = run_dir / "evidence" / "api_responses"

    checkpoint.update_step(run_dir, "call_option_apis", "running", "调用筛选选项接口")
    option_calls = {
        "source_clues_dict": {
            "path": READONLY_ENDPOINTS["source_clues_dict"],
            "params": {"pageNum": 1, "pageSize": 100, "dictType": "source_clues"},
        },
        "history_tag_filter_options": {
            "path": READONLY_ENDPOINTS["history_tag_filter_options"],
            "params": {},
        },
        "region_options": {
            "path": READONLY_ENDPOINTS["region_options"],
            "params": {},
        },
        "sync_detail_status": {
            "path": READONLY_ENDPOINTS["sync_detail_status"],
            "params": {},
        },
    }
    for name, call in option_calls.items():
        response = request_json(call["path"], headers=headers, params=call["params"])
        summary = summarize_options(response)
        summary["code"] = response.get("code")
        summary["note"] = "筛选选项结构摘要"
        summaries[name] = summary
        write_json(raw_dir / f"{name}_summary.json", summary)
    checkpoint.update_step(run_dir, "call_option_apis", "completed", "调用筛选选项接口")

    checkpoint.update_step(run_dir, "call_public_list_summary", "running", "调用公海列表结构摘要")
    list_response = request_json(
        READONLY_ENDPOINTS["public_list"],
        headers=headers,
        params={"pageNum": 1, "pageSize": args.page_size},
    )
    public_list_summary = summarize_public_list(list_response)
    public_list_summary["note"] = "公海客户列表结构摘要，未保存客户行"
    summaries["public_list"] = public_list_summary
    write_json(raw_dir / "public_list_summary.json", public_list_summary)
    checkpoint.update_step(run_dir, "call_public_list_summary", "completed", "调用公海列表结构摘要")

    checkpoint.update_step(run_dir, "write_recon_report", "running", "写入接口侦查报告")
    write_json(run_dir / "outputs" / "api_recon_summary.json", summaries)
    write_report(run_dir, summaries)
    checkpoint.check_contract(run_dir)
    checkpoint.update_step(run_dir, "write_recon_report", "completed", "写入接口侦查报告")
    checkpoint.update_step(run_dir, "stop_before_export", "pending", "停在真实导出前")
    checkpoint.append_log(run_dir, "迈鲸公海客户 API 只读侦查完成，未导出，未保存客户明细。")

    print(f"迈鲸公海客户 API 只读侦查完成，运行目录：{run_dir}")
    print(f"侦查报告：{run_dir / 'outputs' / 'api_recon_report.md'}")
    print(f"结构摘要：{run_dir / 'outputs' / 'api_recon_summary.json'}")


if __name__ == "__main__":
    main()
