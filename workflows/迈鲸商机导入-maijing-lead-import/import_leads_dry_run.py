#!/usr/bin/env python3
"""迈鲸商机导入 workflow。

接收火山外呼 mobile_list_{品类}.json（含 poi_code、store_name），
生成导入 xlsx 并上传到迈鲸 /telesales/import/upload。

默认 dry-run：只生成 xlsx 文件，不上传。
--execute-import：上传文件（须人工确认）。

用法（dry-run 生成导入文件）：
    python3 import_leads_dry_run.py \\
        --mobile-list runs/.../outputs/mobile_list_餐饮.json \\
        --category 餐饮 \\
        --customer-source AI外呼 \\
        --batch 001

用法（真实上传，需人工确认）：
    python3 import_leads_dry_run.py \\
        --mobile-list runs/.../outputs/mobile_list_餐饮.json \\
        --category 餐饮 \\
        --customer-source AI外呼 \\
        --auth-context runs/.../outputs/maijing_auth_context.json \\
        --confirmation-json runs/.../input/human_confirmation.json \\
        --execute-import \\
        --batch 001
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
import urllib.request
import urllib.error
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ID = "maijing-lead-import"
WORKFLOW_NAME_CN = "迈鲸商机导入"

TEMPLATE_ENDPOINT = "/telesales/import/template"
UPLOAD_ENDPOINT = "/telesales/import/upload"
HISTORY_ENDPOINT = "/telesales/import/history"

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
ET.register_namespace("", NS)

# 模板列顺序（按侦查结果）
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
secrets_loader = load_module(ROOT / "common" / "secrets_loader.py", "secrets_loader")

STEPS = [
    checkpoint.StepDef("read_mobile_list", "读取移动号列表"),
    checkpoint.StepDef("build_import_xlsx", "生成导入 xlsx"),
    checkpoint.StepDef("write_confirmation", "写入人工确认清单"),
    checkpoint.StepDef("validate_confirmation", "校验人工确认"),
    checkpoint.StepDef("upload_to_maijing", "上传文件到迈鲸"),
    checkpoint.StepDef("verify_upload", "验证上传结果"),
]


# ── xlsx 生成 ────────────────────────────────────────────────────────────────

def _col_letter(idx: int) -> str:
    """0-based index → Excel 列字母。"""
    result = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        result = chr(65 + rem) + result
    return result


def _make_inline_cell(col_idx: int, row_idx: int, value: str) -> ET.Element:
    """创建 inlineStr 类型单元格。"""
    cell = ET.Element(f"{{{NS}}}c")
    cell.set("r", f"{_col_letter(col_idx)}{row_idx}")
    cell.set("t", "inlineStr")
    is_elem = ET.SubElement(cell, f"{{{NS}}}is")
    t_elem = ET.SubElement(is_elem, f"{{{NS}}}t")
    t_elem.text = value
    return cell


def build_import_xlsx(
    template_bytes: bytes,
    leads: list[dict[str, str]],
    customer_source: str,
) -> bytes:
    """在模板 xlsx 基础上追加数据行，返回新 xlsx bytes。"""
    with zipfile.ZipFile(io.BytesIO(template_bytes)) as zf:
        names = zf.namelist()
        # 找第一个工作表
        sheet_path = "xl/worksheets/sheet1.xml"
        if sheet_path not in names:
            raise RuntimeError("模板 xlsx 缺少 sheet1.xml。")

        original_sheet_xml = zf.read(sheet_path)
        root = ET.fromstring(original_sheet_xml)
        sheet_data = root.find(f"{{{NS}}}sheetData")
        if sheet_data is None:
            raise RuntimeError("sheet1.xml 缺少 sheetData。")

        # 设置列宽，方便人工打开 Excel 复核导入内容。
        existing_cols = root.find(f"{{{NS}}}cols")
        if existing_cols is not None:
            root.remove(existing_cols)
        cols_elem = ET.Element(f"{{{NS}}}cols")
        col_widths = [18, 20, 20, 10, 10, 8, 16, 10, 12, 10, 14, 10, 14, 20, 10, 8, 14, 12, 12]
        for i, width in enumerate(col_widths, 1):
            col = ET.SubElement(cols_elem, f"{{{NS}}}col")
            col.set("min", str(i))
            col.set("max", str(i))
            col.set("width", str(width))
            col.set("customWidth", "1")
        sheet_data_idx = list(root).index(sheet_data)
        root.insert(sheet_data_idx, cols_elem)

        header_rows = list(sheet_data)
        start_row_idx = len(header_rows) + 1  # header 占用第 1 行

        for i, lead in enumerate(leads):
            row_idx = start_row_idx + i
            row_elem = ET.SubElement(sheet_data, f"{{{NS}}}row")
            row_elem.set("r", str(row_idx))
            values = [
                customer_source,          # 客户来源
                lead.get("poi_code", ""), # POI编码
                lead.get("store_name", ""),# POI名称
                lead.get("category", ""), # 一级品类名
                "",                       # 二级品类名
                "",                       # 区域
                lead.get("Phone", ""),    # 电话
            ]
            # 其余列留空
            while len(values) < len(TEMPLATE_COLUMNS):
                values.append("")
            for col_idx, val in enumerate(values):
                if val:
                    row_elem.append(_make_inline_cell(col_idx, row_idx, val))

        buf = io.BytesIO()
        tree = ET.ElementTree(root)
        tree.write(buf, encoding="utf-8", xml_declaration=True)
        new_sheet_xml = buf.getvalue()

        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as dst_zf:
            for item in zf.infolist():
                if item.filename == sheet_path:
                    dst_zf.writestr(item, new_sheet_xml)
                else:
                    dst_zf.writestr(item, zf.read(item.filename))
        return out_buf.getvalue()


# ── API 调用 ─────────────────────────────────────────────────────────────────

def download_template(base_url: str, headers: dict[str, str]) -> bytes:
    url = base_url + TEMPLATE_ENDPOINT
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def upload_xlsx(
    base_url: str,
    headers: dict[str, str],
    xlsx_bytes: bytes,
    filename: str,
) -> dict[str, Any]:
    boundary = "boundary_" + uuid.uuid4().hex
    ct = f"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    lines: list[bytes] = [
        f"--{boundary}".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode(),
        f"Content-Type: {ct}".encode(),
        b"",
        xlsx_bytes,
        f"--{boundary}--".encode(),
    ]
    body = b"\r\n".join(lines)
    upload_headers = dict(headers)
    upload_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    upload_headers.pop("Content-Type".lower(), None)  # 避免重复

    url = base_url + UPLOAD_ENDPOINT
    req = urllib.request.Request(url, data=body, headers=upload_headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def get_latest_import_history(base_url: str, headers: dict[str, str]) -> dict[str, Any] | None:
    url = base_url + HISTORY_ENDPOINT + "?pageNum=1&pageSize=1"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        body = json.loads(r.read())
    rows = body.get("rows", [])
    return rows[0] if rows else None


def list_import_history(base_url: str, headers: dict[str, str], page_size: int = 20) -> list[dict[str, Any]]:
    url = base_url + HISTORY_ENDPOINT + f"?pageNum=1&pageSize={page_size}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        body = json.loads(r.read())
    return body.get("rows", [])


def cmd_probe_history(args: argparse.Namespace) -> None:
    """读取迈鲸导入历史，打印字段供参考（只读，不修改任何数据）。"""
    auth = _load_auth(args.auth_context)
    rows = list_import_history(auth["base_url"], dict(auth["headers"]), args.probe_page_size)
    if not rows:
        print("暂无导入历史。")
        return
    print(f"\n最近 {len(rows)} 条导入历史：\n")
    keep = ["id", "fileName", "importType", "totalCount", "successCount", "failCount",
            "importStatus", "createTime", "clientSource", "followStage"]
    for i, row in enumerate(rows, 1):
        print(f"── #{i} ──────────────────────────────")
        for k in keep:
            if k in row:
                print(f"  {k}: {row[k]}")
        # 打印全部非空 key 帮助发现未知字段
        extras = {k: v for k, v in row.items() if k not in keep and v not in (None, "", [], {})}
        if extras:
            print(f"  其他非空字段: {json.dumps(extras, ensure_ascii=False)}")
    print(f"\n共 {len(rows)} 条，如需更多历史请调大 --probe-page-size 参数。")


# ── 辅助 ─────────────────────────────────────────────────────────────────────

def mask_phone(p: str) -> str:
    d = "".join(ch for ch in p if ch.isdigit())
    if len(d) >= 7:
        return f"{d[:3]}****{d[-4:]}"
    return "***"


def write_confirmation_checklist(
    run_dir: Path,
    category: str,
    lead_count: int,
    customer_source: str,
) -> Path:
    path = run_dir / "outputs" / "confirmation_checklist.md"
    payload = {
        "approved": True,
        "category": category,
        "lead_count": lead_count,
        "customer_source": customer_source,
        "confirmed_by": "操作人姓名",
        "confirmed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    lines = [
        "# 迈鲸商机导入 人工确认清单",
        "",
        f"- 品类：{category}",
        f"- 待导入条数：{lead_count}",
        f"- 客户来源字段值：`{customer_source}`",
        "- 上传接口：`POST /telesales/import/upload`",
        "- ⚠️  `客户来源(跟进阶段)` 的有效值需在迈鲸界面手工确认后填入 `--customer-source`",
        "",
        "## 人工确认 JSON 模板",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "```",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def validate_confirmation(
    confirmation_path: Path,
    category: str,
    lead_count: int,
) -> dict[str, Any]:
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    if confirmation.get("approved") is not True:
        raise SystemExit("human_confirmation.json 中 approved 不为 true。")
    if confirmation.get("category") != category:
        raise SystemExit(f"category 不符。期望：{category}，确认中：{confirmation.get('category')}")
    if confirmation.get("lead_count") != lead_count:
        raise SystemExit(f"lead_count 不符。期望：{lead_count}，确认中：{confirmation.get('lead_count')}")
    return confirmation


# ── 主逻辑 ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="迈鲸商机导入 dry-run。")
    parser.add_argument("--probe-history", action="store_true",
                        help="只读：打印最近导入历史，帮助确认客户来源字段有效值（需 --auth-context）")
    parser.add_argument("--probe-page-size", type=int, default=20,
                        help="--probe-history 时拉取的历史条数（默认 20）")
    parser.add_argument("--mobile-list",
                        help="mobile_list_{品类}.json 路径（fetch_phone_by_id 输出，需含 poi_code）")
    parser.add_argument("--category", help="品类名称")
    parser.add_argument("--customer-source", default="AI外呼",
                        help="客户来源字段值（默认 'AI外呼'，上传前须与业务确认有效值）")
    parser.add_argument("--auth-context", help="maijing_auth_context.json 路径（execute 必填）")
    parser.add_argument("--execute-import", action="store_true", help="真实上传（须人工确认）")
    parser.add_argument("--confirmation-json", help="人工确认 JSON 路径")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--base-dir", default=str(ROOT))
    args = parser.parse_args()

    if args.probe_history:
        cmd_probe_history(args)
        return

    if not args.mobile_list:
        parser.error("--mobile-list 是必填项（--probe-history 模式除外）")
    if not args.category:
        parser.error("--category 是必填项（--probe-history 模式除外）")

    dry_run = not args.execute_import
    run_dir = checkpoint.ensure_run_dir(
        base_dir=Path(args.base_dir).resolve(),
        workflow_id=WORKFLOW_ID,
        workflow_name_cn=WORKFLOW_NAME_CN,
        city=args.category,
        batch=args.batch,
        dry_run=dry_run,
        steps=STEPS,
    )

    try:
        # 1. 读取 mobile_list
        checkpoint.update_step(run_dir, "read_mobile_list", "running", "读取移动号列表")
        mobile_list_path = Path(args.mobile_list).resolve()
        if not mobile_list_path.exists():
            raise SystemExit(f"mobile_list 文件不存在：{mobile_list_path}")
        mobile_data = json.loads(mobile_list_path.read_text(encoding="utf-8"))
        leads = mobile_data.get("phone_list", [])
        if not leads:
            raise SystemExit("phone_list 为空，无商机可导入。")

        missing_poi = [l for l in leads if not l.get("poi_code")]
        if missing_poi:
            print(f"⚠️  {len(missing_poi)}/{len(leads)} 条记录缺少 poi_code，将跳过（这些客户无法导入迈鲸）。")
            leads = [l for l in leads if l.get("poi_code")]
        if not leads:
            raise SystemExit("所有记录都缺少 poi_code，无法导入。请重新运行 fetch_phone_by_id.py 获取最新数据。")

        checkpoint.update_step(run_dir, "read_mobile_list", "completed",
                               f"读取 {len(leads)} 条（含 poi_code）")

        # 2. 生成导入 xlsx
        checkpoint.update_step(run_dir, "build_import_xlsx", "running", "生成导入 xlsx")
        safe_cat = "".join(c if (c.isalnum() or c in "-_") else "_" for c in args.category)
        xlsx_filename = f"AI外呼商机导入_{safe_cat}_{args.batch}_{datetime.now().strftime('%Y%m%d')}.xlsx"

        if dry_run:
            # dry-run：用空模板生成一个演示 xlsx（不调 API 下载模板）
            template_bytes = _build_stub_template()
        else:
            auth = _load_auth(args.auth_context)
            base_url = auth["base_url"]
            req_headers = dict(auth["headers"])
            template_bytes = download_template(base_url, req_headers)

        xlsx_bytes = build_import_xlsx(template_bytes, leads, args.customer_source)
        xlsx_out_path = run_dir / "outputs" / xlsx_filename
        xlsx_out_path.parent.mkdir(parents=True, exist_ok=True)
        xlsx_out_path.write_bytes(xlsx_bytes)

        checkpoint.write_json(run_dir / "outputs" / "import_plan.json", {
            "category": args.category,
            "customer_source": args.customer_source,
            "lead_count": len(leads),
            "xlsx_filename": xlsx_filename,
            "sample_masked": [
                {"poi_code": l["poi_code"], "store": l.get("store_name", ""),
                 "phone": mask_phone(l.get("Phone", ""))}
                for l in leads[:3]
            ],
        })
        checkpoint.update_step(run_dir, "build_import_xlsx", "completed",
                               f"生成 {len(leads)} 行导入 xlsx → {xlsx_filename}")

        # 3. 写确认清单
        checkpoint.update_step(run_dir, "write_confirmation", "running", "写入人工确认清单")
        checklist_path = write_confirmation_checklist(
            run_dir, args.category, len(leads), args.customer_source
        )
        checkpoint.update_step(run_dir, "write_confirmation", "completed", "写入人工确认清单")

        if dry_run:
            checkpoint.update_step(run_dir, "validate_confirmation", "skipped", "dry-run 跳过")
            checkpoint.update_step(run_dir, "upload_to_maijing", "skipped", "dry-run 跳过")
            checkpoint.update_step(run_dir, "verify_upload", "skipped", "dry-run 跳过")
            print(f"\ndry-run 完成")
            print(f"品类：{args.category}，待导入：{len(leads)} 条")
            print(f"生成 xlsx：{xlsx_out_path}")
            print(f"确认清单：{checklist_path}")
            print(f"\n⚠️  上传前须确认 --customer-source 的有效值（见 RECON_FINDINGS.md）")
            print(f"运行目录：{run_dir}")
            return

        # 4. 校验人工确认
        checkpoint.update_step(run_dir, "validate_confirmation", "running", "校验人工确认")
        if not args.confirmation_json:
            raise SystemExit("--execute-import 必须提供 --confirmation-json。")
        confirmation = validate_confirmation(
            Path(args.confirmation_json), args.category, len(leads)
        )
        checkpoint.update_step(run_dir, "validate_confirmation", "completed", "校验人工确认")

        # 5. 上传
        checkpoint.update_step(run_dir, "upload_to_maijing", "running", "上传文件到迈鲸")
        result = upload_xlsx(base_url, req_headers, xlsx_bytes, xlsx_filename)
        upload_code = result.get("code")
        upload_msg = result.get("msg", "")
        checkpoint.write_json(
            run_dir / "evidence" / "api_responses" / "upload_result.json",
            {"code": upload_code, "msg": upload_msg, "keys": list(result.keys())},
        )
        if upload_code not in (200, 0, "200", "0"):
            raise RuntimeError(f"上传失败：code={upload_code} msg={upload_msg}")
        checkpoint.update_step(run_dir, "upload_to_maijing", "completed",
                               f"上传成功 code={upload_code}")

        # 6. 验证（查最新导入历史）
        checkpoint.update_step(run_dir, "verify_upload", "running", "验证上传结果")
        history = get_latest_import_history(base_url, req_headers)
        if history:
            checkpoint.write_json(run_dir / "outputs" / "import_history.json", {
                "id": history.get("id"),
                "fileName": history.get("fileName"),
                "importType": history.get("importType"),
                "totalCount": history.get("totalCount"),
                "successCount": history.get("successCount"),
                "failCount": history.get("failCount"),
                "importStatus": history.get("importStatus"),
            })
        checkpoint.update_step(run_dir, "verify_upload", "completed",
                               f"上传已入队，历史 id={history.get('id') if history else '未知'}")
        checkpoint.append_log(run_dir, f"商机导入完成：{len(leads)} 条，文件={xlsx_filename}")

        print(f"\n上传完成！")
        print(f"文件：{xlsx_filename}，条数：{len(leads)}")
        print(f"运行目录：{run_dir}")

    except Exception as exc:
        checkpoint.update_step(run_dir, "upload_to_maijing", "failed", "上传文件到迈鲸",
                               {"failure_reason": str(exc)})
        raise


def _load_auth(path: str | None) -> dict[str, Any]:
    if not path:
        raise SystemExit("--execute-import 必须提供 --auth-context。")
    auth_path = Path(path).resolve()
    if not auth_path.exists():
        raise SystemExit(f"auth_context 不存在：{auth_path}")
    return json.loads(auth_path.read_text(encoding="utf-8"))


def _build_stub_template() -> bytes:
    """dry-run 用的最小模板 xlsx（只含 header 行）。"""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ET.register_namespace("", ns)

    root = ET.Element(f"{{{ns}}}worksheet")
    sd = ET.SubElement(root, f"{{{ns}}}sheetData")
    header_row = ET.SubElement(sd, f"{{{ns}}}row")
    header_row.set("r", "1")
    for col_idx, col_name in enumerate(TEMPLATE_COLUMNS):
        cell = ET.SubElement(header_row, f"{{{ns}}}c")
        cell.set("r", f"{_col_letter(col_idx)}1")
        cell.set("t", "inlineStr")
        is_e = ET.SubElement(cell, f"{{{ns}}}is")
        t_e = ET.SubElement(is_e, f"{{{ns}}}t")
        t_e.text = col_name

    sheet_buf = io.BytesIO()
    ET.ElementTree(root).write(sheet_buf, encoding="utf-8", xml_declaration=True)

    # 最小有效 xlsx zip
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>')
        zf.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
        zf.writestr("xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>')
        zf.writestr("xl/worksheets/sheet1.xml", sheet_buf.getvalue())
    return out.getvalue()


if __name__ == "__main__":
    main()
