#!/usr/bin/env python3
"""生成火山外呼结果测试 CSV。

用途：在真实任务完成前，用 mobile_list 中的号码生成一份仿真结果 CSV，
供测试 parse_result_to_leads.py 的逻辑是否正确。

生成的 CSV 列名和状态值参照火山引擎外呼系统常见格式（从界面截图和行业惯例推断）。
真实 CSV 列名不同时，parse_result_to_leads.py 会打印所有列名并报错，根据实际列名
再来调整映射。

用法：
    python3 create_test_result_csv.py \\
        --mobile-list runs/2026-05-13/maijing-fetch-phone-by-id-餐饮-001/outputs/mobile_list_餐饮.json \\
        --out /tmp/test_result_餐饮.csv \\
        --answer-rate 0.45 \\
        --seed 42
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path


# 火山外呼结果 CSV 列名（推断，真实名称以实际 CSV 为准）
COLUMNS = [
    "被叫号码",         # 客户手机号
    "任务名称",         # 外呼任务名称
    "通话状态",         # 接通/未接/空号/关机/停机 等
    "接通时长(秒)",     # 通话秒数（未接通为 0）
    "开始时间",         # 呼叫发起时间
    "结束时间",         # 通话结束时间
    "意向等级",         # 有意向/无意向/未知 等（AI 判断）
    "话术名称",         # 使用的话术
]

# 通话状态枚举（接通 vs 未接通）
ANSWERED_STATUSES = ["接通"]
UNANSWERED_STATUSES = ["未接", "关机", "停机", "空号", "拒接"]
INTERESTED_STATUSES = ["有意向", "感兴趣"]
NOT_INTERESTED_STATUSES = ["无意向", "未知"]


def generate_rows(
    phones: list[str],
    task_name: str,
    script_name: str,
    answer_rate: float,
    interest_rate: float,
    rng: random.Random,
) -> list[dict[str, str]]:
    rows = []
    base_time = datetime(2026, 5, 14, 9, 0, 0)
    for i, phone in enumerate(phones):
        start = base_time + timedelta(seconds=i * 45 + rng.randint(0, 30))
        answered = rng.random() < answer_rate
        if answered:
            duration = rng.randint(30, 180)
            status = rng.choice(ANSWERED_STATUSES)
            end = start + timedelta(seconds=duration)
            interested = rng.random() < interest_rate
            intent = rng.choice(INTERESTED_STATUSES if interested else NOT_INTERESTED_STATUSES)
        else:
            duration = 0
            status = rng.choice(UNANSWERED_STATUSES)
            end = start + timedelta(seconds=rng.randint(5, 20))
            intent = "未知"

        rows.append({
            "被叫号码": phone,
            "任务名称": task_name,
            "通话状态": status,
            "接通时长(秒)": str(duration),
            "开始时间": start.strftime("%Y-%m-%d %H:%M:%S"),
            "结束时间": end.strftime("%Y-%m-%d %H:%M:%S"),
            "意向等级": intent,
            "话术名称": script_name,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="生成火山外呼结果仿真 CSV（用于测试）。")
    parser.add_argument("--mobile-list", required=True,
                        help="mobile_list_{品类}.json 路径")
    parser.add_argument("--out", required=True,
                        help="输出 CSV 路径（如 /tmp/test_result_餐饮.csv）")
    parser.add_argument("--answer-rate", type=float, default=0.45,
                        help="接通率（默认 0.45）")
    parser.add_argument("--interest-rate", type=float, default=0.20,
                        help="接通中有意向比例（默认 0.20）")
    parser.add_argument("--task-name", default="餐饮-2026-05-14-001",
                        help="任务名称（默认 餐饮-2026-05-14-001）")
    parser.add_argument("--script-name", default="餐饮",
                        help="话术名称（默认 餐饮）")
    parser.add_argument("--seed", type=int, default=42,
                        help="随机种子（默认 42，保证可重现）")
    args = parser.parse_args()

    mobile_data = json.loads(Path(args.mobile_list).read_text(encoding="utf-8"))
    phones = [r["Phone"] for r in mobile_data.get("phone_list", []) if r.get("Phone")]
    if not phones:
        raise SystemExit("mobile_list 中没有号码。")

    rng = random.Random(args.seed)
    rows = generate_rows(
        phones=phones,
        task_name=args.task_name,
        script_name=args.script_name,
        answer_rate=args.answer_rate,
        interest_rate=args.interest_rate,
        rng=rng,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    answered = sum(1 for r in rows if r["通话状态"] in ANSWERED_STATUSES)
    interested = sum(1 for r in rows if r["意向等级"] in INTERESTED_STATUSES)

    print(f"生成测试 CSV：{out_path}")
    print(f"  总数：{len(rows)}")
    print(f"  接通：{answered}（{answered/len(rows)*100:.1f}%）")
    print(f"  有意向：{interested}（{interested/len(rows)*100:.1f}%）")
    print(f"\n列名（供 parse_result_to_leads.py 参考）：")
    for col in COLUMNS:
        print(f"  {col}")
    print(f"\n⚠️  注意：列名是推断值，实际 CSV 列名以火山引擎下载文件为准。")
    print(f"若列名不符，parse_result_to_leads.py 会打印实际列名并报错，届时更新映射。")


if __name__ == "__main__":
    main()
