---
name: maijing-public-sea-filter-export
description: 迈鲸公海客户筛选导出流程；把飞书需求解析结果转换成迈鲸筛选计划、导出预检和受控导出执行。
version: 0.2.0
metadata:
  cn_name: 迈鲸公海客户筛选导出
  stage: controlled-export
  tags: [workflow, maijing, public-sea, export, dry-run]
---

# 迈鲸公海客户筛选导出

## 当前阶段

支持四层 dry-run：

1. 只解析飞书需求并生成筛选计划。
2. 使用已确认的登录上下文做页面/API 只读侦查。
3. 使用前端源码确认的筛选参数做只读 total 校验。
4. 使用导出统计接口做导出预检，然后停在真实导出前，不点击导出，不下载客户文件。

另有真实导出执行脚本 `export_execute.py`。该脚本默认仍是 dry-run，只生成执行计划和人工确认模板；只有同时提供 `--execute-export`、登录上下文和人工确认文件时，才允许下载真实业务文件。

真实导出后使用 `validate_export_file.py` 做本地文件校验，不访问迈鲸网站；它会校验行数、号码列、城市、区县、品类，并生成中文复核清单。

## 必须先调用的 skill

1. `agent-operating-contract`
2. `checkpoint-runner`
3. `feishu-requirement-parser`
4. `maijing-login`
5. `excel-transform`（仅导出文件校验阶段需要）

## 输入

| 字段 | 说明 |
|---|---|
| requirement_text | 飞书需求原文 |
| parsed_requirement | 已解析的城市、区县、品类 |
| account_ref | 迈鲸账号引用 |

## 固定筛选条件

当前按 SOP 固定：

| 字段 | 条件 |
|---|---|
| 进店状态 | 未进店 |
| 认领状态 | 待认领 |
| 有无号码 | 有号码 |
| 门店筛选 | 有效、误杀 |
| 跟进进度 | 未接通、未跟进 |
| 门店状态 | 营业中 |

每天变化：

| 字段 | 来源 |
|---|---|
| 所在城市 | 飞书需求 |
| 区县 | 飞书需求 |
| 品类 | 飞书需求 |

## 输出

```text
runs/YYYY-MM-DD/maijing-public-sea-filter-export-城市-批次/
  input/requirement.txt
  input/parsed_requirement.json
  outputs/filter_plan.json
  outputs/confirmation_checklist.md
  state/run_state.json
  logs/run.log
```

## 运行目录规范

每次运行必须创建独立目录，不能复用上一次运行目录写新结果。目录名必须包含 workflow ID、城市和批次，例如：

```text
runs/2026-05-13/maijing-public-sea-export-preflight-dry-run-长沙市-002/
```

所有脚本必须写入：

| 路径 | 用途 |
|---|---|
| `input/` | 原始需求、筛选计划、人工确认文件 |
| `state/run_state.json` | 步骤状态和当前停点 |
| `outputs/` | 查询计划、导出计划、校验报告、真实导出文件 |
| `evidence/` | 只读接口摘要、下载响应摘要、截图或捕获证据 |
| `logs/run.log` | 中文运行日志 |

新 agent 接手时，先看 `state/run_state.json` 的 `current_step_cn`，再看对应 `outputs/` 和 `evidence/`。

API 侦查会使用独立运行目录：

```text
runs/YYYY-MM-DD/maijing-public-sea-api-recon-接口侦查-批次/
  input/api_recon_input.json
  evidence/api_responses/*_summary.json
  outputs/api_recon_summary.json
  outputs/api_recon_report.md
  state/run_state.json
  logs/run.log
```

筛选计数 dry-run 会使用独立运行目录：

```text
runs/YYYY-MM-DD/maijing-public-sea-filter-count-dry-run-城市-批次/
  input/filter_plan.json
  outputs/filter_api_query_plan.json
  outputs/confirmation_checklist.md
  evidence/api_responses/filter_count_summary.json
  state/run_state.json
  logs/run.log
```

