#!/usr/bin/env python3
"""将 7天防重失败的 POI 关联回完整手机号，生成重试名单。

从 import_history.json 提取"7天内有大象跟进记录"的 POI，
关联 leads_for_import_{category}.json 中的手机号/门店信息，
输出格式与 mobile_list 完全相同，可直接传给 import_leads_dry_run.py --mobile-list。

用法：
    python3 schedule_retry.py \\
        --history-json runs/2026-05-14/maijing-lead-import-餐饮-001/outputs/import_history.json \\
        --leads-json runs/2026-05-14/volcengine-parse-result-餐饮-001/outputs/leads_for_import_餐饮.json \\
        --category 餐饮 \\
        --import-date 2026-05-14
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_fail_reason(raw: str | list) -> list[dict]:
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
    parser = argparse.ArgumentParser(description="生成 7天防重失败的重试商机名单。")
    parser.add_argument("--history-json", required=True,
                        help="import_history.json 路径（import_leads_dry_run.py 输出）")
    parser.add_argument("--leads-json", required=True,
                        help="leads_for_import_{category}.json 路径（含 poi_code 的完整名单）")
    parser.add_argument("--category", required=True, help="品类名称")
    parser.add_argument("--import-date", default=None,
                        help="导入发生日期 YYYY-MM-DD（默认今天）")
    parser.add_argument("--batch", default="001", help="批次号（默认 001）")
    parser.add_argument("--base-dir", default=None,
                        help="runs 根目录（默认 <项目根>/runs）")
    args = parser.parse_args()

    if args.import_date is None:
        args.import_date = datetime.date.today().isoformat()

    import_date = datetime.date.fromisoformat(args.import_date)
    retry_date = import_date + datetime.timedelta(days=7)
    retry_date_str = retry_date.isoformat()
    retry_date_compact = retry_date.strftime("%Y%m%d")

    # 加载导入历史
    history_path = Path(args.history_json).resolve()
    if not history_path.exists():
        raise SystemExit(f"❌ 文件不存在：{history_path}")
    history = load_json(history_path)

    # 提取 7天防重失败的 POI
    failures = parse_fail_reason(history.get("failReason", ""))
    retryable_pois = {
        item["poi"]
        for item in failures
        if "7天" in item.get("reason", "") and item.get("poi")
    }

    if not retryable_pois:
        print("✅ 无「7天防重」失败记录，无需生成重试名单。")
        sys.exit(0)

    # 加载完整名单，按 poi_code 建索引
    leads_path = Path(args.leads_json).resolve()
    if not leads_path.exists():
        raise SystemExit(f"❌ 文件不存在：{leads_path}")
    leads_data = load_json(leads_path)
    poi_index: dict[str, dict] = {
        r.get("poi_code", ""): r
        for r in leads_data.get("phone_list", [])
        if r.get("poi_code")
    }

    # 匹配
    retry_phone_list = [poi_index[poi] for poi in retryable_pois if poi in poi_index]
    unmatched = retryable_pois - set(poi_index.keys())

    if unmatched:
        print(f"⚠️  {len(unmatched)} 个 POI 在 leads_json 中未找到：{list(unmatched)[:5]}")

    # 构建输出
    base_dir = Path(args.base_dir) if args.base_dir else ROOT / "runs"
    out_dir = base_dir / args.import_date / f"maijing-lead-import-{args.category}-retry-{retry_date_compact}" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"retry_leads_{args.category}.json"
    out_data = {
        "category": args.category,
        "source": "retry_after_7day_block",
        "original_import_date": args.import_date,
        "retry_date": retry_date_str,
        "retry_count": len(retry_phone_list),
        "phone_list": retry_phone_list,
    }
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")

    mobile_list_rel = out_path.relative_to(ROOT) if out_path.is_relative_to(ROOT) else out_path

    print(f"\n重试名单生成完成")
    print(f"{'═' * 50}")
    print(f"导入日期：{args.import_date}")
    print(f"重试日期：{retry_date_str}（7天后）")
    print(f"品类    ：{args.category}")
    print(f"重试条数：{len(retry_phone_list)}")
    if unmatched:
        print(f"未匹配  ：{len(unmatched)} 个 POI（leads_json 中缺失）")
    print(f"输出文件：{mobile_list_rel}")
    print(f"\n执行命令（{retry_date_str} 重新导入）：")
    print(f"  python3 workflows/迈鲸商机导入-maijing-lead-import/import_leads_dry_run.py \\")
    print(f"    --mobile-list {mobile_list_rel} \\")
    print(f"    --category {args.category} \\")
    print(f"    --customer-source AI外呼 \\")
    print(f"    --batch {args.batch}")


if __name__ == "__main__":
    main()
