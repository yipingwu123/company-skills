---
name: workflow-english-id
description: 用一句话说明这个 workflow 编排哪些 skill，当前是否 dry-run。
version: 0.1.0
metadata:
  cn_name: 中文流程名
  stage: dry-run
  tags: [workflow, dry-run]
---

# 中文流程名

## 当前阶段

第一阶段只做 dry-run，不执行真实业务动作。

## 必须先调用的 skill

执行本 workflow 前，必须先遵守：

1. `agent-operating-contract`
2. `checkpoint-runner`

没有运行目录和 `state/run_state.json` 时，不允许继续执行。

## 输入

| 字段 | 说明 |
|---|---|
| requirement_text | 飞书消息原文或人工输入 |
| dry_run | 第一阶段固定为 true |
| batch | 可选，批次号 |

## 输出

```text
runs/YYYY-MM-DD/workflow-english-id-城市-批次/
  input/
  state/run_state.json
  outputs/
  evidence/
  logs/run.log
```

## 运行目录规范

必须由 `checkpoint-runner` 创建运行目录。不允许把文件写到下载目录、桌面、当前目录或临时目录。

## 步骤状态机

| 步骤 ID | 中文名称 | 状态 | 是否需要人工确认 |
|---|---|---|---|
| parse_requirement | 解析需求 | not_started | 模糊时需要 |
| human_confirm_requirement | 人工确认需求 | not_started | 是 |

## 人工确认点

列出所有必须确认的节点。

## dry-run 禁止动作

当 `dry_run=true` 时，禁止：

1. 登录真实系统。
2. 下载真实业务文件。
3. 上传文件。
4. 导入客户数据。
5. 创建外呼任务。
6. 修改飞书在线表格。

## 失败定位

失败时必须输出中文错误，并指向：

```text
state/run_state.json
logs/run.log
evidence/
```

## 可恢复点

说明失败后从哪个 step id 继续。
