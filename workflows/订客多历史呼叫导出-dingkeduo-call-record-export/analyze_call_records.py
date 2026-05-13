#!/usr/bin/env python3
"""订客多呼叫记录分析工具。

读取 dingkeduo_call_records_{date}.csv，生成多维度统计分析报告。
只使用 Python 标准库（csv、json、collections、datetime、pathlib、argparse）。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


CN_TZ = timezone(timedelta(hours=8))


# ──────────────────────────────────────────────────────────────────────────────
# CSV 读取
# ──────────────────────────────────────────────────────────────────────────────

def read_csv(path: Path) -> list[dict[str, str]]:
    """读 CSV，返回字典列表。encoding 优先 utf-8-sig 兼容 BOM。"""
    for encoding in ["utf-8-sig", "utf-8", "gb18030"]:
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                records = []
                for row in reader:
                    records.append({k: (v or "").strip() for k, v in row.items()})
            return records
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别 CSV 编码，请转换为 UTF-8 或 GB18030。")


# ──────────────────────────────────────────────────────────────────────────────
# 业务逻辑
# ──────────────────────────────────────────────────────────────────────────────

def safe_int(value: str | None) -> int:
    """容错：空字符串或 None 视为 0。"""
    try:
        return int(value or "0")
    except (ValueError, TypeError):
        return 0


def is_answered(row: dict[str, str]) -> bool:
    """判断该通话是否接通。"""
    billsec = safe_int(row.get("billsec"))
    if billsec > 0:
        return True
    disposition_name = str(row.get("disposition_name", ""))
    return any(kw in disposition_name for kw in ["接通", "已接", "ANSWERED", "接听"])


def extract_hour(calldate: str) -> str | None:
    """从 calldate 字符串中提取小时，格式 HH。"""
    calldate = calldate.strip()
    # 匹配 YYYY-MM-DD HH:MM:SS 或 YYYY/MM/DD HH:MM:SS
    m = re.search(r"\b(\d{2}):\d{2}(:\d{2})?", calldate)
    if m:
        return m.group(1)
    return None


def extract_date_from_filename(csv_path: Path) -> str | None:
    """从文件名中提取日期，匹配 YYYY-MM-DD 格式。"""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", csv_path.name)
    return m.group(1) if m else None


# ──────────────────────────────────────────────────────────────────────────────
# 分析
# ──────────────────────────────────────────────────────────────────────────────

def analyze(records: list[dict[str, str]], top: int) -> dict[str, Any]:
    """执行所有维度的统计分析，返回结构化结果字典。"""
    if not records:
        return {}

    all_fields = set(records[0].keys())

    # ── 总体概况 ──────────────────────────────────────────────────────────────
    total_calls = len(records)
    answered_list = [r for r in records if is_answered(r)]
    answered_calls = len(answered_list)
    unanswered_calls = total_calls - answered_calls
    answer_rate = answered_calls / total_calls if total_calls else 0.0

    durations = [safe_int(r.get("billsec")) for r in answered_list]
    avg_duration = sum(durations) / len(durations) if durations else 0.0
    max_duration = max(durations) if durations else 0

    result: dict[str, Any] = {
        "total_calls": total_calls,
        "answered_calls": answered_calls,
        "unanswered_calls": unanswered_calls,
        "answer_rate": round(answer_rate, 4),
        "avg_duration_sec": round(avg_duration, 2),
        "max_duration_sec": max_duration,
    }

    # ── 按呼叫结果分组 ────────────────────────────────────────────────────────
    field_disp = "disposition_name"
    if field_disp in all_fields:
        counter: dict[str, int] = defaultdict(int)
        for r in records:
            counter[r.get(field_disp, "") or "（空）"] += 1
        by_disposition = sorted(counter.items(), key=lambda x: -x[1])
        result["by_disposition"] = [
            {
                "disposition_name": name,
                "count": cnt,
                "ratio": round(cnt / total_calls, 4) if total_calls else 0.0,
            }
            for name, cnt in by_disposition
        ]
    else:
        print(f"⚠️ 字段 {field_disp} 不存在，跳过此维度")
        result["by_disposition"] = []

    # ── 按坐席分组 ────────────────────────────────────────────────────────────
    field_agent = "user_name"
    if field_agent in all_fields:
        agent_total: dict[str, int] = defaultdict(int)
        agent_answered: dict[str, int] = defaultdict(int)
        agent_durations: dict[str, list[int]] = defaultdict(list)
        for r in records:
            name = r.get(field_agent, "") or "（未知）"
            agent_total[name] += 1
            if is_answered(r):
                agent_answered[name] += 1
                agent_durations[name].append(safe_int(r.get("billsec")))
        by_agent_sorted = sorted(agent_total.items(), key=lambda x: -x[1])
        by_agent = []
        for agent_name, tot in by_agent_sorted[:top]:
            ans = agent_answered[agent_name]
            durs = agent_durations[agent_name]
            avg_dur = round(sum(durs) / len(durs), 2) if durs else 0.0
            by_agent.append(
                {
                    "user_name": agent_name,
                    "total": tot,
                    "answered": ans,
                    "answer_rate": round(ans / tot, 4) if tot else 0.0,
                    "avg_duration_sec": avg_dur,
                }
            )
        result["by_agent"] = by_agent
    else:
        print(f"⚠️ 字段 {field_agent} 不存在，跳过此维度")
        result["by_agent"] = []

    # ── 按小时分组 ────────────────────────────────────────────────────────────
    field_calldate = "calldate"
    if field_calldate in all_fields:
        hour_counter: dict[str, int] = defaultdict(int)
        for r in records:
            hour = extract_hour(r.get(field_calldate, ""))
            if hour is not None:
                hour_counter[hour] += 1
        by_hour = sorted(
            [{"hour": h, "count": c} for h, c in hour_counter.items()],
            key=lambda x: x["hour"],
        )
        result["by_hour"] = by_hour
    else:
        print(f"⚠️ 字段 {field_calldate} 不存在，跳过此维度")
        result["by_hour"] = []

    return result


# ──────────────────────────────────────────────────────────────────────────────
# 报告打印
# ──────────────────────────────────────────────────────────────────────────────

def _bar(label: str, count: int, ratio: float, width: int = 12) -> str:
    padded = label[:width].ljust(width)
    pct = f"{ratio * 100:.1f}%"
    return f"  {padded}  {count:>6} 条（{pct:>6}）"


def print_report(data: dict[str, Any], date: str, top: int) -> None:
    sep = "══════════════════════════════════════════"
    print(sep)
    print(f"订客多呼叫记录分析 - {date}")
    print(sep)

    # 总体概况
    total = data.get("total_calls", 0)
    answered = data.get("answered_calls", 0)
    unanswered = data.get("unanswered_calls", 0)
    answer_rate = data.get("answer_rate", 0.0)
    avg_dur = data.get("avg_duration_sec", 0.0)
    max_dur = data.get("max_duration_sec", 0)

    print("【总体概况】")
    print(f"  总呼叫数：{total}")
    print(f"  接通数  ：{answered}（{answer_rate * 100:.1f}%）")
    print(f"  未接数  ：{unanswered}")
    print(f"  平均时长：{avg_dur:.1f} 秒")
    print(f"  最长通话：{max_dur} 秒")
    print()

    # 呼叫结果分布
    by_disp = data.get("by_disposition", [])
    if by_disp:
        print("【呼叫结果分布】")
        for item in by_disp:
            print(_bar(item["disposition_name"], item["count"], item["ratio"]))
        print()

    # 坐席排名
    by_agent = data.get("by_agent", [])
    if by_agent:
        print(f"【坐席排名（Top {min(top, len(by_agent))}）】")
        for item in by_agent:
            name = item["user_name"][:8].ljust(8)
            tot = item["total"]
            ans = item["answered"]
            ar = item["answer_rate"] * 100
            avg_d = item["avg_duration_sec"]
            print(f"  {name}  {tot} 呼 / {ans} 接通（{ar:.1f}%）/ 均时 {avg_d:.0f}s")
        print()

    # 高峰时段
    by_hour = data.get("by_hour", [])
    if by_hour:
        print("【高峰时段】")
        for item in by_hour:
            print(f"  {item['hour']}时  {item['count']:>4} 呼")
        print()

    print(sep)


# ──────────────────────────────────────────────────────────────────────────────
# 主程序
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="订客多历史呼叫记录分析工具。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--csv-file", required=True, help="CSV 文件路径（必填）")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="输出目录（默认：CSV 文件所在目录）",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="目标日期 YYYY-MM-DD（默认从 CSV 文件名提取）",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="每个维度显示前 N 项（默认 10）",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv_file).resolve()

    # 处理空文件或不存在的文件
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        print("CSV 为空或不存在")
        return

    # 读 CSV
    try:
        records = read_csv(csv_path)
    except Exception as exc:
        print(f"读取 CSV 失败：{exc}", file=sys.stderr)
        sys.exit(1)

    if not records:
        print("CSV 为空或不存在")
        return

    # 确定日期
    date = args.date or extract_date_from_filename(csv_path)
    if not date:
        date = datetime.now(CN_TZ).strftime("%Y-%m-%d")

    # 输出目录
    out_dir = Path(args.out_dir).resolve() if args.out_dir else csv_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # 执行分析
    analysis = analyze(records, args.top)
    if not analysis:
        print("CSV 为空或不存在")
        return

    # 构造 JSON 输出
    generated_at = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    output: dict[str, Any] = {
        "date": date,
        "generated_at": generated_at,
        **analysis,
    }

    # 写 JSON 文件
    json_path = out_dir / f"call_analysis_{date}.json"
    json_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # 打印报告
    print_report(analysis, date, args.top)

    print(f"分析结果已写入：{json_path}")


if __name__ == "__main__":
    main()
