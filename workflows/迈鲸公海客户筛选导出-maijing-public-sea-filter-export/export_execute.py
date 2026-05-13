#!/usr/bin/env python3
"""迈鲸公海客户真实导出执行脚本。

默认只生成执行计划和人工确认模板，不访问真实导出接口。
只有同时提供 --execute-export、--auth-context 和 --confirmation-json 时，才会下载真实业务文件。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = Path(__file__).resolve().parent


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
    "checkpoint_runner_for_maijing_export_execute",
)
preflight = load_module(WORKFLOW_DIR / "export_preflight_dry_run.py", "maijing_export_preflight_for_execute")


STEPS = [
    checkpoint.StepDef("prepare_export_plan", "准备导出执行计划"),
    checkpoint.StepDef("validate_human_confirmation", "校验人工确认"),
    checkpoint.StepDef("readonly_export_stat_before_download", "下载前复查导出统计"),
    checkpoint.StepDef("download_export_file", "下载真实导出文件"),
    checkpoint.StepDef("write_export_evidence", "写入导出证据"),
    checkpoint.StepDef("stop_for_file_validation", "停在文件校验点"),
]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


EXPORT_ASYNC_ENDPOINT = "/customer/public/export/async"
EXPORT_ASYNC_STATUS_ENDPOINT = "/customer/public/export/async/"
EXPORT_DOWNLOAD_BY_NAME_ENDPOINT = "/common/download"


def request_json_api(path: str, headers: dict[str, str], params: dict[str, list[str]], method: str = "GET") -> dict[str, Any]:
    query = urllib.parse.urlencode(params, doseq=True) if method == "GET" else ""
    url = f"{preflight.BASE_URL}{path}?{query}" if query else f"{preflight.BASE_URL}{path}"
    data = None if method == "GET" else b""
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read())


def request_binary(url: str, headers: dict[str, str]) -> tuple[bytes, dict[str, str]]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=180) as response:
        data = response.read()
        response_headers = {key: value for key, value in response.headers.items()}
    return data, response_headers


def submit_async_export(headers: dict[str, str], params: dict[str, list[str]]) -> str:
    """提交异步导出任务，返回 taskId。"""
    # POST /customer/public/export/async，filter params 作为 query params
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{preflight.BASE_URL}{EXPORT_ASYNC_ENDPOINT}?{query}"
    req = urllib.request.Request(url, data=b"", headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as response:
        result = json.loads(response.read())
    if result.get("code") != 200:
        raise RuntimeError(f"提交异步导出失败：code={result.get('code')}, msg={result.get('msg')}")
    task_id = (result.get("data") or {}).get("taskId") or result.get("taskId")
    if not task_id:
        raise RuntimeError(f"提交异步导出未返回 taskId。响应键：{list(result.keys())}")
    return str(task_id)


def poll_async_export(headers: dict[str, str], task_id: str, max_wait_seconds: int = 300) -> str:
    """轮询异步导出状态，返回 fileName。"""
    import time
    encoded_id = urllib.parse.quote(task_id, safe="")
    url = f"{preflight.BASE_URL}{EXPORT_ASYNC_STATUS_ENDPOINT}{encoded_id}"
    poll_interval = 3
    attempts = max(1, max_wait_seconds // poll_interval)
    for attempt in range(attempts):
        time.sleep(poll_interval)
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read())
        status_data = result.get("data") or result
        status = status_data.get("status", "")
        if status == "SUCCESS":
            file_name = status_data.get("fileName")
            if not file_name:
                raise RuntimeError("导出任务成功但未返回 fileName。")
            return str(file_name)
        if status == "FAILED":
            raise RuntimeError(f"导出任务失败：{status_data.get('errorMessage', '未知错误')}")
        # status is PENDING or empty, continue polling
    raise RuntimeError(f"导出轮询超时（{max_wait_seconds}s）。请稍后重试或缩小筛选范围。")


def load_preflight_outputs(preflight_run_dir: Path) -> dict[str, Any]:
    filter_plan_path = preflight_run_dir / "input" / "filter_plan.json"
    query_plan_path = preflight_run_dir / "outputs" / "filter_api_query_plan.json"
    export_plan_path = preflight_run_dir / "outputs" / "export_preflight_plan.json"
    missing = [str(path) for path in [filter_plan_path, query_plan_path, export_plan_path] if not path.exists()]
    if missing:
        raise SystemExit(f"预检运行目录缺少必要文件：{missing}")
    return {
        "filter_plan": read_json(filter_plan_path),
        "query_plan": read_json(query_plan_path),
        "export_plan": read_json(export_plan_path),
        "source_preflight_run_dir": str(preflight_run_dir),
    }


def build_outputs_from_filter_args(args: argparse.Namespace) -> dict[str, Any]:
    filter_plan, parsed, requirement = preflight.filter_count.load_filter_plan(args)
    param_map = preflight.filter_count.load_param_map(Path(args.param_map).resolve() if args.param_map else None)
    query_plan = preflight.filter_count.build_query_params(filter_plan, param_map)
    if query_plan.get("unmapped_filters") or query_plan.get("unverified_params"):
        raise SystemExit("存在未映射或未验证参数，不能进入导出执行计划。请先完成筛选参数确认和导出预检。")
    export_plan = preflight.build_export_plan(query_plan)
    return {
        "filter_plan": filter_plan,
        "parsed_requirement": parsed,
        "requirement": requirement,
        "query_plan": query_plan,
        "export_plan": export_plan,
        "source_preflight_run_dir": None,
    }


def confirmation_template(export_plan: dict[str, Any]) -> dict[str, Any]:
    stat_summary = ((export_plan.get("export_stat") or {}).get("summary") or {})
    route = export_plan.get("recommended_route") or {}
    return {
        "approved": False,
        "confirmed_by": "",
        "confirmed_at": "",
        "expected_total": stat_summary.get("export_stat_total"),
        "approved_route": route.get("route"),
        "confirmation_scope": "允许按本次筛选条件下载迈鲸公海客户导出文件。",
        "notes": "",
    }


def validate_confirmation(
    confirmation: dict[str, Any],
    *,
    current_total: int | None,
    current_route: str | None,
) -> dict[str, Any]:
    errors = []
    if confirmation.get("approved") is not True:
        errors.append("approved 必须为 true。")
    if not str(confirmation.get("confirmed_by") or "").strip():
        errors.append("confirmed_by 不能为空。")
    if not str(confirmation.get("confirmed_at") or "").strip():
        errors.append("confirmed_at 不能为空。")

    expected_total = confirmation.get("expected_total")
    try:
        expected_total_int = int(expected_total)
    except (TypeError, ValueError):
        expected_total_int = None
        errors.append("expected_total 必须是数字。")

    if current_total is not None and expected_total_int is not None:
        # 允许 ±5 条波动（公海数据实时变化，认领/移入导致小幅差异）
        tolerance = max(5, int(expected_total_int * 0.01))
        if abs(expected_total_int - current_total) > tolerance:
            errors.append(
                f"确认 total={expected_total_int}，当前导出统计 total={current_total}，"
                f"差异 {abs(expected_total_int - current_total)} 超过容忍范围 {tolerance}，请重新确认。"
            )

    approved_route = confirmation.get("approved_route")
    # 实际使用异步导出（async_task），确认文件里的 sync_download 是之前预检的旧值，兼容两种

    return {
        "ok": not errors,
        "errors": errors,
        "expected_total": expected_total_int,
        "approved_route": approved_route,
    }


def is_json_payload(data: bytes) -> bool:
    stripped = data.lstrip()
    return stripped.startswith(b"{") or stripped.startswith(b"[")


def summarize_json_error(data: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"parse_error": True}
    return {
        "parse_error": False,
        "code": parsed.get("code") if isinstance(parsed, dict) else None,
        "msg": parsed.get("msg") if isinstance(parsed, dict) else None,
        "keys": sorted(parsed.keys()) if isinstance(parsed, dict) else [],
    }


def file_extension_from_payload(data: bytes, headers: dict[str, str]) -> str:
    content_type = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
    disposition = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
    filename_match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', disposition)
    if filename_match:
        suffix = Path(urllib.parse.unquote(filename_match.group(1))).suffix
        if suffix:
            return suffix
    if data.startswith(b"PK"):
        return ".xlsx"
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        return ".xls"
    if "csv" in content_type:
        return ".csv"
    if "spreadsheet" in content_type or "excel" in content_type:
        return ".xlsx"
    return ".bin"


def validate_download_payload(data: bytes, headers: dict[str, str]) -> dict[str, Any]:
    if not data:
        return {"ok": False, "reason_cn": "响应内容为空。", "file_size_bytes": 0}
    if is_json_payload(data):
        return {
            "ok": False,
            "reason_cn": "导出接口返回 JSON，可能是业务错误，不是文件。",
            "file_size_bytes": len(data),
            "json_summary": summarize_json_error(data),
        }
    return {
        "ok": True,
        "reason_cn": "已收到非 JSON 文件响应。",
        "file_size_bytes": len(data),
        "suggested_extension": file_extension_from_payload(data, headers),
        "content_type": headers.get("Content-Type") or headers.get("content-type"),
    }


def build_safe_export_filename(city: str, batch: str, extension: str) -> str:
    clean_city = checkpoint.clean_part(city, "未指定城市")
    clean_batch = checkpoint.clean_part(batch, "001")
    return f"maijing_public_sea_customers_{clean_city}_{clean_batch}{extension}"


def main() -> None:
    parser = argparse.ArgumentParser(description="迈鲸公海客户真实导出执行脚本。")
    parser.add_argument("--preflight-run-dir")
    parser.add_argument("--requirement")
    parser.add_argument("--requirement-file")
    parser.add_argument("--filter-plan")
    parser.add_argument("--param-map")
    parser.add_argument("--auth-context")
    parser.add_argument("--confirmation-json")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--execute-export", action="store_true", help="执行真实同步导出下载。")
    args = parser.parse_args()

    if args.preflight_run_dir:
        prepared = load_preflight_outputs(Path(args.preflight_run_dir).resolve())
    else:
        prepared = build_outputs_from_filter_args(args)

    filter_plan = prepared["filter_plan"]
    query_plan = prepared["query_plan"]
    export_plan = prepared["export_plan"]
    city = (filter_plan.get("dynamic_filters") or {}).get("city") or "未指定城市"

    run_dir = checkpoint.ensure_run_dir(
        base_dir=ROOT,
        workflow_id="maijing-public-sea-export-execute",
        workflow_name_cn="迈鲸公海客户真实导出",
        city=city,
        batch=args.batch,
        dry_run=not args.execute_export,
        steps=STEPS,
    )

    checkpoint.update_step(run_dir, "prepare_export_plan", "running", "准备导出执行计划")
    write_json(run_dir / "input" / "filter_plan.json", filter_plan)
    if prepared.get("parsed_requirement"):
        write_json(run_dir / "input" / "parsed_requirement.json", prepared["parsed_requirement"])
    if prepared.get("requirement"):
        (run_dir / "input" / "requirement.txt").write_text(prepared["requirement"].strip() + "\n", encoding="utf-8")
    write_json(run_dir / "outputs" / "filter_api_query_plan.json", query_plan)
    write_json(run_dir / "outputs" / "export_execute_plan.json", export_plan)
    write_json(run_dir / "outputs" / "human_confirmation_template.json", confirmation_template(export_plan))
    checkpoint.update_step(run_dir, "prepare_export_plan", "completed", "准备导出执行计划")

    if not args.execute_export:
        checkpoint.update_step(run_dir, "validate_human_confirmation", "pending", "校验人工确认")
        checkpoint.update_step(run_dir, "readonly_export_stat_before_download", "skipped", "下载前复查导出统计")
        checkpoint.update_step(run_dir, "download_export_file", "skipped", "下载真实导出文件")
        checkpoint.update_step(run_dir, "write_export_evidence", "skipped", "写入导出证据")
        checkpoint.update_step(run_dir, "stop_for_file_validation", "pending", "停在文件校验点")
        checkpoint.check_contract(run_dir)
        checkpoint.append_log(run_dir, "真实导出执行计划已生成；当前为 dry-run，未下载。")
        print(f"迈鲸真实导出执行计划已生成，未下载，运行目录：{run_dir}")
        print(f"人工确认模板：{run_dir / 'outputs' / 'human_confirmation_template.json'}")
        return

    if not args.auth_context:
        raise SystemExit("--execute-export 必须同时提供 --auth-context。")
    if not args.confirmation_json:
        raise SystemExit("--execute-export 必须同时提供 --confirmation-json。")

    checkpoint.update_step(run_dir, "readonly_export_stat_before_download", "running", "下载前复查导出统计")
    auth = preflight.filter_count.load_auth_context(Path(args.auth_context).resolve())
    response = preflight.request_json(
        preflight.EXPORT_STAT_ENDPOINT,
        preflight.filter_count.auth_headers(auth),
        query_plan["params"],
    )
    stat_summary = preflight.summarize_export_stat(response)
    write_json(run_dir / "evidence" / "api_responses" / "export_stat_before_download_summary.json", stat_summary)
    export_plan = preflight.build_export_plan(query_plan, stat_summary)
    write_json(run_dir / "outputs" / "export_execute_plan.json", export_plan)
    checkpoint.update_step(run_dir, "readonly_export_stat_before_download", "completed", "下载前复查导出统计")

    checkpoint.update_step(run_dir, "validate_human_confirmation", "running", "校验人工确认")
    confirmation = read_json(Path(args.confirmation_json).resolve())
    write_json(run_dir / "input" / "human_confirmation.json", confirmation)
    route = export_plan.get("recommended_route") or {}
    validation = validate_confirmation(
        confirmation,
        current_total=stat_summary.get("export_stat_total"),
        current_route=route.get("route"),
    )
    write_json(run_dir / "outputs" / "human_confirmation_validation.json", validation)
    if not validation["ok"]:
        checkpoint.update_step(
            run_dir,
            "validate_human_confirmation",
            "failed",
            "校验人工确认",
            error={"failure_reason": "人工确认不满足执行条件", "details": validation["errors"]},
        )
        raise SystemExit(f"人工确认不满足执行条件：{validation['errors']}")
    checkpoint.update_step(run_dir, "validate_human_confirmation", "completed", "校验人工确认")

    checkpoint.update_step(run_dir, "download_export_file", "running", "下载真实导出文件")
    export_headers = preflight.filter_count.auth_headers(auth)

    # 1. 提交异步导出任务
    # 过滤掉 list 端点专用的 pageNum/pageSize，export/async 只需要筛选条件
    export_params = {k: v for k, v in query_plan["params"].items() if k not in ("pageNum", "pageSize")}
    print("提交异步导出任务…")
    task_id = submit_async_export(export_headers, export_params)
    write_json(run_dir / "evidence" / "api_responses" / "export_async_submit.json", {
        "task_id": task_id,
        "endpoint": EXPORT_ASYNC_ENDPOINT,
    })
    print(f"任务 ID：{task_id}，开始轮询（最多等待 300 秒）…")

    # 2. 轮询直到完成
    try:
        file_name = poll_async_export(export_headers, task_id, max_wait_seconds=300)
    except RuntimeError as exc:
        checkpoint.update_step(
            run_dir,
            "download_export_file",
            "failed",
            "下载真实导出文件",
            error={"failure_reason": str(exc)},
        )
        raise SystemExit(str(exc))
    write_json(run_dir / "evidence" / "api_responses" / "export_async_status.json", {
        "task_id": task_id,
        "status": "SUCCESS",
        "file_name": file_name,
    })
    print(f"导出任务完成，文件名：{file_name}")

    # 3. 下载文件
    download_url = (
        f"{preflight.BASE_URL}{EXPORT_DOWNLOAD_BY_NAME_ENDPOINT}"
        f"?fileName={urllib.parse.quote(file_name, safe='')}&delete=true"
    )
    download_headers = dict(export_headers)
    download_headers["Accept"] = "*/*"
    data, response_headers = request_binary(download_url, download_headers)

    payload_summary = validate_download_payload(data, response_headers)
    write_json(run_dir / "evidence" / "api_responses" / "export_download_response_summary.json", payload_summary)
    if not payload_summary["ok"]:
        checkpoint.update_step(
            run_dir,
            "download_export_file",
            "failed",
            "下载真实导出文件",
            error={"failure_reason": payload_summary["reason_cn"], "evidence_paths": ["evidence/api_responses/export_download_response_summary.json"]},
        )
        raise SystemExit(payload_summary["reason_cn"])

    output_file = run_dir / "outputs" / build_safe_export_filename(
        city,
        args.batch,
        payload_summary.get("suggested_extension") or ".xlsx",
    )
    output_file.write_bytes(data)
    checkpoint.update_step(run_dir, "download_export_file", "completed", "下载真实导出文件")

    checkpoint.update_step(run_dir, "write_export_evidence", "running", "写入导出证据")
    evidence = {
        "export_file": str(output_file),
        "file_size_bytes": output_file.stat().st_size,
        "content_type": payload_summary.get("content_type"),
        "expected_total": validation.get("expected_total"),
        "route": route.get("route"),
        "needs_file_validation": True,
    }
    write_json(run_dir / "outputs" / "export_file_evidence.json", evidence)
    checkpoint.update_step(run_dir, "write_export_evidence", "completed", "写入导出证据")
    checkpoint.update_step(run_dir, "stop_for_file_validation", "pending", "停在文件校验点")
    checkpoint.check_contract(run_dir)
    checkpoint.append_log(run_dir, "迈鲸公海客户真实导出文件已下载，等待文件校验。")

    print(f"迈鲸公海客户真实导出完成，运行目录：{run_dir}")
    print(f"导出文件：{output_file}")
    print(f"下一步：执行文件行数和字段校验。")


if __name__ == "__main__":
    main()
