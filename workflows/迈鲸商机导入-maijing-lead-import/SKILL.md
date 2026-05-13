---
name: maijing-lead-import
description: Use when importing interested Volcengine outbound-call customers back into Maijing CRM leads.
version: 0.1.0
metadata:
  cn_name: 迈鲸商机导入
  stage: dry-run
  tags: [workflow, maijing, lead-import, dry-run]
---

# 迈鲸商机导入

## 当前阶段

默认 dry-run：读取火山外呼结果文件，筛选有意向客户，生成待导入商机计划和人工确认清单，不调用迈鲸 API。

迈鲸商机创建接口尚未侦查，`--execute-import` 会在校验人工确认后停在 `NotImplementedError`。

## 输入

| 字段 | 说明 |
|---|---|
| result_file | 火山外呼结果 CSV、XLSX 或 JSON |
| category | 品类名称 |
| auth_context | 迈鲸认证上下文，真实导入必填 |
| confirmation_json | 人工确认文件，真实导入必填 |

## 输出

```text
runs/YYYY-MM-DD/maijing-lead-import-品类-批次/
  outputs/leads_to_import.json
  outputs/import_summary.json
  outputs/confirmation_checklist.md
  evidence/import_responses/
  state/run_state.json
  logs/run.log
```

## 步骤状态机

| 步骤 ID | 中文名称 |
|---|---|
| read_result_file | 读取外呼结果文件 |
| filter_leads | 筛选有意向客户 |
| generate_import_plan | 生成导入计划 |
| write_confirmation | 写入人工确认清单 |
| validate_confirmation | 校验人工确认 |
| import_to_maijing | 导入商机到迈鲸 |
| write_import_summary | 写入导入摘要 |

## 脚本入口

```bash
python3 workflows/迈鲸商机导入-maijing-lead-import/import_leads_dry_run.py \
  --result-file runs/YYYY-MM-DD/.../outputs/result_餐饮.csv \
  --category 餐饮 \
  --batch 001
```

## dry-run 禁止动作

1. 不调用迈鲸商机创建接口。
2. 不上传客户数据。
3. 不在 evidence 中保存完整手机号。
4. 不修改迈鲸在线数据。
