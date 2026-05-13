# 公司自动化 Skills 架构设计

## 目标

把公司现有 SOP 拆成可复用、可定位、可恢复的 skills。第一版以 dry-run 框架为主；真实系统访问必须由用户明确授权，并优先从只读接口侦查开始，不导出、不上传、不创建任务。

后续完整方案需要能端到端执行，但必须按阶段放权：先人工确认关键节点，再逐步自动化低风险步骤。

## 核心原则

1. API 优先，浏览器兜底。
2. 大流程拆成小 skill，每个 skill 只负责一个清晰动作。
3. 对人中文，对程序英文。
4. 每一步都必须有输入、输出、日志、证据和状态。
5. 失败后从 checkpoint 继续，不从头重跑。
6. 没有测试环境时，真实提交动作默认需要人工确认。
7. 稳定优先于聪明，所有 workflow 必须遵守统一执行契约。

## Agent 执行契约

所有 agent 在执行 workflow 前，必须先遵守：

1. `AUTOMATION_AGENT_CONTRACT.md`
2. `automation_contract.json`
3. `agent-operating-contract`
4. `checkpoint-runner`

没有标准运行目录和 `state/run_state.json` 时，不允许继续执行真实业务动作。

workflow 的 `SKILL.md` 里必须明确写出“必须先调用的 skill”，避免不同 agent 接手时按自己的习惯执行。

## 中文与英文命名规则

目录使用“中文名称-英文ID”，例如：

```text
common/需求解析-feishu-requirement-parser/
common/断点续跑-checkpoint-runner/
workflows/AI外呼数据流程-ai-call-data-pipeline/
```

中文名称用于业务人员定位问题。英文 ID 用于脚本调用、日志字段、状态机字段和后续自动化编排。

注意：中文索引和中文目录不会降低 skill 能力。真正需要稳定识别的是 `SKILL.md` 中的 `name`、`description`、输入输出约定和脚本接口。

## 分层设计

### 通用类 skills

通用能力，不绑定具体业务系统。

| 中文名称 | 英文 ID | 用途 |
|---|---|---|
| 需求解析 | feishu-requirement-parser | 从飞书消息中提取城市、区县、品类等需求字段 |
| 断点续跑 | checkpoint-runner | 管理运行目录、步骤状态、失败恢复 |
| Excel处理 | excel-transform | 处理筛选、匹配、汇总、模板填充 |
| 浏览器辅助 | browser-helpers | 页面定位、日期控件校验、截图证据 |
| 执行契约 | agent-operating-contract | 规定所有 workflow 的强制执行规则 |

### 登录类 skills

只负责登录和认证，不负责业务动作。

| 中文名称 | 英文 ID | 用途 |
|---|---|---|
| 迈鲸登录 | maijing-login | 获取迈鲸 token 或已登录浏览器 |
| 火山登录 | volcengine-login | 登录火山引擎控制台 |
| 订客多登录 | dingkeduo-login | 登录订客多系统 |

### 业务动作类 skills

只做一个业务动作，例如筛选导出、创建任务、生成模板、上传导入。

示例：

```text
maijing-public-sea-filter-export
volcengine-call-task-create
volcengine-call-result-export
maijing-lead-template-build
maijing-lead-import
dingkeduo-call-record-export
```

### 编排类 workflows

负责调用多个小 skill 完成端到端流程，不直接写复杂页面逻辑。

所有 workflow 必须先调用或遵守：

1. `agent-operating-contract`
2. `checkpoint-runner`

所有 workflow 必须使用标准运行目录，不能把文件散落在当前目录、下载目录或临时目录中。

示例：

```text
workflows/AI外呼数据流程-ai-call-data-pipeline/
```

## 运行目录规范

每次运行创建独立目录：

```text
runs/YYYY-MM-DD/流程英文ID-城市-批次/
  input/
    requirement.txt
    parsed_requirement.json
  state/
    run_state.json
  outputs/
    exported.xlsx
    transformed.xlsx
  evidence/
    screenshots/
    api_responses/
  logs/
    run.log
```

目录说明：

