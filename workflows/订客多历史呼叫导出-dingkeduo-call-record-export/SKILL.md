---
name: dingkeduo-call-record-export
description: 订客多历史呼叫记录导出专项，重点解决日期筛选不准；优先侦查接口，其次使用稳定页面定位，并用 Excel 校验导出日期。
version: 0.1.0
metadata:
  cn_name: 订客多历史呼叫导出
  stage: read-only-recon
  tags: [workflow, dingkeduo, call-record, date-filter, export]
---

# 订客多历史呼叫导出

## 当前阶段

真实场景只读侦查。

允许：

1. 登录订客多。
2. 打开历史呼叫页面。
3. 观察日期控件、筛选按钮、导出按钮。
4. 记录页面状态、DOM 线索、网络请求、截图。
5. 分页拉取接口数据并生成内部流通文件。

暂不允许：

1. 批量下载大量文件。
2. 修改系统数据。
3. 删除、提交、写入任何业务数据。
4. 绕过人工确认进入长期自动化。

## 必须先调用的 skill

执行本 workflow 前，必须先遵守：

1. `agent-operating-contract`
2. `checkpoint-runner`
3. `browser-helpers`
4. `excel-transform`
5. `dingkeduo-login`

## 输入

| 字段 | 说明 |
|---|---|
| target_date | 目标日期，格式 `YYYY-MM-DD` |
| account_ref | 订客多账号引用 |
| dry_run | 第一阶段为 true；只读侦查时可以打开页面，但不批量导出 |
| max_pages | 最多分页拉取页数 |

## 输出

```text
runs/YYYY-MM-DD/dingkeduo-call-record-export-日期-批次/
  input/
  state/run_state.json
  outputs/
  evidence/
    screenshots/
    api_responses/
    page_state.json
    network_requests.json
  logs/run.log
```

## 运行目录规范

必须由 `checkpoint-runner` 创建运行目录。不允许把文件写到桌面、下载目录或临时目录。

## 步骤状态机

| 步骤 ID | 中文名称 | 说明 |
|---|---|---|
| create_run_dir | 创建运行目录 | 由 checkpoint-runner 完成 |
| open_login_page | 打开订客多登录页 | 截图留证据 |
| login_readonly | 登录订客多 | 只获取页面访问能力 |
| open_call_record_page | 打开历史呼叫页面 | 记录页面 URL 和标题 |
| inspect_date_filter | 侦查日期筛选控件 | 找 DOM、文本、placeholder、接口参数 |
| set_target_date | 设置目标日期 | 设置后必须读取页面当前条件 |
| verify_page_filter | 校验页面日期条件 | 页面显示日期必须等于目标日期 |
| inspect_export_request | 侦查导出请求 | 优先找接口参数 |
| fetch_pages | 分页拉取历史呼叫 | 默认可限制页数 |
| validate_export_file | 校验导出文件日期 | 调用 excel-validator |
| human_confirm_result | 人工确认导出结果 | 等人工确认 |

## 人工确认点

1. 是否允许进入全量分页拉取。
2. 如果接口日期和文件日期不一致，必须人工处理。
3. 如果导出接口参数不明确，必须人工处理。

## dry-run 禁止动作

当 `dry_run=true` 时，禁止：

1. 未限制页数的全量分页拉取。
2. 修改订客多数据。
3. 删除或提交任何记录。

## 失败定位

查看：

```text
state/run_state.json
logs/run.log
evidence/screenshots/
evidence/page_state.json
evidence/network_requests.json
evidence/validation_report.json
```

## 可恢复点

日期筛选失败时，停在 `set_target_date` 或 `verify_page_filter`，不重新登录，不重新跑前置步骤。

## 当前可运行命令

只读侦查并探测列表接口：

```bash
DINGKEDUO_USERNAME="从本地 secrets 读取" \
DINGKEDUO_PASSWORD="从本地 secrets 读取" \
python3 workflows/订客多历史呼叫导出-dingkeduo-call-record-export/recon.py \
  --target-date 2026-05-12 \
  --batch 001 \
  --headless \
  --perpage 10 \
  --max-pages 2
```

该命令会：

1. 登录订客多。
2. 打开历史呼叫页面。
3. 探测 `/pbx/cdr-record-list`。
4. 生成脱敏日期样本。
5. 调用 `excel_validator.py` 校验日期。
6. 生成 `outputs/confirmation_checklist.md`。
7. 停在人工确认导出结果。

分页拉取 dry-run，生成内部流通文件并校验日期：

```bash
DINGKEDUO_USERNAME="从本地 secrets 读取" \
DINGKEDUO_PASSWORD="从本地 secrets 读取" \
python3 workflows/订客多历史呼叫导出-dingkeduo-call-record-export/export_dry_run.py \
  --target-date 2026-05-12 \
  --batch 001 \
  --headless \
  --perpage 10 \
  --max-pages 2
```

## 侦查结论

阶段性侦查结论见：

```text
workflows/订客多历史呼叫导出-dingkeduo-call-record-export/RECON_FINDINGS.md
```

当前建议优先使用 `/pbx/cdr-record-list` 接口按 `calldate_start` / `calldate_end` 分页拉取，再本地生成文件并用 `excel_validator.py` 校验日期。