筛选参数人工捕获会使用独立运行目录：

```text
runs/YYYY-MM-DD/maijing-public-sea-filter-param-capture-城市-批次/
  input/filter_plan.json
  outputs/manual_capture_instructions.md
  outputs/suggested_param_mapping_candidates.json
  evidence/captured_public_list_requests.json
  state/run_state.json
  logs/run.log
```

导出预检 dry-run 会使用独立运行目录：

```text
runs/YYYY-MM-DD/maijing-public-sea-export-preflight-dry-run-城市-批次/
  input/filter_plan.json
  outputs/filter_api_query_plan.json
  outputs/export_preflight_plan.json
  outputs/export_preflight_checklist.md
  evidence/api_responses/export_stat_summary.json
  state/run_state.json
  logs/run.log
```

真实导出执行脚本会使用独立运行目录：

```text
runs/YYYY-MM-DD/maijing-public-sea-export-execute-城市-批次/
  input/filter_plan.json
  input/human_confirmation.json
  outputs/export_execute_plan.json
  outputs/human_confirmation_template.json
  outputs/human_confirmation_validation.json
  outputs/export_file_evidence.json
  outputs/maijing_public_sea_customers_城市_批次.xlsx
  evidence/api_responses/export_stat_before_download_summary.json
  evidence/api_responses/export_download_response_summary.json
  state/run_state.json
  logs/run.log
```

默认 dry-run 不会生成 `input/human_confirmation.json`、`outputs/human_confirmation_validation.json`、真实导出文件和下载响应证据。

导出文件校验会使用独立运行目录：

```text
runs/YYYY-MM-DD/maijing-public-sea-export-file-validate-城市-批次/
  input/filter_plan.json
  input/validation_input.json
  outputs/validation_report.json
  outputs/validation_review_checklist.md
  state/run_state.json
  logs/run.log
```

## 步骤状态机

| 步骤 ID | 中文名称 |
|---|---|
| parse_requirement | 解析飞书需求 |
| build_filter_plan | 生成筛选计划 |
| human_confirm_filter_plan | 人工确认筛选计划 |
| stop_before_real_export | 停在真实导出前 |

API 侦查步骤：

| 步骤 ID | 中文名称 |
|---|---|
| load_auth_context | 读取迈鲸认证上下文 |
| call_option_apis | 调用筛选选项接口 |
| call_public_list_summary | 调用公海列表结构摘要 |
| write_recon_report | 写入接口侦查报告 |
| stop_before_export | 停在真实导出前 |

筛选计数 dry-run 步骤：

| 步骤 ID | 中文名称 |
|---|---|
| parse_or_load_filter_plan | 解析或读取筛选计划 |
| build_api_query_plan | 生成 API 查询计划 |
| readonly_count_check | 只读读取筛选结果数量 |
| human_confirm_filter_count | 人工确认筛选数量 |
| stop_before_export | 停在真实导出前 |

筛选参数人工捕获步骤：

| 步骤 ID | 中文名称 |
|---|---|
| load_auth_context | 读取迈鲸认证上下文 |
| prepare_filter_plan | 准备筛选计划 |
| open_public_sea_page | 打开公海客户页面 |
| capture_filter_requests | 捕获筛选请求参数 |
| write_mapping_evidence | 写入参数映射证据 |
| stop_before_export | 停在真实导出前 |

导出预检 dry-run 步骤：

| 步骤 ID | 中文名称 |
|---|---|
| parse_or_load_filter_plan | 解析或读取筛选计划 |
| build_export_plan | 生成导出预检计划 |
| readonly_export_stat | 只读读取导出统计 |
| human_confirm_export_plan | 人工确认导出计划 |
| stop_before_export | 停在真实导出前 |

真实导出执行步骤：

