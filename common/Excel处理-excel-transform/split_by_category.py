#!/usr/bin/env python3
"""按一级品类拆分迈鲸导出 xlsx。

只使用 Python 标准库。策略：
- 读取原始 xlsx 的 sheetData XML
- 按指定列的值分组，每组生成一个独立 xlsx
- 保留原始 zip 中除 sheet1.xml 之外的所有文件（样式、sharedStrings 等不变）

用法（dry-run，只打印分组摘要，不写文件）：
    python3 split_by_category.py \\
        --file runs/.../maijing_public_sea_customers_长沙市_002.xlsx \\
        --split-col 一级品类 \\
        --out-dir runs/.../outputs/split

用法（真实拆分）：
    python3 split_by_category.py \\
        --file runs/.../maijing_public_sea_customers_长沙市_002.xlsx \\
        --split-col 一级品类 \\
        --out-dir runs/.../outputs/split \\
        --execute
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_MAP = {"a": NS}
ET.register_namespace("", NS)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checkpoint = load_module(
    ROOT / "common" / "断点续跑-checkpoint-runner" / "checkpoint_runner.py",
    "checkpoint_runner",
)

STEPS = [
    checkpoint.StepDef("read_source", "读取源文件"),
    checkpoint.StepDef("group_by_category", "按品类分组"),
    checkpoint.StepDef("write_split_files", "写入拆分文件"),
    checkpoint.StepDef("write_split_summary", "写入拆分摘要"),
]


# ── xlsx 读取 ───────────────────────────────────────────────────────────────

def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for si in root.findall(f"{{{NS}}}si"):
        strings.append("".join(node.text or "" for node in si.findall(f".//{{{NS}}}t")))
    return strings


def column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - ord("A") + 1
    return value - 1


def first_sheet_path(zf: zipfile.ZipFile) -> str:
    ns_wb = {"a": NS, "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    first_sheet = workbook.find("a:sheets/a:sheet", ns_wb)
    if first_sheet is None:
        raise ValueError("xlsx 中没有工作表。")
    rel_id = first_sheet.attrib.get(f"{{{ns_wb['r']}}}id")
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_ns = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
    for rel in rels.findall("rel:Relationship", rel_ns):
        if rel.attrib.get("Id") == rel_id:
            return "xl/" + rel.attrib["Target"].lstrip("/")
    raise ValueError("无法定位第一个工作表文件。")


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    raw = cell.find(f"{{{NS}}}v")
    inline = cell.find(f"{{{NS}}}is/{{{NS}}}t")
    if cell_type == "s" and raw is not None:
        idx = int(raw.text or "0")
        return shared_strings[idx] if idx < len(shared_strings) else ""
    if inline is not None:
        return inline.text or ""
    if raw is not None:
        return raw.text or ""
    return ""


def read_rows_and_header(zf: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]) -> tuple[list[str], list[ET.Element]]:
    """返回 (header_values, data_row_elements)。header_values 是首行字符串列表。"""
    root = ET.fromstring(zf.read(sheet_path))
    sheet_data = root.find(f"{{{NS}}}sheetData")
    if sheet_data is None:
        return [], []

    all_rows = list(sheet_data)
    if not all_rows:
        return [], []

    # 首行作为 header
    header_row = all_rows[0]
    headers: list[str] = []
    header_cells = list(header_row.findall(f"{{{NS}}}c"))
    if header_cells:
        max_col = max(column_index(c.attrib.get("r", "A1")) for c in header_cells)
        col_vals: dict[int, str] = {}
        for c in header_cells:
            col_vals[column_index(c.attrib.get("r", "A1"))] = cell_value(c, shared_strings)
        headers = [col_vals.get(i, "") for i in range(max_col + 1)]

    return headers, all_rows[1:]


# ── xlsx 写入 ───────────────────────────────────────────────────────────────

def find_split_col_index(headers: list[str], split_col: str) -> int:
    for i, h in enumerate(headers):
        if h.strip() == split_col.strip():
            return i
    candidates = [h for h in headers if split_col in h]
    if candidates:
        for i, h in enumerate(headers):
            if h == candidates[0]:
                return i
    raise ValueError(f"未找到列 '{split_col}'。可用列：{headers}")


def group_data_rows(
    data_rows: list[ET.Element],
    split_col_idx: int,
    shared_strings: list[str],
) -> dict[str, list[ET.Element]]:
    """返回 {category_value: [row_element, ...]}。"""
    groups: dict[str, list[ET.Element]] = {}
    for row in data_rows:
        cells = {column_index(c.attrib.get("r", "A1")): c for c in row.findall(f"{{{NS}}}c")}
        cat_cell = cells.get(split_col_idx)
        cat_val = cell_value(cat_cell, shared_strings).strip() if cat_cell is not None else ""
        if not cat_val:
            cat_val = "未分类"
        groups.setdefault(cat_val, []).append(row)
    return groups


def build_sheet_xml(original_sheet_xml: bytes, keep_rows: list[ET.Element], header_row: ET.Element) -> bytes:
    """复制原始 sheet XML，仅替换 sheetData 中的行。"""
    root = ET.fromstring(original_sheet_xml)
    sheet_data = root.find(f"{{{NS}}}sheetData")
    if sheet_data is None:
        raise ValueError("sheet1.xml 缺少 sheetData 元素。")

    # 清空 sheetData，重新写入 header + 选中的行
    for child in list(sheet_data):
        sheet_data.remove(child)
    sheet_data.append(header_row)
    for row in keep_rows:
        sheet_data.append(row)

    # 序列化（保留命名空间前缀）
    ET.register_namespace("", NS)
    buf = io.BytesIO()
    tree = ET.ElementTree(root)
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def write_category_xlsx(
    source_path: Path,
    out_path: Path,
    sheet_path: str,
    original_sheet_xml: bytes,
    header_row: ET.Element,
    keep_rows: list[ET.Element],
) -> None:
    new_sheet_xml = build_sheet_xml(original_sheet_xml, keep_rows, header_row)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_path, "r") as src_zf:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as dst_zf:
            for item in src_zf.infolist():
                if item.filename == sheet_path:
                    dst_zf.writestr(item, new_sheet_xml)
                else:
                    dst_zf.writestr(item, src_zf.read(item.filename))


# ── 主逻辑 ──────────────────────────────────────────────────────────────────

def safe_filename(s: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in s)


def main() -> None:
    parser = argparse.ArgumentParser(description="按品类拆分迈鲸导出 xlsx。")
    parser.add_argument("--file", required=True, help="源 xlsx 文件路径")
    parser.add_argument("--split-col", default="一级品类", help="用于拆分的列名（默认：一级品类）")
    parser.add_argument("--out-dir", help="输出目录（默认：源文件同级 split/ 子目录）")
    parser.add_argument("--execute", action="store_true", help="真实写入拆分文件（默认 dry-run）")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--base-dir", default=str(ROOT))
    args = parser.parse_args()

    dry_run = not args.execute
    source_path = Path(args.file).resolve()
    if not source_path.exists():
        raise SystemExit(f"源文件不存在：{source_path}")

    out_dir = Path(args.out_dir).resolve() if args.out_dir else source_path.parent / "split"

    run_dir = checkpoint.ensure_run_dir(
        base_dir=Path(args.base_dir).resolve(),
        workflow_id="excel-split-by-category",
        workflow_name_cn="按品类拆分Excel",
        city=safe_filename(args.split_col),
        batch=args.batch,
        dry_run=dry_run,
        steps=STEPS,
    )

    try:
        # 1. 读取源文件
        checkpoint.update_step(run_dir, "read_source", "running", "读取源文件")
        with zipfile.ZipFile(source_path) as zf:
            shared_strings = read_shared_strings(zf)
            sheet_path = first_sheet_path(zf)
            original_sheet_xml = zf.read(sheet_path)
            headers, data_rows = read_rows_and_header(zf, sheet_path, shared_strings)

        if not headers:
            raise SystemExit("源文件没有 header 行。")

        root_for_header = ET.fromstring(original_sheet_xml)
        sd = root_for_header.find(f"{{{NS}}}sheetData")
        header_row_elem = list(sd)[0] if sd is not None and list(sd) else None
        if header_row_elem is None:
            raise SystemExit("无法提取 header 行元素。")

        checkpoint.update_step(run_dir, "read_source", "completed", f"读取源文件，共 {len(data_rows)} 数据行，{len(headers)} 列")

        # 2. 按品类分组
        checkpoint.update_step(run_dir, "group_by_category", "running", "按品类分组")
        try:
            split_col_idx = find_split_col_index(headers, args.split_col)
        except ValueError as exc:
            raise SystemExit(str(exc))

        groups = group_data_rows(data_rows, split_col_idx, shared_strings)
        group_summary = {cat: len(rows) for cat, rows in sorted(groups.items())}
        total_grouped = sum(group_summary.values())

        checkpoint.write_json(run_dir / "outputs" / "group_summary.json", {
            "source_file": str(source_path),
            "split_col": args.split_col,
            "split_col_index": split_col_idx,
            "total_data_rows": len(data_rows),
            "total_grouped": total_grouped,
            "groups": group_summary,
            "dry_run": dry_run,
        })
        checkpoint.update_step(run_dir, "group_by_category", "completed", f"分组完成，{len(groups)} 个品类")

        print(f"\n分组结果（共 {len(data_rows)} 行 → {len(groups)} 个品类）：")
        for cat, count in sorted(group_summary.items()):
            print(f"  {cat}: {count} 行")

        # 3. 写入拆分文件
        if dry_run:
            checkpoint.update_step(run_dir, "write_split_files", "skipped", "dry-run 跳过写文件")
            checkpoint.update_step(run_dir, "write_split_summary", "skipped", "dry-run 跳过")
            print(f"\ndry-run 完成。加 --execute 写入以下文件：")
            for cat in sorted(groups.keys()):
                fname = f"category_{safe_filename(cat)}.xlsx"
                print(f"  {out_dir / fname}")
            print(f"\n运行目录：{run_dir}")
            return

        checkpoint.update_step(run_dir, "write_split_files", "running", "写入拆分文件")
        written: list[dict[str, Any]] = []
        out_dir.mkdir(parents=True, exist_ok=True)

        for cat, rows in sorted(groups.items()):
            fname = f"category_{safe_filename(cat)}.xlsx"
            out_path = out_dir / fname
            write_category_xlsx(
                source_path=source_path,
                out_path=out_path,
                sheet_path=sheet_path,
                original_sheet_xml=original_sheet_xml,
                header_row=header_row_elem,
                keep_rows=rows,
            )
            written.append({
                "category": cat,
                "row_count": len(rows),
                "file": str(out_path),
                "file_size_bytes": out_path.stat().st_size,
            })
            print(f"  写入：{out_path}（{len(rows)} 行）")

        checkpoint.update_step(run_dir, "write_split_files", "completed", f"写入 {len(written)} 个文件")

        # 4. 写摘要
        checkpoint.update_step(run_dir, "write_split_summary", "running", "写入拆分摘要")
        checkpoint.write_json(run_dir / "outputs" / "split_result.json", {
            "source_file": str(source_path),
            "split_col": args.split_col,
            "out_dir": str(out_dir),
            "files": written,
            "total_rows_written": sum(w["row_count"] for w in written),
        })
        checkpoint.update_step(run_dir, "write_split_summary", "completed", "写入拆分摘要")

        checkpoint.append_log(run_dir, f"按品类拆分完成，写入 {len(written)} 个文件。")
        print(f"\n拆分完成，运行目录：{run_dir}")
        print(f"输出目录：{out_dir}")

    except Exception as exc:
        checkpoint.update_step(run_dir, "write_split_files", "failed", "写入拆分文件",
                                {"failure_reason": str(exc)})
        raise


if __name__ == "__main__":
    main()
