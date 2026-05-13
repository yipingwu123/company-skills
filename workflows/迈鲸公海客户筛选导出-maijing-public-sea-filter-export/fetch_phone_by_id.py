#!/usr/bin/env python3
"""按客户 ID 批量拉取迈鲸明文手机号。

导出文件中手机号已脱敏，本脚本通过 /customer/public/{id} 逐条获取明文号码，
生成 phone_list_{品类}.json（全部号码）和 mobile_list_{品类}.json（仅移动号）。

移动号判定：11 位纯数字、首位为 1。

用法：
    python3 fetch_phone_by_id.py \\
        --split-file runs/.../outputs/split/category_餐饮.xlsx \\
        --auth-context runs/.../maijing_auth_context.json \\
        --category 餐饮 \\
        --batch 001
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


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
excel_validator = load_module(
    ROOT / "common" / "Excel处理-excel-transform" / "excel_validator.py",
    "excel_validator",
)
secrets_loader = load_module(ROOT / "common" / "secrets_loader.py", "secrets_loader")

STEPS = [
    checkpoint.StepDef("read_id_list", "读取客户 ID 列表"),
    checkpoint.StepDef("fetch_phones", "批量拉取明文手机号"),
    checkpoint.StepDef("write_phone_list", "写入手机号列表"),
    checkpoint.StepDef("filter_mobile", "筛选移动手机号"),
]


def is_mobile(phone: str) -> bool:
    """移动号：11 位纯数字、首位 1。"""
    return len(phone) == 11 and phone.isdigit() and phone.startswith("1")


def fetch_customer_phone(base_url: str, headers: dict[str, str], customer_id: str) -> dict[str, str]:
    url = f"{base_url}/customer/public/{customer_id}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    row = data.get("data") or data
    return {
        "customer_id": customer_id,
        "poi_code": str(row.get("poi") or "").strip(),
        "phone": str(row.get("phone") or "").strip(),
        "store_name": str(row.get("storeName") or row.get("poiName") or row.get("name") or "").strip(),
        "category": str(row.get("categoryName") or "").strip(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="按 ID 批量拉取迈鲸明文手机号。")
    parser.add_argument("--split-file", required=True, help="按品类拆分后的 xlsx 文件")
    parser.add_argument("--auth-context", required=True, help="maijing_auth_context.json 路径")
    parser.add_argument("--category", required=True, help="品类名称（仅用于命名输出文件）")
    parser.add_argument("--interval", type=float, default=0.15, help="每次请求间隔秒数（默认 0.15）")
    parser.add_argument("--batch", default="001")
    parser.add_argument("--base-dir", default=str(ROOT))
    args = parser.parse_args()

    run_dir = checkpoint.ensure_run_dir(
        base_dir=Path(args.base_dir).resolve(),
        workflow_id="maijing-fetch-phone-by-id",
        workflow_name_cn="迈鲸批量拉取手机号",
        city=args.category,
        batch=args.batch,
        dry_run=False,
        steps=STEPS,
    )

    auth = json.loads(Path(args.auth_context).read_text(encoding="utf-8"))
    base_url = auth["base_url"]
    headers = dict(auth["headers"])

    try:
        # 1. 读取 ID 列表
        checkpoint.update_step(run_dir, "read_id_list", "running", "读取客户 ID 列表")
        records = excel_validator.read_table(Path(args.split_file))
        customer_ids = [r["客户ID"].strip() for r in records if r.get("客户ID", "").strip()]
        if not customer_ids:
            raise SystemExit("未找到客户 ID 列（列名：客户ID）。")
        checkpoint.update_step(run_dir, "read_id_list", "completed", f"读取 {len(customer_ids)} 个客户 ID")

        # 2. 批量拉取
        checkpoint.update_step(run_dir, "fetch_phones", "running", f"批量拉取 {len(customer_ids)} 个明文手机号")

        # 断点续跑：检查已有进度
        progress_path = run_dir / "outputs" / "fetch_progress.json"
        fetched: list[dict[str, str]] = []
        failed_ids: list[str] = []
        if progress_path.exists():
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            fetched = progress.get("fetched", [])
            failed_ids = progress.get("failed", [])
            done_ids = {f["customer_id"] for f in fetched}
            customer_ids = [cid for cid in customer_ids if cid not in done_ids]
            print(f"断点续跑：已完成 {len(done_ids)}，剩余 {len(customer_ids)}")

        total = len(customer_ids) + len(fetched)
        for i, cid in enumerate(customer_ids):
            try:
                result = fetch_customer_phone(base_url, headers, cid)
                if result["phone"]:
                    fetched.append(result)
                else:
                    failed_ids.append(cid)
            except Exception as exc:
                failed_ids.append(cid)
                checkpoint.append_log(run_dir, f"拉取 ID={cid} 失败：{exc}")

            # 每 50 条保存进度
            if (i + 1) % 50 == 0 or i == len(customer_ids) - 1:
                checkpoint.write_json(progress_path, {"fetched": fetched, "failed": failed_ids})
                done_count = len(fetched) + len(failed_ids)
                print(f"  进度：{done_count}/{total}，有号码：{len(fetched)}，无号码：{len(failed_ids)}")

            time.sleep(args.interval)

        checkpoint.update_step(
            run_dir, "fetch_phones", "completed",
            f"拉取完成，有号码 {len(fetched)}，无号码/失败 {len(failed_ids)}",
        )

        # 3. 写入手机号列表
        checkpoint.update_step(run_dir, "write_phone_list", "running", "写入手机号列表")
        safe_cat = "".join(c if (c.isalnum() or c in "-_") else "_" for c in args.category)
        out_path = run_dir / "outputs" / f"phone_list_{safe_cat}.json"
        phone_list = [
            {
                "Phone": r["phone"],
                "poi_code": r["poi_code"],
                "store_name": r["store_name"],
                "category": r["category"],
            }
            for r in fetched
            if r["phone"]
        ]
        checkpoint.write_json(out_path, {
            "category": args.category,
            "total_ids": total,
            "phone_count": len(phone_list),
            "failed_count": len(failed_ids),
            "phone_list": phone_list,
        })

        # 写脱敏摘要到 evidence
        checkpoint.write_json(
            run_dir / "evidence" / "api_responses" / "phone_fetch_summary.json",
            {
                "category": args.category,
                "total_ids": total,
                "phone_count": len(phone_list),
                "failed_count": len(failed_ids),
                "sample_masked": [secrets_loader.mask_secret(p["Phone"]) for p in phone_list[:3]],
            },
        )
        checkpoint.update_step(run_dir, "write_phone_list", "completed", f"写入 {len(phone_list)} 个手机号")

        # 4. 筛选移动号
        checkpoint.update_step(run_dir, "filter_mobile", "running", "筛选移动手机号")
        mobile_list = [p for p in phone_list if is_mobile(p["Phone"])]
        # poi_code 传入 mobile_list（导入迈鲸商机时需要）
        mobile_path = run_dir / "outputs" / f"mobile_list_{safe_cat}.json"
        checkpoint.write_json(mobile_path, {
            "category": args.category,
            "total_ids": total,
            "mobile_count": len(mobile_list),
            "phone_list": mobile_list,
        })
        checkpoint.update_step(
            run_dir, "filter_mobile", "completed",
            f"移动号 {len(mobile_list)}/{len(phone_list)}（非移动号 {len(phone_list) - len(mobile_list)} 个跳过）",
        )
        checkpoint.append_log(run_dir, f"批量拉取完成：{len(phone_list)} 个有效号码，其中移动号 {len(mobile_list)} 个。")

        print(f"\n拉取完成：{len(phone_list)} 个有效号码，移动号 {len(mobile_list)} 个，{len(failed_ids)} 个无号码/失败")
        print(f"全部号码：{out_path}")
        print(f"移动号：  {mobile_path}")
        print(f"运行目录：{run_dir}")

    except Exception as exc:
        checkpoint.update_step(run_dir, "fetch_phones", "failed", "批量拉取手机号",
                                {"failure_reason": str(exc)})
        raise


if __name__ == "__main__":
    main()
