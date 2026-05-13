#!/usr/bin/env python3
"""接收 agent-browser eval 返回的火山外呼结果 JSON，存入 run_dir 并下载文件。

agent-browser eval 执行 browser_eval/export_and_download.js 后，
把返回的 JSON 粘贴到 --browser-result-json，本脚本完成后续：
  1. 保存 task_status.json
  2. 下载结果文件（通过 download_url）
  3. 解析 CSV 并写摘要

用法：
    python3 receive_browser_result.py \\
        --browser-result-json '{"task_id":"...","download_url":"...","answer_count":50,...}' \\
        --category 餐饮 \\
        --batch 001

或读取文件：
    python3 receive_browser_result.py \\
        --browser-result-file /tmp/browser_eval_result.json \\
        --category 餐饮 \\
        --batch 001
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


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
    checkpoint.StepDef("save_task_status", "保存任务状态"),
    checkpoint.StepDef("download_result", "下载结果文件"),
    checkpoint.StepDef("parse_result", "解析结果"),
    checkpoint.StepDef("write_summary", "写入摘要"),
]


def download_file(url: str, out_path: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return len(data)


def parse_result_csv(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "total_rows": 0}
    total = answered = converted = 0
    headers_seen: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers_seen = list(reader.fieldnames or [])
        for row in reader:
            total += 1
            row_text = json.dumps(row, ensure_ascii=False)
            if any(w in row_text for w in ["接通", "已接", "ANSWERED", "connected"]):
                answered += 1
            if any(w in row_text for w in ["有意向", "感兴趣", "回调", "转化"]):
                converted += 1
    return {
        "exists": True,
        "total_rows": total,
        "answered_count": answered,
        "not_answered_count": max(total - answered, 0),
        "converted_count": converted,
        "headers": headers_seen,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="接收 agent-browser 结果并下载文件。")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--browser-result-json", help="agent-browser eval 返回的 JSON 字符串")
    group.add_argument("--browser-result-file", help="agent-browser eval 返回的 JSON 文件路径")
    parser.add_argument("--category", required=True, help="品类名称")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--base-dir", default=str(ROOT))
    args = parser.parse_args()

    if args.browser_result_json:
        browser_result = json.loads(args.browser_result_json)
    else:
        browser_result = json.loads(Path(args.browser_result_file).read_text(encoding="utf-8"))

    required_keys = {"task_id", "download_url"}
    missing = required_keys - set(browser_result.keys())
    if missing:
        raise SystemExit(f"browser_result 缺少字段：{missing}")

    run_dir = checkpoint.ensure_run_dir(
        base_dir=Path(args.base_dir).resolve(),
        workflow_id="volcengine-call-result-export",
        workflow_name_cn="火山外呼结果导出",
        city=args.category,
        batch=args.batch,
        dry_run=False,
        steps=STEPS,
    )

    # 1. 保存任务状态
    checkpoint.update_step(run_dir, "save_task_status", "running", "保存任务状态")
    task_status = {
        "task_id": browser_result.get("task_id"),
        "status": browser_result.get("task_status"),
        "total_count": browser_result.get("total_count"),
        "answer_count": browser_result.get("answer_count"),
        "connected_count": browser_result.get("connected_count"),
        "export_id": browser_result.get("export_id"),
        "download_url": browser_result.get("download_url"),
    }
    checkpoint.write_json(run_dir / "outputs" / "task_status.json", task_status)
    checkpoint.write_json(run_dir / "evidence" / "api_responses" / "browser_result.json", {
        k: v for k, v in browser_result.items() if k != "download_url"
    })
    checkpoint.update_step(run_dir, "save_task_status", "completed",
                           f"任务状态已保存，接通：{browser_result.get('answer_count')}/{browser_result.get('total_count')}")

    # 2. 下载结果文件
    checkpoint.update_step(run_dir, "download_result", "running", "下载结果文件")
    safe_cat = "".join(c if (c.isalnum() or c in "-_") else "_" for c in args.category)
    result_path = run_dir / "outputs" / f"result_{safe_cat}.csv"
    download_url = browser_result["download_url"]
    try:
        size = download_file(download_url, result_path)
        checkpoint.update_step(run_dir, "download_result", "completed",
                               f"下载完成，{size} bytes → {result_path.name}")
    except Exception as exc:
        checkpoint.update_step(run_dir, "download_result", "failed", "下载结果文件",
                               {"failure_reason": str(exc), "download_url": download_url})
        raise

    # 3. 解析结果
    checkpoint.update_step(run_dir, "parse_result", "running", "解析结果")
    parse_summary = parse_result_csv(result_path)
    checkpoint.update_step(run_dir, "parse_result", "completed",
                           f"总行数 {parse_summary['total_rows']}，接通 {parse_summary['answered_count']}")

    # 4. 写摘要
    checkpoint.update_step(run_dir, "write_summary", "running", "写入摘要")
    summary = {
        "category": args.category,
        "task_id": browser_result.get("task_id"),
        "task_status": task_status,
        "parse_summary": parse_summary,
    }
    checkpoint.write_json(run_dir / "outputs" / "result_summary.json", summary)
    checkpoint.update_step(run_dir, "write_summary", "completed", "摘要已写入")
    checkpoint.append_log(run_dir, f"火山结果导出完成：{parse_summary['total_rows']} 行，接通 {parse_summary['answered_count']}。")

    print(f"\n✅ 处理完成")
    print(f"品类：{args.category}，任务ID：{browser_result.get('task_id')}")
    print(f"总数：{browser_result.get('total_count')}，接通：{browser_result.get('answer_count')}")
    print(f"结果文件：{result_path}")
    print(f"运行目录：{run_dir}")


if __name__ == "__main__":
    main()
