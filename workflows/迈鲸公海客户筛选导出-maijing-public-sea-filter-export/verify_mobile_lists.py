#!/usr/bin/env python3
"""批量重跑 mobile_list 检查脚本。

检查指定日期、批次、品类的 mobile_list_{品类}.json 是否存在、非空、含 poi_code。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CN_TZ = timezone(timedelta(hours=8))


def today_str() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def mobile_list_path(base_dir: Path, run_date: str, category: str, batch: str) -> Path:
    return (
        base_dir
        / "runs"
        / run_date
        / f"maijing-fetch-phone-by-id-{category}-{batch}"
        / "outputs"
        / f"mobile_list_{category}.json"
    )


def check_one(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "reason": "文件缺失", "count": 0, "path": str(path)}
    try:
        data = load_json(path)
    except json.JSONDecodeError:
        return {"ok": False, "reason": "JSON 无法解析", "count": 0, "path": str(path)}
    phone_list = data.get("phone_list")
    if not isinstance(phone_list, list) or not phone_list:
        return {"ok": False, "reason": "phone_list 为空", "count": 0, "path": str(path)}
    missing_poi = [
        idx for idx, item in enumerate(phone_list, start=1)
        if not isinstance(item, dict) or not str(item.get("poi_code", "")).strip()
    ]
    if missing_poi:
        return {
            "ok": False,
            "reason": f"poi_code 缺失 {len(missing_poi)}/{len(phone_list)} 条",
            "count": len(phone_list),
            "path": str(path),
        }
    return {"ok": True, "reason": "通过", "count": len(phone_list), "path": str(path)}


def print_next_commands(run_date: str, batch: str, categories: list[str]) -> None:
    print("\n下一步可运行 import dry-run：")
    for category in categories:
        print(
            "python3 workflows/迈鲸商机导入-maijing-lead-import/import_leads_dry_run.py "
            f"--mobile-list runs/{run_date}/maijing-fetch-phone-by-id-{category}-{batch}/outputs/mobile_list_{category}.json "
            f"--category {category} --batch {batch}"
        )


def print_rerun_hint(run_date: str, batch: str, categories: list[str]) -> None:
    print("\n存在失败项。可重跑手机号批量生成：")
    print(
        "python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/batch_regen_phones.py "
        f"--run-date {run_date} --batch {batch} --categories {' '.join(categories)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="检查各品类 mobile_list 是否可用于迈鲸商机导入。")
    parser.add_argument("--run-date", default=today_str(), help="运行日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--batch", default="002", help="批次号，默认 002")
    parser.add_argument("--categories", nargs="+", default=["餐饮", "休闲娱乐"], help="品类列表")
    parser.add_argument("--base-dir", default=str(ROOT), help="skills 根目录")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    results = []
    for category in args.categories:
        path = mobile_list_path(base_dir, args.run_date, category, args.batch)
        result = check_one(path)
        result["category"] = category
        results.append(result)
        if result["ok"]:
            print(f"✅ {category}: 存在（{result['count']} 条，poi_code 已填充）")
        else:
            print(f"❌ {category}: {result['reason']} - {result['path']}")

    if all(item["ok"] for item in results):
        print_next_commands(args.run_date, args.batch, args.categories)
        raise SystemExit(0)
    print_rerun_hint(args.run_date, args.batch, args.categories)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
