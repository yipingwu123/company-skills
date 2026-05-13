# 自动化 Skills 中文索引

本索引用来帮助业务人员和执行人员快速找到对应 skill、定位问题、查看恢复点。

## 使用规则

1. 看中文名称定位用途。
2. 看英文 ID 定位脚本和状态机字段。
3. 看路径打开对应 `SKILL.md`。
4. 出错时优先查看运行目录中的 `state/run_state.json`、`logs/run.log` 和 `evidence/`。

## 新对话接手

新对话或新 agent 接手时，先读：

1. `NEXT_AGENT_HANDOFF.md`
2. `AUTOMATION_AGENT_CONTRACT.md`
3. `AUTOMATION_ARCHITECTURE.md`
4. `SECRETS_POLICY.md`
5. 本索引

## 通用类

| 中文名称 | 英文 ID | 用途 | 路径 | 当前状态 |
|---|---|---|---|---|
| 需求解析 | feishu-requirement-parser | 解析飞书消息里的城市、区县、品类 | `common/需求解析-feishu-requirement-parser` | 骨架 |
| 断点续跑 | checkpoint-runner | 创建运行目录、记录步骤状态、失败后继续 | `common/断点续跑-checkpoint-runner` | 骨架 |
| Excel处理 | excel-transform | Excel 筛选、匹配、汇总、模板填充 | `common/Excel处理-excel-transform` | 骨架 |
| 浏览器辅助 | browser-helpers | 页面稳定定位、日期控件校验、截图证据 | `common/浏览器辅助-browser-helpers` | 骨架 |
| 执行契约 | agent-operating-contract | 约束所有 agent 的运行目录、状态文件、dry-run、人工确认和证据规则 | `common/执行契约-agent-operating-contract` | 骨架 |

## 登录类

| 中文名称 | 英文 ID | 用途 | 路径 | 当前状态 |
|---|---|---|---|---|
| 迈鲸登录 | maijing-login | 登录迈鲸，获取 token 和认证上下文 | `login/迈鲸登录-maijing-login` | 已真实验证 |
| 火山登录 | volcengine-login | 登录火山引擎控制台，提取 csrfToken | `login/火山登录-volcengine-login` | 侦查完成，login_browser.py 已实现 |
| 订客多登录 | dingkeduo-login | 登录订客多系统 | `login/订客多登录-dingkeduo-login` | 骨架 |

## 流程类

| 中文名称 | 英文 ID | 用途 | 路径 | 当前状态 |
|---|---|---|---|---|
| AI外呼数据流程 | ai-call-data-pipeline | 编排需求解析、迈鲸导出、火山创建任务、结果回填、迈鲸导入 | `workflows/AI外呼数据流程-ai-call-data-pipeline` | 骨架 |
| 订客多历史呼叫导出 | dingkeduo-call-record-export | 侦查并稳定化订客多历史呼叫日期筛选与导出 | `workflows/订客多历史呼叫导出-dingkeduo-call-record-export` | 只读侦查 |
| 迈鲸公海客户筛选导出 | maijing-public-sea-filter-export | 生成筛选计划，做公海客户页面/API 只读侦查、导出预检、受控真实导出和导出文件校验 | `workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export` | 真实导出与文件校验入口已实现，待人工确认执行 |
| 火山外呼任务创建 | volcengine-call-task-create | 按品类创建火山外呼任务，支持 dry-run 和真实创建 | `workflows/火山外呼任务创建-volcengine-call-task-create` | dry-run 脚本已实现，API 侦查完成 |

## 后续建议新增的业务动作类

| 中文名称 | 英文 ID | 用途 |
|---|---|---|
| 火山外呼结果导出 | volcengine-call-result-export | 导出当天已完成任务结果 |
| 迈鲸商机模板生成 | maijing-lead-template-build | 生成商机名单导入模板 |
| 迈鲸商机导入 | maijing-lead-import | 上传并导入人工确认后的模板 |

## 现阶段执行边界

当前阶段默认只做 dry-run 框架；真实系统访问必须有用户明确授权，并且先从只读侦查开始。

任何 workflow 开始前，必须先遵守：

1. [AUTOMATION_AGENT_CONTRACT.md](AUTOMATION_AGENT_CONTRACT.md)
2. `common/执行契约-agent-operating-contract`
3. `common/断点续跑-checkpoint-runner`

没有运行目录和 `state/run_state.json` 时，不允许继续执行。

允许：

1. 解析需求文本。
2. 生成运行目录。
3. 写状态文件。
4. 生成中文确认清单。
5. 设计后续 skill 输入输出。

不允许：

1. 未经用户明确授权登录真实业务系统。
2. 下载真实业务文件。
3. 上传或导入客户数据。
4. 创建火山外呼任务。
5. 修改飞书在线表格。
