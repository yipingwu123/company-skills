---
name: ai-call-data-pipeline
description: AI外呼数据端到端流程编排；第一阶段只做 dry-run，验证需求解析、运行目录、状态机和人工确认点。
version: 0.1.0
metadata:
  cn_name: AI外呼数据流程
  stage: dry-run
  tags: [workflow, ai-call, maijing, volcengine, dry-run]
---

# AI外呼数据流程

## 这个 workflow 是做什么的

编排“飞书需求解析 -> 迈鲸公海客户导出 -> Excel 按品类拆分 -> 火山创建外呼任务 -> 火山结果导出 -> Excel 匹配回填 -> 迈鲸商机导入”的端到端流程。

## 当前阶段

第一版只做 dry-run：

1. 读取飞书需求文本。
2. 解析城市、区县、品类。
3. 创建运行目录。
4. 写入 `run_state.json`。
5. 生成中文待确认清单。
6. 不登录真实系统，不导出，不上传，不创建任务。

## 必须先调用的 skill

执行本 workflow 前，必须先遵守：

1. `agent-operating-contract`
2. `checkpoint-runner`
3. `feishu-requirement-parser`

没有标准运行目录和 `state/run_state.json` 时，不允许继续执行。

## 输入

| 字段 | 说明 |
|---|---|
| requirement_text | 飞书消息原文 |
| dry_run | 第一阶段固定为 true |
| batch | 可选，批次号 |

## 输出

```text
runs/YYYY-MM-DD/ai-call-data-pipeline-城市-批次/
  input/requirement.txt
  input/parsed_requirement.json
  state/run_state.json
  outputs/confirmation_checklist.md
  logs/run.log
```

## dry-run 脚本入口

```bash
python3 workflows/AI外呼数据流程-ai-call-data-pipeline/dry_run.py \
  --requirement "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐" \
  --batch 001
```

从已有运行目录继续：

```bash
python3 workflows/AI外呼数据流程-ai-call-data-pipeline/dry_run.py \
  --resume-run-dir runs/YYYY-MM-DD/ai-call-data-pipeline-长沙市-002 \
  --confirm-requirement \
  --confirmation-json runs/YYYY-MM-DD/ai-call-data-pipeline-长沙市-002/input/human_confirmation.json
```

如果解析结果缺少城市、区县或品类，必须提供 `--confirmation-json` 补齐字段，不能只用 `--confirm-requirement` 跳过。

## 运行目录规范

必须由 `checkpoint-runner` 创建运行目录。

不允许把文件写到当前目录、桌面、下载目录或临时目录中。

标准目录：

```text
runs/YYYY-MM-DD/ai-call-data-pipeline-城市-批次/
  input/
  state/
  outputs/
  evidence/
  logs/
```

## 第一版步骤

| 步骤 ID | 中文名称 | 是否真实执行业务 |
|---|---|---|
| parse_requirement | 解析飞书需求 | 否 |
| human_confirm_requirement | 人工确认筛选条件 | 否 |
| prepare_run_plan | 生成运行计划 | 否 |
| stop_before_real_system | 停在真实系统前 | 否 |

## dry-run 禁止动作

当 `dry_run=true` 时，禁止：

1. 登录迈鲸、火山、订客多等真实系统。
2. 下载真实业务文件。
3. 上传 Excel 或模板。
4. 创建火山外呼任务。
5. 导入迈鲸客户或商机数据。
6. 修改飞书在线表格。

## 后续真实执行步骤

| 步骤 ID | 中文名称 | 人工确认 |
|---|---|---|
| maijing_export_public_sea | 迈鲸公海客户导出 | 需要确认筛选条件和导出行数 |
| split_by_category | 按品类拆分 Excel | 异常时确认 |
| volcengine_create_tasks | 火山创建外呼任务 | 必须确认 |
| volcengine_export_results | 火山导出外呼结果 | 异常时确认 |
| match_results_to_source | 外呼结果匹配源数据 | 需要确认匹配率 |
| build_maijing_import_template | 生成迈鲸导入模板 | 需要确认 |
| maijing_import_leads | 迈鲸商机导入 | 必须确认 |

## 失败时怎么定位

查看：

```text
state/run_state.json
logs/run.log
outputs/confirmation_checklist.md
```

## 可恢复点

第一版 dry-run 可从任何未完成步骤继续。后续真实执行时，每个外部系统动作都必须先保存状态和证据，再进入下一步。