| 目录 | 用途 |
|---|---|
| input | 原始输入和解析后的需求 |
| state | 当前步骤、已完成步骤、失败位置 |
| outputs | Excel、模板、报表等最终或中间产物 |
| evidence | 截图、接口响应、下载回执等证据 |
| logs | 中文运行日志 |

## 状态机规范

每个流程必须有 `state/run_state.json`。

示例：

```json
{
  "run_id": "ai-call-data-changsha-001",
  "workflow_id": "ai-call-data-pipeline",
  "workflow_name_cn": "AI外呼数据流程",
  "dry_run": true,
  "current_step": "parse_requirement",
  "current_step_cn": "解析飞书需求",
  "steps": {
    "parse_requirement": {
      "name_cn": "解析飞书需求",
      "status": "completed",
      "started_at": "2026-05-12T22:00:00+08:00",
      "finished_at": "2026-05-12T22:00:03+08:00"
    },
    "human_confirm_requirement": {
      "name_cn": "人工确认筛选条件",
      "status": "pending"
    }
  }
}
```

状态值固定为：

| 状态 | 含义 |
|---|---|
| not_started | 未开始 |
| running | 执行中 |
| completed | 已完成 |
| pending | 等待人工确认 |
| failed | 失败 |
| skipped | 已跳过 |

## 人工确认规则

没有测试环境时，第一版必须保守。

必须人工确认的节点：

1. 飞书需求解析结果不完整或有歧义。
2. 筛选条件准备进入真实系统前。
3. 导出文件的行数、字段、日期范围异常时。
4. 创建火山外呼任务前。
5. 上传或导入迈鲸前。
6. 涉及退款、转移门店、拨打任务、客户数据写入等高风险动作前。

可优先自动化的节点：

1. 读取输入文本。
2. 解析城市、区县、品类。
3. 创建运行目录。
4. 写状态文件。
5. 生成待确认清单。
6. Excel 本地筛选、匹配、汇总、模板生成。

## 需求解析规则

飞书消息格式不固定，但关键词主要是城市、区县、品类。

示例输入：

```text
筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐
```

示例输出：

```json
{
  "city": "长沙市",
  "districts": ["岳麓区"],
  "categories": ["餐饮", "休闲娱乐"],
  "missing_fields": [],
  "needs_human_review": false
}
```

模糊输入：

```text
长沙餐饮先跑一下
```

示例输出：

```json
{
  "city": "长沙市",
  "districts": [],
  "categories": ["餐饮"],
  "missing_fields": ["区县"],
  "needs_human_review": true,
  "questions": ["区县未指定，是否使用默认区县范围？"]
}
```

## 错误定位规范

错误必须中文可读，并指向证据文件和恢复点。

示例：

```text
步骤失败：订客多日期筛选
失败原因：导出文件中存在非目标日期数据
建议处理：
1. 查看 evidence/screenshots/date-filter-after.png
2. 查看 outputs/exported.xlsx 的日期列
3. 从 state/run_state.json 的 dingkeduo_filter_date 步骤继续
可恢复点：dingkeduo_filter_date
```

## 订客多日期筛选专项要求

订客多当前最痛点是日期筛选不准。后续实现时按以下顺序处理：

1. 优先查页面请求接口，直接通过接口传日期。
2. 如果必须用页面，使用 DOM 文本、label、placeholder、role 定位，不用坐标。
3. 设置日期后读取页面当前筛选条件，确认等于目标日期。
4. 导出后检查文件日期列是否全部符合目标日期。
5. 页面显示日期和文件内容任一不一致，都判定失败。

## 第一阶段交付边界

第一阶段只交付：

1. 中文索引文档。
2. 架构设计文档。
3. 通用 skill 骨架。
4. 工作流 skill 骨架。
5. dry-run 约定。
6. agent 执行契约。
7. workflow 模板。

第一阶段默认不做：

1. 未经明确授权登录真实系统。
2. 导出真实文件。
3. 上传或导入数据。
4. 创建外呼任务。
5. 修改飞书在线表格。

## 后续接入顺序建议

1. 通用 dry-run 框架。
2. 飞书需求解析。
3. 订客多日期筛选专项。
4. 迈鲸公海客户筛选导出。
5. 火山任务创建和结果导出。
6. Excel 匹配和模板生成。
7. 迈鲸导入。
8. 报表和看板类流程。
