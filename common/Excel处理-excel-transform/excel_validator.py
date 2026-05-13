#!/usr/bin/env python3
"""Excel/CSV 通用校验工具。

只使用 Python 标准库。支持 CSV 和常见 xlsx 首个工作表读取。
输出中文 validation_report.json，供人工复核和 workflow 状态判断。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from xml.etree import ElementTree as ET


NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%m月%d日", "%m.%d"]


def normalize_cell(value: Any) -> str:
    return "" if value is None else str(value).strip()


def read_csv(path: Path) -> List[List[str]]:
    for encoding in ["utf-8-sig", "utf-8", "gb18030"]:
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return [[normalize_cell(cell) for cell in row] for row in csv.reader(f)]
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别 CSV 编码，请转换为 UTF-8 或 GB18030。")


def column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - ord("A") + 1
    return value - 1


def read_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings = []
    for si in root.findall("a:si", NS):
        strings.append("".join(node.text or "" for node in si.findall(".//a:t", NS)))
    return strings


def first_sheet_path(zf: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    first_sheet = workbook.find("a:sheets/a:sheet", NS)
    if first_sheet is None:
        raise ValueError("xlsx 中没有工作表。")
    rel_id = first_sheet.attrib.get(f"{{{NS['r']}}}id")
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_ns = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
    for rel in rels.findall("rel:Relationship", rel_ns):
        if rel.attrib.get("Id") == rel_id:
            return "xl/" + rel.attrib["Target"].lstrip("/")
    raise ValueError("无法定位第一个工作表文件。")


def read_xlsx(path: Path) -> List[List[str]]:
    with zipfile.ZipFile(path) as zf:
        shared_strings = read_shared_strings(zf)
        root = ET.fromstring(zf.read(first_sheet_path(zf)))
    rows: List[List[str]] = []
    for row in root.findall(".//a:sheetData/a:row", NS):
        values: Dict[int, str] = {}
        for cell in row.findall("a:c", NS):
            ref = cell.attrib.get("r", "")
            idx = column_index(ref) if ref else len(values)
            cell_type = cell.attrib.get("t")
            raw = cell.find("a:v", NS)
            inline = cell.find("a:is/a:t", NS)
            if cell_type == "s" and raw is not None:
                shared_idx = int(raw.text or "0")
                value = shared_strings[shared_idx] if shared_idx < len(shared_strings) else ""
            elif inline is not None:
                value = inline.text or ""
            elif raw is not None:
                value = raw.text or ""
            else:
                value = ""
            values[idx] = normalize_cell(value)
        if values:
            rows.append([values.get(i, "") for i in range(max(values) + 1)])
    return rows


def read_table(path: Path) -> List[Dict[str, str]]:
    if path.suffix.lower() == ".csv":
        rows = read_csv(path)
    elif path.suffix.lower() == ".xlsx":
        rows = read_xlsx(path)
    else:
        raise ValueError(f"暂不支持文件类型：{path.suffix}")
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        return []
    headers = [normalize_cell(cell) for cell in rows[0]]
    records = []
    for raw_row in rows[1:]:
        padded = raw_row + [""] * max(0, len(headers) - len(raw_row))
        records.append({headers[i]: normalize_cell(padded[i]) for i in range(len(headers)) if headers[i]})
    return records


def parse_date(value: str, default_year: int | None = None) -> str | None:
    value = normalize_cell(value)
    if not value:
        return None
    value = re.sub(r"\s+\d{1,2}:\d{2}(:\d{2})?$", "", value)
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            if "%Y" not in fmt and default_year:
                dt = dt.replace(year=default_year)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def validate(records: List[Dict[str, str]], config: Dict[str, Any]) -> Dict[str, Any]:
    headers = list(records[0].keys()) if records else []
    errors = []
    warnings = []

    missing_columns = [name for name in config.get("required_columns", []) if name not in headers]
    if missing_columns:
        errors.append({"type": "missing_columns", "message_cn": f"缺少必要列：{', '.join(missing_columns)}"})

    row_count = len(records)
    min_rows = config.get("min_rows")
    max_rows = config.get("max_rows")
    if min_rows is not None and row_count < int(min_rows):
        errors.append({"type": "row_count_too_low", "message_cn": f"行数 {row_count} 小于最小要求 {min_rows}"})
    if max_rows is not None and row_count > int(max_rows):
        errors.append({"type": "row_count_too_high", "message_cn": f"行数 {row_count} 大于最大要求 {max_rows}"})

    date_issues = []
    date_column = config.get("date_column")
    allowed_dates = set(config.get("allowed_dates", []))
    if date_column:
        if date_column not in headers:
            errors.append({"type": "missing_date_column", "message_cn": f"缺少日期列：{date_column}"})
        else:
            for idx, row in enumerate(records, start=2):
                parsed = parse_date(row.get(date_column, ""), config.get("default_year"))
                if parsed is None:
                    date_issues.append({"row": idx, "value": row.get(date_column, ""), "reason_cn": "无法识别日期"})
                elif allowed_dates and parsed not in allowed_dates:
                    date_issues.append({"row": idx, "value": row.get(date_column, ""), "parsed": parsed, "reason_cn": "日期不在允许范围"})
            if date_issues:
                errors.append({"type": "date_issues", "message_cn": f"日期列存在 {len(date_issues)} 条异常"})

    empty_issues = []
    for col in config.get("non_empty_columns", []):
        if col not in headers:
            errors.append({"type": "missing_non_empty_column", "message_cn": f"缺少非空校验列：{col}"})
            continue
        empty_count = sum(1 for row in records if not row.get(col, ""))
        if empty_count:
            empty_issues.append({"column": col, "empty_count": empty_count})
    if empty_issues:
        warnings.append({"type": "empty_values", "message_cn": "存在空值列", "details": empty_issues})

    duplicate_issues = []
    for col in config.get("unique_columns", []):
        if col not in headers:
            errors.append({"type": "missing_unique_column", "message_cn": f"缺少去重列：{col}"})
            continue
        seen: Dict[str, int] = {}
        for idx, row in enumerate(records, start=2):
            value = row.get(col, "")
            if not value:
                continue
            if value in seen:
                duplicate_issues.append({"column": col, "first_row": seen[value], "row": idx, "value": value})
            else:
                seen[value] = idx
    if duplicate_issues:
        warnings.append({"type": "duplicate_values", "message_cn": f"存在 {len(duplicate_issues)} 个重复值"})

    return {
        "ok": not errors,
        "row_count": row_count,
        "columns": headers,
        "errors": errors,
        "warnings": warnings,
        "details": {
            "date_issues": date_issues[:100],
            "duplicate_issues": duplicate_issues[:100],
        },
        "needs_human_review": bool(errors or warnings),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="校验 CSV/XLSX 文件。")
    parser.add_argument("--file", required=True, help="待校验文件。")
    parser.add_argument("--config", help="校验配置 JSON。")
    parser.add_argument("--out", help="输出 validation_report.json。")
    args = parser.parse_args()

    source = Path(args.file).resolve()
    config = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else {}
    report = validate(read_table(source), config)
    report["source_file"] = str(source)
    report["config"] = config
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
