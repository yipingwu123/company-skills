---
name: volcengine-call-result-export
description: Use when exporting completed Volcengine outbound-call task results into local CSV/JSON summaries.
version: 0.1.0
metadata:
  cn_name: 火山外呼结果导出
  stage: dry-run
  tags: [workflow, volcengine, call-result, export, dry-run]
---

# 火山外呼结果导出

## 当前阶段

默认只做 dry-run：生成导出计划和人工确认清单，不调用火山 API。

`--execute-readonly` 和 `--execute-export` 的 API 函数为占位实现。由于火山控制台依赖 httpOnly cookie，Python `urllib` 直接调用通常会 401；真实执行时应使用 `agent-browser eval` 在已登录浏览器上下文中完成调用。

## 输入

| 字段 | 说明 |
|---|---|
| task_id | 火山外呼任务 ID |
| category | 品类名称，用于运行目录和结果文件命名 |
| auth_context | 火山登录上下文，execute 模式必填 |
| confirmation_json | 人工确认文件，真实导出必填 |

## 输出

```text
runs/YYYY-MM-DD/volcengine-call-result-export-品类-批次/
  input/human_confirmation.json
  outputs/task_status.json
  outputs/result_品类.csv
  outputs/result_summary.json
  outputs/confirmation_checklist.md
  evidence/api_responses/query_task_response.json
  state/run_state.json
  logs/run.log
```

## 步骤状态机

| 步骤 ID | 中文名称 |
|---|---|
| query_task_status | 查询任务状态 |
| submit_export | 提交导出任务 |
| poll_export_status | 轮询导出状态 |
| download_result | 下载结果文件 |
| parse_result | 解析结果 |
| write_summary | 写入摘要 |

## 人工确认点

真实导出前必须人工确认任务 ID、品类、任务状态和导出动作。

## 脚本入口

```bash
python3 workflows/火山外呼结果导出-volcengine-call-result-export/export_result_dry_run.py \
  --task-id 1778676465986TH972IWOR7U94NO0Y \
  --category 餐饮 \
  --batch 001
```

## dry-run 禁止动作

1. 不调用 QueryTask。
2. 不提交 ExportTask。
3. 不轮询导出状态。
4. 不下载结果文件。
5. 不在 evidence 中保存完整号码。
