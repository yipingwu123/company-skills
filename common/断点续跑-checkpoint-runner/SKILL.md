---
name: checkpoint-runner
description: 管理自动化运行目录、步骤状态、日志、证据文件和失败恢复点，支持 dry-run 和真实执行模式。
version: 0.1.0
metadata:
  cn_name: 断点续跑
  stage: dry-run
  tags: [checkpoint, state, resume, dry-run]
---

# 断点续跑

## 这个 skill 是做什么的

为每次自动化运行创建标准目录，记录每一步状态。失败后从最后一个未完成步骤继续，避免从头重跑。

## 什么时候用

- 任意端到端流程开始前。
- 任意步骤完成、失败、等待人工确认时。
- 需要查看流程卡在哪一步时。

## 输入

| 字段 | 说明 |
|---|---|
| workflow_id | 流程英文 ID |
| workflow_name_cn | 流程中文名 |
| city | 可选，城市 |
| batch | 可选，批次 |
| dry_run | 是否 dry-run |
| steps | 步骤定义 |

## 输出

```text
runs/YYYY-MM-DD/流程英文ID-城市-批次/
  input/
  state/run_state.json
  outputs/
  evidence/
  logs/run.log
```

## 脚本入口

```bash
python3 common/断点续跑-checkpoint-runner/checkpoint_runner.py create \
  --workflow-id ai-call-data-pipeline \
  --workflow-name-cn AI外呼数据流程 \
  --city 长沙市 \
  --batch 001 \
  --steps "parse_requirement:解析飞书需求,human_confirm_requirement:人工确认筛选条件"
```

检查运行目录是否符合执行契约：

```bash
python3 common/断点续跑-checkpoint-runner/checkpoint_runner.py check-contract \
  --run-dir runs/YYYY-MM-DD/ai-call-data-pipeline-长沙市-001
```

查看下一个未完成步骤：

```bash
python3 common/断点续跑-checkpoint-runner/checkpoint_runner.py next-step \
  --run-dir runs/YYYY-MM-DD/ai-call-data-pipeline-长沙市-001
```

检查某个动作当前是否允许：

```bash
python3 common/断点续跑-checkpoint-runner/checkpoint_runner.py guard-action \
  --run-dir runs/YYYY-MM-DD/ai-call-data-pipeline-长沙市-001 \
  --action login_real_system
```

当 `dry_run=true` 时，`login_real_system`、`download_real_business_file`、`upload_file`、`import_customer_data`、`create_outbound_call_task`、`modify_feishu_online_sheet` 都会被拦截。

## 状态值

| 状态 | 含义 |
|---|---|
| not_started | 未开始 |
| running | 执行中 |
| completed | 已完成 |
| pending | 等待人工确认 |
| failed | 失败 |
| skipped | 已跳过 |

## 失败时怎么定位

优先查看：

```text
state/run_state.json
logs/run.log
evidence/
```

## 可恢复点

每个步骤都必须有英文 step id。恢复时读取 `current_step` 和第一个未完成步骤，从该步骤继续。