| 步骤 ID | 中文名称 |
|---|---|
| prepare_export_plan | 准备导出执行计划 |
| validate_human_confirmation | 校验人工确认 |
| readonly_export_stat_before_download | 下载前复查导出统计 |
| download_export_file | 下载真实导出文件 |
| write_export_evidence | 写入导出证据 |
| stop_for_file_validation | 停在文件校验点 |

导出文件校验步骤：

| 步骤 ID | 中文名称 |
|---|---|
| load_export_file | 读取导出文件 |
| validate_row_count | 校验导出行数 |
| validate_filter_columns | 校验筛选字段 |
| write_validation_report | 写入校验报告 |
| human_review_validation | 人工复核校验结果 |

## 人工确认点

1. 城市、区县、品类缺失时必须确认。
2. 筛选计划进入真实迈鲸前必须确认。
3. 导出预检读取到的 total 和推荐导出路径必须确认。
4. `export_execute.py --execute-export` 必须有人工确认 JSON，且确认的 total 和下载前复查 total 必须一致。
5. 后续真实导出后，导出行数异常必须确认。
6. 文件校验报告有错误或警告时，必须人工复核。

## dry-run 禁止动作

1. 未经用户明确确认时登录迈鲸。
2. 点击导出按钮。
3. 调用导出接口。
4. 下载客户文件。
5. 保存完整客户列表作为业务文件。

`export_preflight_dry_run.py --execute-readonly-stat` 只允许调用 `/customer/public/export/stat`。它不允许调用 `/customer/public/export/async`，也不允许调用 `/customer/public/export` 下载文件。

`export_execute.py` 默认也是 dry-run，不会下载文件。真实下载必须同时满足：

1. 传入 `--execute-export`。
2. 传入 `--auth-context`。
3. 传入 `--confirmation-json`。
4. 人工确认文件中 `approved=true`。
5. `expected_total` 等于下载前复查的 `/customer/public/export/stat` total。
6. `approved_route` 等于当前推荐路径。

## 脚本入口

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/plan_dry_run.py \
  --requirement "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐" \
  --batch 001
```

公海客户页面/API 只读侦查：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/recon.py \
  --auth-context runs/YYYY-MM-DD/maijing-login-admin-001/outputs/maijing_auth_context.json \
  --batch 001 \
  --headless
```

公海客户 API 只读侦查：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/api_recon.py \
  --auth-context runs/YYYY-MM-DD/maijing-login-admin-001/outputs/maijing_auth_context.json \
  --batch 001
```

`api_recon.py` 只保存接口结构、分页信息和筛选选项摘要，不保存完整客户明细。

公海客户筛选计数 dry-run（默认只生成本地查询计划，不访问真实 API）：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/filter_count_dry_run.py \
  --requirement "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐" \
  --batch 001
```

只读读取筛选 total 时必须显式传入登录上下文和 `--execute-readonly`：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/filter_count_dry_run.py \
  --requirement "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐" \
  --auth-context runs/YYYY-MM-DD/maijing-login-admin-001/outputs/maijing_auth_context.json \
  --execute-readonly \
  --batch 001
```

如果参数仍未验证，脚本会拒绝访问真实 API；只读探测时需要显式加 `--allow-unverified-params`。

公海客户筛选参数人工捕获：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/manual_filter_capture.py \
  --auth-context runs/YYYY-MM-DD/maijing-login-admin-001/outputs/maijing_auth_context.json \
  --requirement "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐" \
  --wait-seconds 120 \
  --batch 001
```

运行后由人工在打开的迈鲸页面中设置筛选条件并点击查询。脚本只捕获 `/customer/public/list` 的请求参数和响应摘要，不保存完整客户行，不点击导出。

公海客户导出预检 dry-run（默认只生成本地导出计划，不访问真实 API）：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/export_preflight_dry_run.py \
  --requirement "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐" \
  --batch 001
