#!/usr/bin/env python3
"""火山结果 × mobile_list × 迈鲸导出 三表匹配，生成飞书推送用的线索清单。

用法：
    python3 match_by_phone.py \\
        --result-csv  runs/.../outputs/call_result.csv \\
        --mobile-list-json runs/.../outputs/mobile_list_丽人.json \\
        --maijing-xlsx runs/.../outputs/maijing_export.xlsx \\
        --category 丽人 \\
        --batch 001 \\
        --customer-source AI外呼

输出（runs/{today}/volcengine-result-feishu-match-{category}-{batch}/outputs/）：
    matched_leads_{category}_{date}.json   — 完整字段 JSON
    matched_leads_{category}_{date}.xlsx   — 迈鲸导入格式 19 列 xlsx
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from datetime import datetime, date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

# ── 常量 ──────────────────────────────────────────────────────────────────────

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
ET.register_namespace("", NS)

# 迈鲸导入模板列顺序（19 列）
TEMPLATE_COLUMNS = [
    "客户来源(跟进阶段)",
    "POI编码",
    "POI名称",
    "一级品类名",
    "二级品类名",
    "区域",
    "电话",
    "商圈",
    "跟进情况",
    "跟进人",
    "跟进时间",
    "备注",
    "跟进详情",
    "详细地址",
    "下发状态",
    "城市",
    "KPI线索类型",
    "统计日期",
    "客户意向等级",
]

# 火山 CSV：各字段可能的列名关键词（不区分大小写）
PHONE_KEYWORDS    = ["被叫号码", "手机号", "电话", "phone"]
STATUS_KEYWORDS   = ["通话状态", "呼叫状态", "disposition", "status"]
DURATION_KEYWORDS = ["通话时长", "billsec", "时长"]

# 迈鲸 xlsx：用于 poi_code 匹配的列名候选
POI_CODE_CANDIDATES = ["POI编码", "poi_code", "POI code"]

# 迈鲸 xlsx：需要读取的其他列（找到即用，找不到留空）
MAIJING_FIELD_COLS = [
    "客户标签", "意向等级", "跟进阶段", "一级品类名",
    "区域", "城市", "详细地址", "POI名称",
]


# ── xlsx 读取（stdlib only：zipfile + ET）──────────────────────────────────────

def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """读取 xl/sharedStrings.xml，返回字符串列表。"""
    try:
        xml = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(xml)
    return [
        "".join(t.text or "" for t in si.iter(f"{{{NS}}}t"))
        for si in root.findall(f".//{{{NS}}}si")
    ]


def cell_value(cell_el: ET.Element, shared_strings: list[str]) -> str:
    """从单元格元素提取字符串值（支持 shared string 和 inline 值）。"""
    t = cell_el.get("t", "")
    v_el = cell_el.find(f"{{{NS}}}v")
    if v_el is None:
        # 检查 inlineStr
        is_el = cell_el.find(f"{{{NS}}}is")
        if is_el is not None:
            return "".join(t_el.text or "" for t_el in is_el.iter(f"{{{NS}}}t"))
        return ""
    if t == "s":
        # shared string 索引
        try:
            return shared_strings[int(v_el.text or "0")]
        except (ValueError, IndexError):
            return v_el.text or ""
    return v_el.text or ""


def col_letter_to_index(col_str: str) -> int:
    """Excel 列字母（A、B、AA…）→ 0-based 整数。"""
    col_str = col_str.upper().strip()
    result = 0
    for ch in col_str:
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1


def parse_cell_ref(ref: str):
    """'AB12' → (col_index_0based, row_index_1based)。"""
    i = 0
    while i < len(ref) and ref[i].isalpha():
        i += 1
    col_str = ref[:i]
    row_str = ref[i:]
    return col_letter_to_index(col_str), int(row_str) if row_str else 0


def read_xlsx_sheet(zf: zipfile.ZipFile, shared_strings: list[str]) -> list[list[str]]:
    """读取 sheet1.xml，返回二维列表（行×列），缺失单元格填空字符串。"""
    try:
        xml = zf.read("xl/worksheets/sheet1.xml")
    except KeyError:
        raise RuntimeError("xlsx 中找不到 xl/worksheets/sheet1.xml")
    root = ET.fromstring(xml)
    sheet_data = root.find(f"{{{NS}}}sheetData")
    if sheet_data is None:
        return []

    rows: list[list[str]] = []
    for row_el in sheet_data.findall(f"{{{NS}}}row"):
        # 找出该行最大列索引，用于补齐空格
        cells = row_el.findall(f"{{{NS}}}c")
        if not cells:
            rows.append([])
            continue
        max_col = max(parse_cell_ref(c.get("r", "A1"))[0] for c in cells)
        row_data = [""] * (max_col + 1)
        for c_el in cells:
            ref = c_el.get("r", "")
            if not ref:
                continue
            col_idx, _ = parse_cell_ref(ref)
            row_data[col_idx] = cell_value(c_el, shared_strings)
        rows.append(row_data)
    return rows


# ── xlsx 写入（stdlib only：zipfile + ET）──────────────────────────────────────

def _col_letter(idx: int) -> str:
    """0-based 列索引 → Excel 列字母（A, B, …, Z, AA, …）。"""
    result = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        result = chr(65 + rem) + result
    return result


def build_output_xlsx(rows: list[dict[str, str]]) -> bytes:
    """将行列表写成最小有效 xlsx，使用 sharedStrings 去重。"""
    # 构建 shared strings 表（去重、保持插入顺序）
    ss_list: list[str] = []
    ss_index: dict[str, int] = {}

    def get_ss_idx(value: str) -> int:
        if value not in ss_index:
            ss_index[value] = len(ss_list)
            ss_list.append(value)
        return ss_index[value]

    # 预先收集 header + 数据行所有字符串
    all_strings: list[list[str]] = []
    header = TEMPLATE_COLUMNS
    all_strings.append(header)
    for row in rows:
        all_strings.append([row.get(col, "") for col in header])

    for row_vals in all_strings:
        for v in row_vals:
            get_ss_idx(v)

    # ── 构建 sheet1.xml ──
    ws_root = ET.Element(f"{{{NS}}}worksheet")
    sd = ET.SubElement(ws_root, f"{{{NS}}}sheetData")

    for row_idx, row_vals in enumerate(all_strings, 1):
        row_el = ET.SubElement(sd, f"{{{NS}}}row")
        row_el.set("r", str(row_idx))
        for col_idx, val in enumerate(row_vals):
            c_el = ET.SubElement(row_el, f"{{{NS}}}c")
            c_el.set("r", f"{_col_letter(col_idx)}{row_idx}")
            c_el.set("t", "s")  # shared string
            v_el = ET.SubElement(c_el, f"{{{NS}}}v")
            v_el.text = str(get_ss_idx(val))

    sheet_buf = io.BytesIO()
    ET.ElementTree(ws_root).write(sheet_buf, encoding="utf-8", xml_declaration=True)
    sheet_xml = sheet_buf.getvalue()

    # ── 构建 sharedStrings.xml ──
    ss_root = ET.Element(f"{{{NS}}}sst")
    ss_root.set("xmlns", NS)
    ss_root.set("count", str(len(ss_list)))
    ss_root.set("uniqueCount", str(len(ss_list)))
    for s in ss_list:
        si = ET.SubElement(ss_root, f"{{{NS}}}si")
        t = ET.SubElement(si, f"{{{NS}}}t")
        t.text = s
    ss_buf = io.BytesIO()
    ET.ElementTree(ss_root).write(ss_buf, encoding="utf-8", xml_declaration=True)
    ss_xml = ss_buf.getvalue()

    # ── 打包 xlsx ──
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml"'
            ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml"'
            ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml"'
            ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            '<Override PartName="/xl/styles.xml"'
            ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1"'
            ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
            ' Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1"'
            ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
            ' Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2"'
            ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"'
            ' Target="sharedStrings.xml"/>'
            '<Relationship Id="rId3"'
            ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"'
            ' Target="styles.xml"/>'
            "</Relationships>",
        )
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        zf.writestr("xl/sharedStrings.xml", ss_xml)
        # 最小 styles.xml（Excel 打开不报错）
        zf.writestr(
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<fonts><font/></fonts>"
            "<fills><fill/></fills>"
            "<borders><border/></borders>"
            "<cellStyleXfs><xf/></cellStyleXfs>"
            "<cellXfs><xf/></cellXfs>"
            "</styleSheet>",
        )
    return out.getvalue()


# ── Step 1：读取火山 CSV ───────────────────────────────────────────────────────

def _detect_col(headers: list[str], keywords: list[str]) -> int | None:
    """在 headers 中找第一个名称含任意关键词的列（不区分大小写），返回索引；找不到返回 None。"""
    lower_headers = [h.lower() for h in headers]
    for kw in keywords:
        kw_lower = kw.lower()
        for i, h in enumerate(lower_headers):
            if kw_lower in h:
                return i
    return None


def load_volcengine_csv(csv_path: Path) -> list[dict[str, str]]:
    """读取火山外呼结果 CSV，尝试逗号/Tab 分隔，过滤出已接通记录。"""
    raw = csv_path.read_bytes()
    # 尝试 UTF-8-BOM / UTF-8 / GBK
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        raise RuntimeError(f"无法解码 CSV 文件：{csv_path}")

    # 尝试逗号，再尝试 Tab
    answered: list[dict[str, str]] = []
    for delimiter in (",", "\t"):
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        try:
            rows = list(reader)
        except Exception:
            continue
        if not rows:
            continue
        headers = list(rows[0].keys())
        # 至少要有 2 列才算有效
        if len(headers) < 2:
            continue

        phone_col    = _detect_col(headers, PHONE_KEYWORDS)
        status_col   = _detect_col(headers, STATUS_KEYWORDS)
        duration_col = _detect_col(headers, DURATION_KEYWORDS)

        if phone_col is None:
            # 该分隔符解析结果不含电话列，换下一个
            continue

        phone_key    = headers[phone_col]
        status_key   = headers[status_col]   if status_col   is not None else None
        duration_key = headers[duration_col] if duration_col is not None else None

        print(f"[火山CSV] 分隔符='{delimiter}'，共 {len(rows)} 行")
        print(f"  电话列：{phone_key}")
        print(f"  状态列：{status_key or '未找到'}")
        print(f"  时长列：{duration_key or '未找到'}")

        # 过滤已接通
        for row in rows:
            phone = row.get(phone_key, "").strip()
            if not phone:
                continue
            status   = row.get(status_key, "").strip()   if status_key   else ""
            duration = row.get(duration_key, "").strip() if duration_key else ""

            is_answered = False
            if "接通" in status:
                is_answered = True
            else:
                try:
                    if float(duration) > 0:
                        is_answered = True
                except (ValueError, TypeError):
                    pass

            if is_answered:
                answered.append(dict(row))
                # 统一挂一个 "__phone__" 键方便后续使用
                answered[-1]["__phone__"] = phone

        return answered

    raise RuntimeError("无法解析火山 CSV：未能检测到电话列，请检查文件格式。")


# ── Step 2：构建 phone → poi 映射 ─────────────────────────────────────────────

def build_phone_to_poi(mobile_list: list[dict]) -> dict[str, dict]:
    """phone_to_poi[phone] = {"poi_code": ..., "store_name": ...}"""
    phone_to_poi: dict[str, dict] = {}
    for entry in mobile_list:
        phone = entry.get("Phone", "").strip()
        if phone:
            phone_to_poi[phone] = {
                "poi_code":   entry.get("poi_code",   ""),
                "store_name": entry.get("store_name", ""),
            }
    return phone_to_poi


# ── Step 3：读取迈鲸导出 xlsx ─────────────────────────────────────────────────

def load_maijing_xlsx(xlsx_path: Path) -> dict[str, dict]:
    """
    读取迈鲸导出 xlsx，返回 poi_to_maijing dict。
    key = POI编码，value = 该行所有字段。
    """
    with zipfile.ZipFile(xlsx_path, "r") as zf:
        shared_strings = read_shared_strings(zf)
        sheet_rows = read_xlsx_sheet(zf, shared_strings)

    if not sheet_rows:
        print("[迈鲸xlsx] 工作表为空，跳过。")
        return {}

    # 第一行为表头
    header = sheet_rows[0]
    print(f"[迈鲸xlsx] 共 {len(sheet_rows) - 1} 条数据行，列：{header}")

    # 找 POI编码 列索引
    poi_col_idx: int | None = None
    for candidate in POI_CODE_CANDIDATES:
        for i, h in enumerate(header):
            if h.strip() == candidate or candidate.lower() in h.lower():
                poi_col_idx = i
                break
        if poi_col_idx is not None:
            break

    if poi_col_idx is None:
        print(f"[迈鲸xlsx] 警告：未找到 POI编码 列（候选：{POI_CODE_CANDIDATES}），将无法关联迈鲸数据。")
        return {}

    print(f"  POI编码 列：索引={poi_col_idx}，列名='{header[poi_col_idx]}'")

    poi_to_maijing: dict[str, dict] = {}
    for row in sheet_rows[1:]:
        # 补齐行长度
        while len(row) <= poi_col_idx:
            row.append("")
        poi_code = row[poi_col_idx].strip()
        if not poi_code:
            continue
        row_dict: dict[str, str] = {}
        for col_idx, col_name in enumerate(header):
            row_dict[col_name] = row[col_idx] if col_idx < len(row) else ""
        poi_to_maijing[poi_code] = row_dict

    print(f"[迈鲸xlsx] 已索引 {len(poi_to_maijing)} 个 POI编码。")
    return poi_to_maijing


# ── Step 4 & 5：关联 + 构建输出 ───────────────────────────────────────────────

def normalize_phone(phone: str) -> str:
    """去除空格、去除前置 +86 或 86（11位手机号场景）。"""
    p = phone.strip()
    if p.startswith("+86"):
        p = p[3:]
    elif p.startswith("86") and len(p) == 13:
        p = p[2:]
    return p.strip()


def build_output_rows(
    answered: list[dict[str, str]],
    phone_to_poi: dict[str, dict],
    poi_to_maijing: dict[str, dict],
    customer_source: str,
    category: str,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """
    三表 JOIN，返回 (output_rows, stats)。
    output_rows 中每项 key 与 TEMPLATE_COLUMNS 对应，另加额外字段。
    """
    stats = {
        "total_answered": len(answered),
        "matched_mobile_list": 0,
        "matched_maijing": 0,
        "unmatched": 0,
    }

    output_rows: list[dict[str, str]] = []

    for call_row in answered:
        raw_phone = call_row.get("__phone__", "").strip()
        phone = normalize_phone(raw_phone)

        # 查 mobile_list
        poi_info = phone_to_poi.get(phone) or phone_to_poi.get(raw_phone)
        if poi_info:
            stats["matched_mobile_list"] += 1
            poi_code   = poi_info["poi_code"]
            store_name = poi_info["store_name"]
        else:
            stats["unmatched"] += 1
            poi_code   = ""
            store_name = ""

        # 查迈鲸
        maijing_row: dict[str, str] = {}
        if poi_code and poi_code in poi_to_maijing:
            maijing_row = poi_to_maijing[poi_code]
            stats["matched_maijing"] += 1

        # 构建迈鲸导入格式行（19 列）
        def mj(field: str) -> str:
            return maijing_row.get(field, "")

        out: dict[str, str] = {
            "客户来源(跟进阶段)": customer_source,
            "POI编码":          poi_code,
            "POI名称":          store_name or mj("POI名称"),
            "一级品类名":        mj("一级品类名") or category,
            "二级品类名":        mj("二级品类名") or mj("二级品类") or "",
            "区域":             mj("区域"),
            "电话":             phone,
            "商圈":             mj("商圈"),
            "跟进情况":          mj("跟进情况") or mj("客户标签") or "",
            "跟进人":            mj("跟进人"),
            "跟进时间":          mj("跟进时间"),
            "备注":             mj("备注"),
            "跟进详情":          mj("跟进详情"),
            "详细地址":          mj("详细地址"),
            "下发状态":          mj("下发状态"),
            "城市":             mj("城市"),
            "KPI线索类型":       mj("KPI线索类型"),
            "统计日期":          mj("统计日期"),
            "客户意向等级":       mj("意向等级") or mj("客户意向等级") or "",
        }

        # 额外保存原始火山字段（方便 JSON 调试）
        out["__raw_phone__"] = raw_phone
        for k, v in call_row.items():
            if k != "__phone__":
                out[f"__volcengine_{k}__"] = v

        output_rows.append(out)

    return output_rows, stats


# ── 主逻辑 ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="火山呼叫结果 × mobile_list × 迈鲸导出 三表匹配，生成飞书推送线索。"
    )
    parser.add_argument("--result-csv",        required=True,  help="火山外呼结果 CSV 路径")
    parser.add_argument("--mobile-list-json",  required=True,  help="mobile_list_{品类}.json 路径")
    parser.add_argument("--maijing-xlsx",      required=True,  help="迈鲸导出 xlsx 路径")
    parser.add_argument("--category",          required=True,  help="品类，如 丽人")
    parser.add_argument("--batch",             default="001",  help="批次号（默认 001）")
    parser.add_argument("--customer-source",   default="AI外呼", help="客户来源字段值（默认 AI外呼）")
    parser.add_argument(
        "--run-dir",
        default=None,
        help=(
            "输出根目录（默认 runs/{today}/volcengine-result-feishu-match-{category}-{batch}/）"
        ),
    )
    args = parser.parse_args()

    # ── 确定输出目录 ──
    today_str = date.today().strftime("%Y-%m-%d")
    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
    else:
        safe_cat = "".join(c if (c.isalnum() or c in "-_") else "_" for c in args.category)
        run_dir = (
            Path(__file__).resolve().parents[2]
            / "runs"
            / today_str
            / f"volcengine-result-feishu-match-{safe_cat}-{args.batch}"
        )
    outputs_dir = run_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    print(f"[初始化] 输出目录：{outputs_dir}")

    # ── Step 1：读取火山 CSV ──
    result_csv_path = Path(args.result_csv).resolve()
    if not result_csv_path.exists():
        raise SystemExit(f"[错误] 火山 CSV 不存在：{result_csv_path}")
    print(f"\n[Step 1] 读取火山 CSV：{result_csv_path}")
    answered = load_volcengine_csv(result_csv_path)
    print(f"  已接通记录：{len(answered)} 条")

    if not answered:
        print("[完成] 没有已接通记录，无需输出。")
        return

    # ── Step 2：构建 phone → poi 映射 ──
    mobile_list_path = Path(args.mobile_list_json).resolve()
    if not mobile_list_path.exists():
        raise SystemExit(f"[错误] mobile_list JSON 不存在：{mobile_list_path}")
    print(f"\n[Step 2] 读取 mobile_list JSON：{mobile_list_path}")
    raw_json = json.loads(mobile_list_path.read_text(encoding="utf-8"))
    # 支持顶层为 list 或 {"phone_list": [...]} 两种格式
    if isinstance(raw_json, list):
        mobile_list = raw_json
    else:
        mobile_list = raw_json.get("phone_list", raw_json.get("data", []))
    print(f"  共 {len(mobile_list)} 条 mobile_list 记录")
    phone_to_poi = build_phone_to_poi(mobile_list)
    print(f"  构建 phone→poi 映射：{len(phone_to_poi)} 条")

    # ── Step 3：读取迈鲸导出 xlsx ──
    maijing_xlsx_path = Path(args.maijing_xlsx).resolve()
    if not maijing_xlsx_path.exists():
        raise SystemExit(f"[错误] 迈鲸 xlsx 不存在：{maijing_xlsx_path}")
    print(f"\n[Step 3] 读取迈鲸导出 xlsx：{maijing_xlsx_path}")
    poi_to_maijing = load_maijing_xlsx(maijing_xlsx_path)

    # ── Step 4：三表 JOIN ──
    print(f"\n[Step 4] 执行三表匹配…")
    output_rows, stats = build_output_rows(
        answered, phone_to_poi, poi_to_maijing,
        args.customer_source, args.category,
    )

    # ── Step 5：写输出 ──
    date_str = today_str.replace("-", "")
    safe_cat = "".join(c if (c.isalnum() or c in "-_") else "_" for c in args.category)

    # 5a. JSON（含所有字段）
    json_out_path = outputs_dir / f"matched_leads_{safe_cat}_{date_str}.json"
    json_out_path.write_text(
        json.dumps(output_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[Step 5] 写 JSON：{json_out_path}")

    # 5b. xlsx（迈鲸导入格式，19 列）
    xlsx_rows = [{col: r.get(col, "") for col in TEMPLATE_COLUMNS} for r in output_rows]
    xlsx_bytes = build_output_xlsx(xlsx_rows)
    xlsx_out_path = outputs_dir / f"matched_leads_{safe_cat}_{date_str}.xlsx"
    xlsx_out_path.write_bytes(xlsx_bytes)
    print(f"[Step 5] 写 xlsx：{xlsx_out_path}")

    # ── 统计 ──
    print("\n" + "─" * 50)
    print("匹配统计：")
    print(f"  已接通通话总数        ：{stats['total_answered']}")
    print(f"  匹配到 mobile_list    ：{stats['matched_mobile_list']}（找到 poi_code）")
    print(f"  匹配到迈鲸 xlsx       ：{stats['matched_maijing']}（找到额外字段）")
    print(f"  未匹配（phone 不在 mobile_list 中）：{stats['unmatched']}")
    print("─" * 50)

    print(f"\n[完成] 输出：{xlsx_out_path}")


if __name__ == "__main__":
    main()
