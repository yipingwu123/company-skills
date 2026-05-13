#!/usr/bin/env python3
"""解析迈鲸商机导入失败原因，生成可读报告。

import_leads_dry_run.py --execute-import 上传后，
/telesales/import/history 返回的 failReason 是 JSON 字符串数组：
  [{"poi":"1026210038729281","reason":"7天内有大象跟进记录","rowNum":77}, ...]

本脚本读取 import_history.json，打印：
  - 成功/失败/跳过数
  - 按失败原因分组统计
  - 可重试的 POI 清单（跨越防重窗口后可再导）

用法：
    python3 parse_import_failures.py \\
        --history-json runs/2026-05-14/maijing-lead-import-餐饮-001/outputs/import_history.json

    python3 parse_import_failures.py \\
        --history-json runs/.../import_history.json \\
        --leads-json runs/.../volcengine-parse-result-餐饮-001/outputs/leads_for_import_餐饮.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_fail_reason(raw: str | list) -> list[dict]:
    """failReason 可能是 JSON 字符串或已解析的 list。"""
    if isinstance(raw, list):
        return raw
    if not raw or raw in ("null", "[]", ""):
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description="解析迈鲸导入失败原因。")
    parser.add_argument("--history-json", required=True,
                        help="import_history.json 路径（import_leads_dry_run.py 输出）")
    parser.add_argument("--leads-json", default="",
                        help="leads_for_import_{品类}.json 路径（可选，用于关联失败记录的门店信息）")
    args = parser.parse_args()

    history_path = Path(args.history_json).resolve()
    if not history_path.exists():
        raise SystemExit(f"文件不存在：{history_path}")

    history = load_json(history_path)

    # 读取导入结果基础数字
    total = history.get("totalCount", "?")
    success = history.get("successCount", "?")
    fail = history.get("failCount", "?")
    status = history.get("importStatus", "?")
    file_name = history.get("fileName", "?")

    print(f"\n{'═'*55}")
    print(f"迈鲸导入结果分析")
    print(f"{'═'*55}")
    print(f"文件名    ：{file_name}")
    print(f"导入状态  ：{status}")
    print(f"总数      ：{total}")
    print(f"成功      ：{success}")
    print(f"失败      ：{fail}")

    fail_reason_raw = history.get("failReason", "")
    failures = parse_fail_reason(fail_reason_raw)

    if not failures:
        if fail in (0, "0"):
            print(f"\n✅ 全部成功，无失败记录。")
        else:
            print(f"\n⚠️  failReason 为空但 failCount={fail}，可能需要重新查询导入历史。")
        return

    # 按原因分组
    reason_groups: dict[str, list[dict]] = defaultdict(list)
    for item in failures:
        reason = item.get("reason", "未知原因")
        reason_groups[reason].append(item)

    print(f"\n{'─'*55}")
    print(f"失败原因统计（{len(failures)} 条失败）：")
    for reason, items in sorted(reason_groups.items(), key=lambda x: -len(x[1])):
        print(f"\n  [{len(items)} 条] {reason}")
        # 打印前 5 个 poi 示例
        for item in items[:5]:
            poi = item.get("poi", "?")
            row = item.get("rowNum", "?")
            print(f"    行 {row}：POI={poi}")
        if len(items) > 5:
            print(f"    ... 还有 {len(items)-5} 条")

    # 关联门店名称（如果提供了 leads-json）
    if args.leads_json:
        leads_path = Path(args.leads_json).resolve()
        if leads_path.exists():
            leads_data = load_json(leads_path)
            poi_to_store = {
                r.get("poi_code", ""): r.get("store_name", "")
                for r in leads_data.get("phone_list", [])
            }
            retryable = [
                f"  POI {item.get('poi')}（{poi_to_store.get(item.get('poi',''), '未知门店')}）"
                for item in failures
                if "7天" in item.get("reason", "")
            ]
            if retryable:
                print(f"\n{'─'*55}")
                print(f"7天防重限制（{len(retryable)} 条，7天后可重试）：")
                for line in retryable[:10]:
                    print(line)
                if len(retryable) > 10:
                    print(f"  ... 还有 {len(retryable)-10} 条")

    # 真正无法导入的（非防重原因）
    hard_failures = [f for f in failures if "7天" not in f.get("reason", "")]
    if hard_failures:
        print(f"\n{'─'*55}")
        print(f"⚠️  硬性失败（{len(hard_failures)} 条，需人工处理）：")
        for item in hard_failures[:10]:
            print(f"  行 {item.get('rowNum')}：POI={item.get('poi')}，原因={item.get('reason')}")

    print(f"\n{'═'*55}")
    retryable_count = sum(1 for f in failures if "7天" in f.get("reason", ""))
    hard_count = len(failures) - retryable_count
    print(f"汇总：成功 {success}，7天防重 {retryable_count} 条，硬性失败 {hard_count} 条")


if __name__ == "__main__":
    main()
