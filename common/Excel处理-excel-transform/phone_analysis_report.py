#!/usr/bin/env python3
"""电话号码类型分析工具。

读取一个或多个 phone_list_{品类}.json / mobile_list_{品类}.json，
统计移动号、固定电话、400/800 服务号和无效号码占比，判断是否建议外呼。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def classify_phone(raw: str) -> str:
    """
    返回: "mobile" | "landline" | "toll_free" | "invalid"
    """
    phone = raw.strip()
    # 去除常见分隔符后取纯数字
    digits = "".join(ch for ch in phone if ch.isdigit())

    # 移动号：11位纯数字，首位1
    if len(digits) == 11 and digits[0] == "1":
        return "mobile"

    # 400/800 服务号：400/4008/800开头，10-11位
    if digits.startswith(("400", "4008", "800")) and 10 <= len(digits) <= 11:
        return "toll_free"

    # 固定电话：0开头，去掉区号后剩7-8位
    # 区号长度：3位（如010）或4位（如0731），后跟7或8位号码
    if digits.startswith("0") and 10 <= len(digits) <= 12:
        return "landline"

    # 8位纯数字（无区号的本地号）也归为固定电话
    if len(digits) == 8:
        return "landline"

    return "invalid"


def safe_category_from_filename(path: Path) -> str:
    stem = path.stem
    for prefix in ["phone_list_", "mobile_list_"]:
        if stem.startswith(prefix):
            return stem[len(prefix):] or "未指定品类"
    return stem or "未指定品类"


def load_phone_list(path: Path) -> tuple[str, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    category = str(data.get("category") or safe_category_from_filename(path))
    phone_list = data.get("phone_list") or []
    if not isinstance(phone_list, list):
        raise ValueError(f"{path} 的 phone_list 不是数组。")
    return category, [item for item in phone_list if isinstance(item, dict)]


def phone_value(item: dict[str, Any]) -> str:
    for key in ["Phone", "phone", "手机号", "电话", "联系电话", "号码"]:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def analyze_category(category: str, rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    counts = {
        "mobile": 0,
        "landline": 0,
        "toll_free": 0,
        "invalid": 0,
    }
    for item in rows:
        counts[classify_phone(phone_value(item))] += 1
    total = sum(counts.values())
    mobile_ratio = counts["mobile"] / total if total else 0.0
    return {
        "category": category,
        "total": total,
        "mobile": counts["mobile"],
        "landline": counts["landline"],
        "toll_free": counts["toll_free"],
        "invalid": counts["invalid"],
        "mobile_ratio": round(mobile_ratio, 3),
        "recommended": mobile_ratio >= threshold,
    }


def merge_inputs(paths: list[Path]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        category, rows = load_phone_list(path)
        grouped.setdefault(category, []).extend(rows)
    return grouped


def print_table(categories: list[dict[str, Any]]) -> None:
    headers = ["品类", "总号码", "移动号", "固话", "400/800", "无效", "移动占比", "建议"]
    rows = []
    for item in categories:
        rows.append([
            item["category"],
            str(item["total"]),
            str(item["mobile"]),
            str(item["landline"]),
            str(item["toll_free"]),
            str(item["invalid"]),
            f"{item['mobile_ratio'] * 100:.1f}%",
            "可外呼" if item["recommended"] else "不建议",
        ])
    widths = []
    for index, header in enumerate(headers):
        widths.append(max(len(header), *(len(row[index]) for row in rows)) if rows else len(header))
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    for row in rows:
        print("  ".join(row[index].ljust(widths[index]) for index in range(len(headers))))


def write_report(out_dir: Path, batch: str, threshold: float, categories: list[dict[str, Any]]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "threshold": threshold,
        "categories": categories,
    }
    out_path = out_dir / f"phone_analysis_{batch}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="分析 phone_list JSON 中的电话号码类型。")
    parser.add_argument("--phone-list", action="append", required=True, help="phone_list JSON 路径，可重复传入")
    parser.add_argument("--threshold", type=float, default=0.10, help="移动号占比阈值，默认 0.10")
    parser.add_argument("--out-dir", default=".", help="输出目录，默认当前目录")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--base-dir", default=str(ROOT))
    args = parser.parse_args()

    paths = [Path(item).resolve() for item in args.phone_list]
    for path in paths:
        if not path.exists():
            raise SystemExit(f"phone_list 文件不存在：{path}")

    grouped = merge_inputs(paths)
    categories = [
        analyze_category(category, rows, args.threshold)
        for category, rows in sorted(grouped.items())
    ]
    print_table(categories)
    out_path = write_report(Path(args.out_dir).resolve(), args.batch, args.threshold, categories)
    print(f"\n分析报告：{out_path}")


if __name__ == "__main__":
    main()
