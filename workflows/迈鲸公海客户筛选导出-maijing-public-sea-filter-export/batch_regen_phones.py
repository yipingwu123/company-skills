#!/usr/bin/env python3
"""批量重新拉取各品类明文手机号（带 poi_code）。

当 mobile_list 缺少 poi_code 时，用此脚本对所有品类重跑 fetch_phone_by_id.py。

用法：
    python3 batch_regen_phones.py \\
        --split-dir runs/2026-05-13/maijing-public-sea-export-execute-长沙市-002/outputs/split \\
        --auth-context runs/2026-05-13/.../maijing_auth_context.json \\
        --batch 002

脚本会发现 split-dir 中所有 category_*.xlsx，按顺序为每个品类调用
fetch_phone_by_id.py，新批次写入独立的 run_dir，不影响旧数据。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FETCH_SCRIPT = Path(__file__).parent / "fetch_phone_by_id.py"


def discover_categories(split_dir: Path) -> list[tuple[str, Path]]:
    """返回 [(category_name, xlsx_path), ...] 按文件名排序。"""
    results = []
    for xlsx in sorted(split_dir.glob("category_*.xlsx")):
        name = xlsx.stem  # "category_餐饮"
        category = re.sub(r"^category_", "", name)
        if category:
            results.append((category, xlsx))
    return results


def run_fetch(
    category: str,
    split_file: Path,
    auth_context: Path,
    batch: str,
    base_dir: Path,
    interval: float,
) -> bool:
    """调用 fetch_phone_by_id.py，返回 True=成功。"""
    cmd = [
        sys.executable,
        str(FETCH_SCRIPT),
        "--split-file", str(split_file),
        "--auth-context", str(auth_context),
        "--category", category,
        "--batch", batch,
        "--base-dir", str(base_dir),
        "--interval", str(interval),
    ]
    print(f"\n{'─'*60}")
    print(f"品类：{category}  批次：{batch}")
    print(f"命令：{' '.join(cmd)}")
    print(f"{'─'*60}")
    result = subprocess.run(cmd)
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="批量重跑所有品类的手机号拉取。")
    parser.add_argument(
        "--split-dir",
        required=True,
        help="包含 category_*.xlsx 的目录（maijing-public-sea-export-execute 输出）",
    )
    parser.add_argument(
        "--auth-context",
        required=True,
        help="maijing_auth_context.json 路径（需要有效 session）",
    )
    parser.add_argument(
        "--categories",
        nargs="*",
        help="指定要处理的品类（默认：split-dir 中所有品类）",
    )
    parser.add_argument(
        "--batch",
        default="002",
        help="新批次号（默认 002，避免与旧 001 冲突）",
    )
    parser.add_argument(
        "--base-dir",
        default=str(ROOT),
        help="runs 根目录（默认项目根目录）",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.15,
        help="每次 API 请求间隔秒数（默认 0.15）",
    )
    args = parser.parse_args()

    split_dir = Path(args.split_dir).resolve()
    if not split_dir.is_dir():
        raise SystemExit(f"split-dir 不存在或不是目录：{split_dir}")

    auth_context = Path(args.auth_context).resolve()
    if not auth_context.exists():
        raise SystemExit(f"auth-context 文件不存在：{auth_context}")

    all_categories = discover_categories(split_dir)
    if not all_categories:
        raise SystemExit(f"在 {split_dir} 中未找到 category_*.xlsx 文件。")

    # 过滤品类
    if args.categories:
        requested = set(args.categories)
        all_categories = [(c, p) for c, p in all_categories if c in requested]
        if not all_categories:
            raise SystemExit(f"指定的品类 {requested} 在 split-dir 中不存在。")

    print(f"\n批量手机号重拉任务")
    print(f"split-dir：{split_dir}")
    print(f"auth-context：{auth_context}")
    print(f"批次：{args.batch}")
    print(f"品类（共 {len(all_categories)} 个）：{[c for c, _ in all_categories]}")

    base_dir = Path(args.base_dir).resolve()
    successes = []
    failures = []

    for category, xlsx_path in all_categories:
        ok = run_fetch(
            category=category,
            split_file=xlsx_path,
            auth_context=auth_context,
            batch=args.batch,
            base_dir=base_dir,
            interval=args.interval,
        )
        if ok:
            successes.append(category)
        else:
            failures.append(category)

    print(f"\n{'='*60}")
    print(f"批量拉取完成")
    print(f"  成功：{successes}")
    print(f"  失败：{failures}")
    if failures:
        print(f"\n⚠️  {len(failures)} 个品类失败，请检查日志后单独重跑。")
        sys.exit(1)
    else:
        print(f"\n✅ 全部成功。mobile_list 已写入各自的 run_dir/outputs/mobile_list_*.json")
        print(f"\n下一步：")
        print(f"  python3 workflows/迈鲸商机导入-maijing-lead-import/import_leads_dry_run.py \\")
        print(f"    --mobile-list runs/YYYY-MM-DD/maijing-fetch-phone-by-id-餐饮-{args.batch}/outputs/mobile_list_餐饮.json \\")
        print(f"    --category 餐饮 \\")
        print(f"    --customer-source AI外呼 \\")
        print(f"    --batch {args.batch}")


if __name__ == "__main__":
    main()