```

只读读取导出统计时必须显式传入登录上下文和 `--execute-readonly-stat`：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/export_preflight_dry_run.py \
  --requirement "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐" \
  --auth-context runs/YYYY-MM-DD/maijing-login-admin-001/outputs/maijing_auth_context.json \
  --execute-readonly-stat \
  --batch 001
```

已验证样例：长沙市、岳麓区、餐饮/休闲娱乐和固定条件的导出统计 total 为 `869`。因为没有超过前端阈值 `10000`，预检推荐后续真实导出路径为同步下载 `/customer/public/export`；这只是推荐路径，不代表已经执行导出。

真实导出执行计划 dry-run（默认不访问真实导出接口）：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/export_execute.py \
  --requirement "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐" \
  --batch 001
```

使用已有预检运行目录生成真实导出执行计划：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/export_execute.py \
  --preflight-run-dir runs/YYYY-MM-DD/maijing-public-sea-export-preflight-dry-run-长沙市-001 \
  --batch 001
```

真实下载只能在人工确认后执行：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/export_execute.py \
  --preflight-run-dir runs/YYYY-MM-DD/maijing-public-sea-export-preflight-dry-run-长沙市-001 \
  --auth-context runs/YYYY-MM-DD/maijing-login-admin-001/outputs/maijing_auth_context.json \
  --confirmation-json runs/YYYY-MM-DD/maijing-public-sea-export-execute-长沙市-001/input/human_confirmation.json \
  --execute-export \
  --batch 001
```

人工确认 JSON 示例：

```json
{
  "approved": true,
  "confirmed_by": "业务负责人姓名",
  "confirmed_at": "2026-05-13T16:00:00+08:00",
  "expected_total": 869,
  "approved_route": "sync_download",
  "confirmation_scope": "允许按本次筛选条件下载迈鲸公海客户导出文件。",
  "notes": ""
}
```

导出文件本地校验：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/validate_export_file.py \
  --file runs/YYYY-MM-DD/maijing-public-sea-export-execute-长沙市-001/outputs/maijing_public_sea_customers_长沙市_001.xlsx \
  --export-run-dir runs/YYYY-MM-DD/maijing-public-sea-export-execute-长沙市-001 \
  --batch 001
```

如导出文件列名和默认候选不一致，可以传入 `--column-map` 指定字段候选。字段候选 JSON 的键为 `city`、`district`、`category`、`phone`，值为候选列名数组。

## 可恢复点

| 停点 | 恢复方式 |
|---|---|
| `human_confirm_filter_plan` | 补充城市、区县、品类后重新运行筛选计划 |
| `human_confirm_filter_count` | 人工确认 total 后进入导出预检 |
| `human_confirm_export_plan` | 人工确认导出统计和推荐路径后生成确认 JSON |
| `validate_human_confirmation` | 修正确认 JSON 后重新执行 `export_execute.py --execute-export` |
| `stop_for_file_validation` | 对导出文件运行 `validate_export_file.py` |
| `human_review_validation` | 人工复核校验报告，通过后才能进入火山任务创建 |

## 失败定位

| 失败位置 | 先看文件 | 处理方式 |
|---|---|---|
| 需求解析失败 | `input/requirement.txt`、`outputs/confirmation_checklist.md` | 让人工补城市、区县、品类后重新生成筛选计划 |
| 参数映射失败 | `outputs/filter_api_query_plan.json` | 补充 `filter_param_map.example.json` 或重新做只读侦查 |
| total 不符合预期 | `evidence/api_responses/filter_count_summary.json`、`export_stat_summary.json` | 停止导出，人工确认筛选条件 |
| 人工确认失败 | `outputs/human_confirmation_validation.json` | 修正确认文件或重新跑导出预检 |
| 下载返回 JSON | `evidence/api_responses/export_download_response_summary.json` | 视为业务错误，不保存为有效客户文件 |
| 文件校验失败 | `outputs/validation_report.json`、`outputs/validation_review_checklist.md` | 人工复核，不进入火山任务创建 |
