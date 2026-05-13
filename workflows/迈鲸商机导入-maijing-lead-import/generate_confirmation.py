#!/usr/bin/env python3
"""预填充 human_confirmation.json，减少手动编辑步骤。

从 dry-run 生成的 run_dir 中读取 xlsx，统计数据行数，
自动写入 input/human_confirmation.json（confirmed_by 留空待用户填写）。

用法：
    python3 generate_confirmation.py \\
        --run-dir runs/2026-05-14/maijing-lead-import-餐饮-001 \\
        --category 餐饮 \\
        --customer-source AI外呼

    # 若已知姓名，一步到位：
    python3 generate_confirmation.py \\
        --run-dir runs/2026-05-14/maijing-lead-import-餐饮-001 \\
        --category 餐饮 \\
        --customer-source AI外呼 \\
        --confirmed-by 张三
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def count_data_rows(xlsx_path: Path) -> int:
    """统计 xlsx sheet1 的数据行数（排除 header 行）。"""
    with zipfile.ZipFile(xlsx_path) as zf:
        sheet_xml = zf.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(sheet_xml)
    sheet_data = root.find(f".//{{{NS}}}sheetData")
    if sheet_data is None:
        return 0
    total_rows = len(list(sheet_data))
    return max(total_rows - 1, 0)  # 减去 header 行


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def infer_category(run_dir: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    state = load_json(run_dir / "state" / "run_state.json")
    run_id = state.get("run_id") or run_dir.name
    prefix = "maijing-lead-import-"
    if isinstance(run_id, str) and run_id.startswith(prefix):
        suffix = run_id[len(prefix):]
        parts = suffix.rsplit("-", 1)
        if parts and parts[0]:
            return parts[0]
    raise SystemExit("❌ 无法从 run_state.json 或目录名推断品类，请传入 --category。")


def infer_customer_source(run_dir: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    import_plan = load_json(run_dir / "outputs" / "import_plan.json")
    source = import_plan.get("customer_source")
    if source:
        return str(source)
    return "AI外呼"


def main() -> None:
    parser = argparse.ArgumentParser(description="预填充 human_confirmation.json（减少手动步骤）。")
    parser.add_argument("--run-dir", required=True,
                        help="maijing-lead-import-{category}-{batch} 的运行目录")
    parser.add_argument("--category", help="品类名称；省略时从 run_state.json 或目录名推断")
    parser.add_argument("--customer-source",
                        help="客户来源字段值；省略时从 outputs/import_plan.json 推断，默认 AI外呼")
    parser.add_argument("--confirmed-by", default="",
                        help="操作人姓名（默认留空，需手动填写）")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists():
        raise SystemExit(f"❌ 运行目录不存在：{run_dir}")
    category = infer_category(run_dir, args.category)
    customer_source = infer_customer_source(run_dir, args.customer_source)

    # 查找最新的 xlsx
    xlsx_files = sorted((run_dir / "outputs").glob("*.xlsx"))
    if not xlsx_files:
        raise SystemExit(
            f"❌ 未找到 xlsx，请先运行 dry-run：\n"
            f"  python3 workflows/迈鲸商机导入-maijing-lead-import/import_leads_dry_run.py "
            f"--mobile-list <...> --category {category} --batch <...>"
        )
    xlsx_path = xlsx_files[-1]

    # 统计行数
    try:
        row_count = count_data_rows(xlsx_path)
    except Exception as exc:
        raise SystemExit(f"❌ 读取 xlsx 失败：{exc}")

    # 写入 confirmation JSON
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    confirmation = {
        "approved": True,
        "category": category,
        "lead_count": row_count,
        "customer_source": customer_source,
        "confirmed_by": args.confirmed_by,
        "confirmed_at": now,
    }

    input_dir = run_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    conf_path = input_dir / "human_confirmation.json"
    conf_path.write_text(json.dumps(confirmation, ensure_ascii=False, indent=2), encoding="utf-8")

    # 确定批次（从 run_dir 名称解析最后一段）
    batch = run_dir.name.rsplit("-", 1)[-1]

    print(f"\n{'═' * 45}")
    print(f"人工确认 JSON 预填充")
    print(f"{'═' * 45}")
    print(f"xlsx 文件  ：{xlsx_path.name}")
    print(f"数据行数   ：{row_count}")
    print(f"写入路径   ：{conf_path}")
    print()

    if not args.confirmed_by:
        print(f'⚠️  请打开文件，将 "confirmed_by" 字段填写为操作人姓名，然后再执行真实导入。')
        print(f"\n    {conf_path}")
    else:
        print(f"✅ confirmed_by 已填写：{args.confirmed_by}")

    print(f"\n确认后的命令：")
    print(f"  python3 workflows/迈鲸商机导入-maijing-lead-import/import_leads_dry_run.py \\")
    print(f"    --mobile-list <leads_for_import 路径> \\")
    print(f"    --category {category} \\")
    print(f"    --customer-source {customer_source} \\")
    print(f"    --auth-context <auth_context 路径> \\")
    print(f"    --confirmation-json {conf_path} \\")
    print(f"    --execute-import \\")
    print(f"    --batch {batch}")


if __name__ == "__main__":
    main()
