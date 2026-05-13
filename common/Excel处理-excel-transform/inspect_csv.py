#!/usr/bin/env python3
"""CSV 列结构快速分析工具。

当收到未知格式的 CSV（如火山外呼结果）时，用此工具快速了解：
- 列名列表
- 每列唯一值（上限 15 个）及其频率
- 哪列可能是手机号（11 位数字、首位 1）
- 哪列可能是通话状态（少量唯一值、含常见状态词）

用法：
    python3 inspect_csv.py 结果.csv
    python3 inspect_csv.py 结果.csv --encoding gbk
    python3 inspect_csv.py 结果.csv --top 5        # 只看每列前 5 个值
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


STATUS_HINTS = {"接通", "未接", "关机", "停机", "空号", "拒接", "接听", "无应答",
                "ANSWERED", "NO_ANSWER", "BUSY", "FAILED", "CANCEL"}
PHONE_LIKE_PREFIXES = {"1"}


def normalize_digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def is_mobile_like(value: str) -> bool:
    d = normalize_digits(value)
    return len(d) == 11 and d[0] == "1"


def guess_column_role(col_name: str, sample_values: list[str]) -> str:
    """猜测列的语义角色。"""
    col_lower = col_name.lower()
    non_empty = [v for v in sample_values if v.strip()]
    if not non_empty:
        return ""

    # 电话号码列
    mobile_count = sum(1 for v in non_empty if is_mobile_like(v))
    if mobile_count / len(non_empty) > 0.7:
        return "📱 可能是手机号列"

    # 状态列
    unique_vals = set(non_empty)
    status_match = unique_vals & STATUS_HINTS
    if status_match or any(h in col_name for h in ["状态", "status", "Status", "结果", "result"]):
        return f"📊 可能是状态列（值：{', '.join(sorted(unique_vals)[:8])}）"

    # 时间列
    time_like = sum(1 for v in non_empty if len(v) >= 10 and "-" in v and ":" in v)
    if time_like / len(non_empty) > 0.7:
        return "🕐 可能是时间列"

    # 数字列（时长等）
    digit_only = sum(1 for v in non_empty if v.strip().lstrip("-").isdigit())
    if digit_only / len(non_empty) > 0.8:
        return "🔢 纯数字列（时长/秒数/计数？）"

    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="CSV 列结构快速分析。")
    parser.add_argument("csv_file", help="要分析的 CSV 文件路径")
    parser.add_argument("--encoding", default="utf-8-sig",
                        help="文件编码（默认 utf-8-sig；如果乱码试 gbk）")
    parser.add_argument("--top", type=int, default=10,
                        help="每列显示最多多少个高频值（默认 10）")
    parser.add_argument("--sample", type=int, default=500,
                        help="读取前 N 行做分析（默认 500，0=全读）")
    args = parser.parse_args()

    path = Path(args.csv_file)
    if not path.exists():
        raise SystemExit(f"文件不存在：{path}")

    rows: list[dict[str, str]] = []
    with path.open("r", encoding=args.encoding, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for i, row in enumerate(reader):
            if args.sample and i >= args.sample:
                break
            rows.append(row)

    if not fieldnames:
        raise SystemExit("CSV 无列名（空文件或格式错误）。")

    print(f"\n文件：{path}")
    print(f"编码：{args.encoding}")
    print(f"行数（已读）：{len(rows)}")
    print(f"列数：{len(fieldnames)}")
    print(f"\n{'─'*70}")
    print("列名列表：")
    for i, col in enumerate(fieldnames):
        print(f"  [{i}] {col!r}")

    print(f"\n{'─'*70}")
    print("各列详情：\n")

    for col in fieldnames:
        vals = [r.get(col, "") for r in rows]
        non_empty = [v for v in vals if v.strip()]
        counter = Counter(vals)
        top_vals = counter.most_common(args.top)
        unique_count = len(counter)
        role = guess_column_role(col, non_empty)

        print(f"  列：{col!r}   唯一值：{unique_count}   非空：{len(non_empty)}/{len(vals)}")
        if role:
            print(f"       {role}")
        for val, cnt in top_vals:
            bar = "█" * min(int(cnt / len(vals) * 30), 30)
            pct = cnt / len(vals) * 100
            label = f"{val!r}" if val else "(空)"
            print(f"       {label:<25} {cnt:>5}  {pct:>5.1f}%  {bar}")
        print()

    # 总结：手机号列和状态列建议
    print(f"{'─'*70}")
    print("建议映射（供 parse_result_to_leads.py 使用）：\n")
    phone_col = None
    status_col = None
    for col in fieldnames:
        vals = [r.get(col, "") for r in rows]
        non_empty = [v for v in vals if v.strip()]
        if not non_empty:
            continue
        mobile_ratio = sum(1 for v in non_empty if is_mobile_like(v)) / len(non_empty)
        if mobile_ratio > 0.7 and phone_col is None:
            phone_col = col
        unique_set = set(non_empty)
        status_match = unique_set & STATUS_HINTS
        if (status_match or any(h in col for h in ["状态", "status", "Status", "结果"])):
            if status_col is None:
                status_col = col

    if phone_col:
        print(f"  手机号列：{phone_col!r}  → parse_result_to_leads.py 的 PHONE_COLS 第一项")
    else:
        print("  ⚠️  未找到手机号列，请手动确认列名")

    if status_col:
        vals = [r.get(status_col, "") for r in rows]
        unique_statuses = sorted(set(v for v in vals if v.strip()))
        print(f"  状态列  ：{status_col!r}  → parse_result_to_leads.py 的 STATUS_COLS 第一项")
        print(f"  状态值  ：{unique_statuses}")
        answered = [v for v in unique_statuses if v in STATUS_HINTS and v in {"接通", "已接", "ANSWERED"}]
        if answered:
            print(f"  接通值  ：{answered}  → ANSWERED_STATUS_VALUES")
        else:
            print(f"  ⚠️  未自动识别接通值，请从上面的状态值中手动选择接通的值")
    else:
        print("  ⚠️  未找到状态列，请手动确认列名")

    print(f"\n{'─'*70}")
    print("下一步：将上面的列名更新到 parse_result_to_leads.py 的 PHONE_COLS / STATUS_COLS 常量。")


if __name__ == "__main__":
    main()
