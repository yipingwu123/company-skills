---
name: agent-operating-contract
description: 所有公司自动化 workflow 执行前必须遵守的运行契约，规定运行目录、状态文件、dry-run 边界、人工确认、证据和错误定位要求。
version: 0.1.0
metadata:
  cn_name: 执行契约
  stage: dry-run
  tags: [contract, workflow, stability, dry-run]
---

# 执行契约

## 这个 skill 是做什么的

规定所有自动化 agent 在执行 workflow 前必须遵守的统一规则，避免不同 agent 按不同习惯运行，导致结果不一致。

## 什么时候用

任何 workflow 开始前都必须先阅读并遵守本 skill。

包括：

- AI外呼数据流程
- 订客多日期筛选
- 迈鲸公海客户导出
- 火山任务创建
- Excel 汇总报表
- 飞书表格写入

## 必须遵守的规则

1. workflow 开始前必须创建标准运行目录。
2. workflow 必须写 `state/run_state.json`。
3. 第一阶段 `dry_run=true`，禁止真实业务动作。
4. 高风险动作必须人工确认。
5. 错误信息必须中文可读。
6. 浏览器操作不得依赖坐标。
7. 外部系统动作必须保存证据。
8. 需求模糊时必须停下确认。
9. workflow 必须复用通用 skill，不能重复实现通用能力。
10. 每次结束必须说明当前步骤、产物位置、是否等待人工确认、下次恢复点。

## 关联文件

| 文件 | 用途 |
|---|---|
| `AUTOMATION_AGENT_CONTRACT.md` | 给人和 agent 看的完整执行契约 |
| `automation_contract.json` | 给脚本或 agent 检查的机器可读契约 |
| `AUTOMATION_ARCHITECTURE.md` | 总体架构 |
| `AUTOMATION_SKILLS_INDEX.md` | 中文索引 |

## 输入

| 字段 | 说明 |
|---|---|
| workflow_id | 即将执行的流程英文 ID |
| dry_run | 是否 dry-run，第一阶段必须为 true |
| run_dir | 运行目录 |

## 输出

| 输出 | 说明 |
|---|---|
| contract_check | 是否满足执行契约 |
| missing_items | 缺失项 |
| next_required_action | 下一步必须做什么 |

## 失败时怎么定位

如果某个 workflow 没有创建运行目录、没有状态文件、绕过人工确认或直接操作真实系统，视为违反执行契约。

优先检查：

```text
state/run_state.json
logs/run.log
AUTOMATION_AGENT_CONTRACT.md
automation_contract.json
```

## 可恢复点

如果违反执行契约但尚未执行真实业务动作，应停止当前 workflow，补齐运行目录和状态文件后再继续。
