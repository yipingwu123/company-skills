# 新对话接手说明

如果开启新对话，让 agent 先读本文件。

## 当前目标

公司自动化当前阶段以稳定框架和只读验证为主。

默认只允许 dry-run：

1. 解析飞书需求。
2. 创建标准运行目录。
3. 写状态文件。
4. 生成中文确认清单。
5. 停在真实系统前。

未经用户明确确认时禁止：

1. 登录真实系统。
2. 下载真实业务文件。
3. 上传或导入数据。
4. 创建火山外呼任务。
5. 修改飞书在线表格。

## 必读文件

按顺序读取：

1. `AUTOMATION_AGENT_CONTRACT.md`
2. `AUTOMATION_ARCHITECTURE.md`
3. `AUTOMATION_SKILLS_INDEX.md`
4. `automation_contract.json`
5. `SECRETS_POLICY.md`
6. 对应 workflow 的 `SKILL.md`

## 当前已完成

1. 建立中文索引。
2. 建立 agent 执行契约。
3. 建立通用 skill 骨架。
4. 建立 AI 外呼数据流程 dry-run 骨架。
5. 删除旧的 `login/maijing`，重建为 `login/迈鲸登录-maijing-login`。
6. 实现最小 dry-run 脚本。
7. 实现运行目录契约检查。
8. 实现 dry-run resume 入口。
9. 将需求解析词库拆到 `vocabulary.json`。
10. 实现 Excel/CSV 通用校验脚本 `excel_validator.py`。
11. 实现 dry-run 动作保护 `guard-action`。
12. 建立 secrets 管理规范。
13. 建立订客多历史呼叫导出专项，并完成真实只读侦查初步结论。
14. 实现订客多接口分页拉取 dry-run，已验证前 2 页拉取、内部 CSV 生成、日期校验和人工确认停点。
15. 实现迈鲸登录 API 版本脚本，生成 `maijing_auth_context.json` 供后续 skill 复用。
16. 用户已明确允许使用迈鲸账号 `admin` 和一次性提供的密码做真实登录验证；登录验证已成功。源码文档不得记录明文密码。
17. 新增迈鲸公海客户筛选导出 dry-run，可生成筛选计划和确认清单。
18. 完成迈鲸公海客户页面只读侦查，发现公海列表、城市/区域选项、历史标签等接口。
19. 新增并验证迈鲸公海客户 API 只读侦查脚本 `api_recon.py`；已验证 5 个只读接口 `code=200`，未保存完整客户明细，未导出文件。
20. 使用有头浏览器执行 `manual_filter_capture.py` 一次：页面打开和请求捕获成功，但 TDesign 多选框自动输入不稳定，未形成带筛选条件请求。
21. 从前端源码确认迈鲸公海客户筛选参数映射，并更新 `filter_param_map.example.json`。
22. 使用 `filter_count_dry_run.py --execute-readonly` 完成只读 total 校验：长沙市、岳麓区、餐饮/休闲娱乐和固定条件返回 `total=869`，未保存完整客户行，未导出。
23. 使用 `export_preflight_dry_run.py --execute-readonly-stat` 完成导出预检：`/customer/public/export/stat` 返回 `total=869`；未调用 `/customer/public/export/async`，未调用 `/customer/public/export` 下载文件。
24. 新增 `export_execute.py` 真实导出执行入口；默认只生成计划和人工确认模板，已跑通 dry-run，未下载真实文件。基于预检目录生成的模板已带 `expected_total=869` 和 `approved_route=sync_download`。真实下载必须带 `--execute-export`、登录上下文和人工确认 JSON。
25. 新增 `validate_export_file.py` 导出文件本地校验入口；真实导出后用于校验行数、号码列、城市、区县、品类，并输出中文复核清单。
26. 完成火山引擎智能外呼 API 侦查：用 QueryScript GET 接口获取全部 8 个话术 Script ID（含餐饮/休娱/购物/丽人）；QueryNumberPool 获取 2 个号码池（塔外/塔思奇）；CreateTask 完整参数列表从 JS bundle 提取。结论保存至 `login/火山登录-volcengine-login/RECON_FINDINGS.md`。
27. 新增 `login/火山登录-volcengine-login/login_browser.py`：Playwright 浏览器 IAM 登录，提取 csrfToken 写 `volcengine_auth_context.json`。
28. 新增 `workflows/火山外呼任务创建-volcengine-call-task-create/`：含 `script_map.json`（品类→话术映射）和 `create_task_dry_run.py`（dry-run 计划+真实创建双模式）。
29. 完成迈鲸真实导出：修复异步导出流程（POST `/customer/public/export/async` → 轮询 → GET `/common/download?fileName=...`），成功下载 868 行 xlsx，校验通过。
30. 新增 `common/Excel处理-excel-transform/split_by_category.py`：按一级品类拆分 xlsx，已验证：餐饮 557 行，休闲娱乐 311 行，每行均有联系电话。
31. 修复火山任务创建脚本读取手机号列的 bug（`inlineStr` 类型未处理 + 优先级错误），现复用 `excel_validator.read_table`，两个品类 dry-run 均已通过。
32. 新增 `fetch_phone_by_id.py`：按客户 ID 批量拉取迈鲸明文手机号（`GET /customer/public/{id}`），支持断点续跑，输出 `phone_list_{品类}.json`。
33. 完成迈鲸手机号拉取：餐饮 196 个有效移动手机号；休闲娱乐仅 3 个（业务以固话/400 为主，不可行）。
34. 通过 agent-browser 调用 Volcengine CreateTask API，成功创建餐饮外呼任务：TaskId=`1778676465986TH972IWOR7U94NO0Y`，196 客户，2026-05-14 09:00-20:00，号码池塔外。
35. 修复 `create_task_dry_run.py` 的 `build_task_body()`：改用 RFC 3339 时间格式（`T09:00:00+08:00`），`NumberList:[number_id]` 替代 `SelectNumberRule`，删除 `IsEncryption`/`EncryptionType`/`EnableMakeCallCheck`。
36. `fetch_phone_by_id.py` 加移动号筛选步骤（`is_mobile()`），自动输出 `mobile_list_{品类}.json`（11位、首位1、纯数字）。
37. `create_task_dry_run.py` 加 `--phone-list-json` 参数，从 `mobile_list_{品类}.json` 读真实号码；`--export-file` 改为可选（脱敏号码仅 dry-run 参考用）。已验证：餐饮 dry-run 正确读入 196 个移动号。
38. 迈鲸商机导入接口侦查完成：导入是文件导入（POST `/telesales/import/upload` multipart）；模板列 POI编码/POI名称/客户来源；`GET /customer/public/{id}` 返回 `poi` 字段即 POI编码。
39. `fetch_phone_by_id.py` 加 `poi_code`（`poi` 字段）和 `category` 字段，两者都输出到 phone_list 和 mobile_list。
40. 重写 `import_leads_dry_run.py`：实现 xlsx 生成（含 19 列模板格式）+ multipart 上传；dry-run 生成本地 xlsx 不上传；execute 真实上传后验证导入历史。已验证 dry-run 和 xlsx 列对齐正确。
41. 新增 `workflows/火山外呼结果导出-volcengine-call-result-export/browser_eval/query_task.js` 和 `export_and_download.js`：可直接粘贴到 agent-browser eval 执行，覆盖查状态→提交导出→轮询→返回下载链接全流程。
42. 新增 `receive_browser_result.py`：接收 agent-browser eval 返回的 JSON（含 download_url），下载结果 CSV，解析并写摘要，作为 browser 侧和 Python 侧的交接点。
43. Codex 任务 5-6 完成验收：`common/run_status_report.py` 可按日期打印全部 run_dir 状态表格；`browser_eval/` 下有 4 个 JS 模板（query_task.js、export_task.js、download_result.js、export_and_download.js）。
44. 新增 `batch_regen_phones.py`：一键重跑所有品类的手机号拉取（`batch 002`），获取含 poi_code 和 category 的 mobile_list，解决旧数据缺字段问题。
45. `import_leads_dry_run.py` 加 `--probe-history` 模式：只读拉取迈鲸最近 N 条导入历史，帮助确认 `客户来源(跟进阶段)` 字段有效值。
46. 新增 `RUNBOOK_2026-05-14.md`：完整 12 步操作手册，覆盖阶段一（上午重跑手机号）、阶段二（晚上导出结果 + parse_result_to_leads 筛选接通客户）、阶段三（导入迈鲸），含所有命令。
47. Codex 任务 7 验收：`parse_result_to_leads.py` 已存在，修复 PHONE_COLUMNS 缺少"被叫号码"/"通话状态" 问题，并用合成 CSV 完成端到端验证（196 行 → 87 接通 → 87 匹配 → dry-run xlsx 生成）。
48. Codex 任务 8 验收：`pipeline_status.py` 已存在，`--date 2026-05-13` 正确打印 6 步 SOP 流程状态表格，餐饮步骤 1-3 OK、步骤 4-6 WAIT。
49. 新增 `create_test_result_csv.py`：生成仿真火山外呼结果 CSV（用真实手机号、随机接通状态），用于在真实任务完成前测试 parse 和 import 流程。
50. 新增 `common/Excel处理-excel-transform/inspect_csv.py`：CSV 列结构分析工具，自动识别手机号列/状态列/时间列，并建议列名映射供 parse_result_to_leads.py 使用。
51. Codex 任务 9-10 完成验收：`validate_import_xlsx.py` 6项全通过；`batch_report.py` 正确读任务信息/解析摘要/导入历史并显示"未完成"占位符。
52. 新增 `workflows/迈鲸商机导入-maijing-lead-import/parse_import_failures.py`：解析 import_history.json 的 failReason，按原因分类，区分"7天防重"（可重试）和"硬性失败"（需人工），关联门店名称。
53. 新增 `login/迈鲸登录-maijing-login/check_session.py`：通过轻量只读 API 探测 session 是否有效，过期则打印重新登录命令，避免上传时 401。
54. RUNBOOK_2026-05-14.md 更新至 13 步：加入步骤 8（check_session）、步骤 9.5（validate_import_xlsx）、步骤 12（parse_import_failures）、步骤 13（batch_report），操作手册现已完整。
55. Codex 任务 12 验收：`verify_mobile_lists.py` 已存在，`--help` 正常，batch 001（缺 poi_code）显示 ❌，有 poi_code 数据显示 ✅。CODEX_TASKS.md 任务 11-12 均标记为 [x]。
56. 新增 `workflows/迈鲸商机导入-maijing-lead-import/schedule_retry.py`：从 import_history.json 提取"7天防重"失败 POI，关联 leads JSON 生成重试名单（格式与 mobile_list 相同），打印 7天后的重试命令。
57. 新增 `workflows/迈鲸商机导入-maijing-lead-import/generate_confirmation.py`：读取 dry-run xlsx，自动统计行数，预填充 human_confirmation.json，减少手动步骤。
58. RUNBOOK 修复：步骤 1 的 `maijing_login.py` 更正为 `login_api.py`；步骤 10 改为使用 generate_confirmation.py；步骤 12.5 新增 schedule_retry.py。Codex 任务 13-14 均已完成并验收。
59. 新增 `login/订客多登录-dingkeduo-login/login_api.py`：标准化 Playwright 登录，提取 cookies 保存为 `dingkeduo_auth_context.json`，使用 secrets_loader + checkpoint_runner，结构与迈鲸登录一致。
60. 新增 `workflows/订客多历史呼叫导出-dingkeduo-call-record-export/export_execute.py`：全量导出执行脚本，无 max_pages 限制，dry-run 探测总数生成确认清单，--execute-export 拉取所有页 + 日期校验 + 摘要。
61. 新增 `workflows/订客多历史呼叫导出-dingkeduo-call-record-export/analyze_call_records.py`：呼叫记录多维分析，按结果/坐席/时段统计，输出 JSON + 文字报告。

## 当前可运行命令

解析需求：

```bash
python3 common/需求解析-feishu-requirement-parser/parse_requirement.py \
  --text "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐"
```

运行 AI 外呼数据流程 dry-run：

```bash
python3 workflows/AI外呼数据流程-ai-call-data-pipeline/dry_run.py \
  --requirement "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐" \
  --batch 001
```

模糊需求测试：

```bash
python3 workflows/AI外呼数据流程-ai-call-data-pipeline/dry_run.py \
  --requirement "长沙餐饮先跑一下" \
  --batch 002
```

检查运行目录是否符合执行契约：

```bash
python3 common/断点续跑-checkpoint-runner/checkpoint_runner.py check-contract \
  --run-dir runs/YYYY-MM-DD/ai-call-data-pipeline-长沙市-001
```

检查当前 run 是否允许执行真实动作：

```bash
python3 common/断点续跑-checkpoint-runner/checkpoint_runner.py guard-action \
  --run-dir runs/YYYY-MM-DD/ai-call-data-pipeline-长沙市-001 \
  --action login_real_system
```

从已有 dry-run 继续：

```bash
python3 workflows/AI外呼数据流程-ai-call-data-pipeline/dry_run.py \
  --resume-run-dir runs/YYYY-MM-DD/ai-call-data-pipeline-长沙市-002 \
  --confirm-requirement \
  --confirmation-json runs/YYYY-MM-DD/ai-call-data-pipeline-长沙市-002/input/human_confirmation.json
```

`human_confirmation.json` 示例：

```json
{
  "city": "长沙市",
  "districts": ["岳麓区", "芙蓉区"],
  "categories": ["餐饮"]
}
```

## 运行产物

每次运行会生成：

```text
runs/YYYY-MM-DD/ai-call-data-pipeline-城市-批次/
  input/requirement.txt
  input/parsed_requirement.json
  state/run_state.json
  outputs/confirmation_checklist.md
  logs/run.log
```

`runs/` 是运行产物目录，已加入 `.gitignore`，不作为 skill 源码提交。

## 后续建议

**当前主路径（按优先级）**：

1. ~~迈鲸真实导出~~ ✅ 已完成（868 行，`maijing_public_sea_customers_长沙市_002.xlsx`）
2. ~~按品类拆分~~ ✅ 已完成（餐饮 557 行，休闲娱乐 311 行）
3. ~~迈鲸手机号拉取~~ ✅ 已完成（餐饮 196 个移动号；休闲娱乐仅 3 个，不可行）
4. ~~火山登录 + 餐饮外呼任务创建~~ ✅ 已完成（TaskId: `1778676465986TH972IWOR7U94NO0Y`，2026-05-14）
5. ~~火山外呼结果导出脚本骨架~~ ✅ 已实现（Codex），API 占位 NotImplementedError，等 2026-05-14 任务完成后做实际侦查
6. ~~迈鲸商机导入脚本~~ ✅ 已实现（完整流程：xlsx 生成 + multipart 上传），`客户来源` 字段有效值待确认
7. **火山外呼结果导出（2026-05-14 晚）**：任务跑完后用 `browser_eval/export_and_download.js` 导出，再用 `receive_browser_result.py` 下载 CSV
8. ~~re-run fetch_phone_by_id~~ — batch_regen_phones.py 已就绪，明日早上执行
9. ~~parse_result_to_leads.py~~ ✅ 已完成（Codex 任务七，已修复 PHONE_COLS，端到端验证通过）
10. **2026-05-14 早上**：login_api.py → batch_regen_phones.py → mobile_list with poi_code（见 RUNBOOK 阶段一）
11. **2026-05-14 晚上**：browser_eval export → receive_browser_result → inspect_csv → parse_result_to_leads → generate_confirmation → validate_import_xlsx → import_leads --execute-import → parse_import_failures → schedule_retry（若有7天防重）→ batch_report
12. **完整操作手册（14步）**：见 `RUNBOOK_2026-05-14.md`
13. **休闲娱乐**：仅 3 个移动号，本次跳过

订客多 219 页全量拉取已经被用户要求跳过，不作为当前下一步。

订客多侦查结论见：

```text
workflows/订客多历史呼叫导出-dingkeduo-call-record-export/RECON_FINDINGS.md
```

订客多分页拉取 dry-run：

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

迈鲸 API 登录：

```bash
MAIJING_USERNAME="从本地 secrets 读取" \
MAIJING_PASSWORD="从本地 secrets 读取" \
python3 login/迈鲸登录-maijing-login/login_api.py \
  --account-ref admin \
  --batch 001
```

迈鲸公海客户 API 只读侦查：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/api_recon.py \
  --auth-context runs/YYYY-MM-DD/maijing-login-admin-001/outputs/maijing_auth_context.json \
  --batch 001
```

迈鲸公海客户筛选计数 dry-run：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/filter_count_dry_run.py \
  --requirement "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐" \
  --auth-context runs/YYYY-MM-DD/maijing-login-admin-001/outputs/maijing_auth_context.json \
  --execute-readonly \
  --batch 001
```

迈鲸公海客户导出预检 dry-run：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/export_preflight_dry_run.py \
  --requirement "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐" \
  --auth-context runs/YYYY-MM-DD/maijing-login-admin-001/outputs/maijing_auth_context.json \
  --execute-readonly-stat \
  --batch 001
```

迈鲸公海客户真实导出执行计划 dry-run：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/export_execute.py \
  --preflight-run-dir runs/YYYY-MM-DD/maijing-public-sea-export-preflight-dry-run-长沙市-001 \
  --batch 001
```

迈鲸公海客户真实导出下载。只有用户明确确认后才能执行：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/export_execute.py \
  --preflight-run-dir runs/YYYY-MM-DD/maijing-public-sea-export-preflight-dry-run-长沙市-001 \
  --auth-context runs/YYYY-MM-DD/maijing-login-admin-001/outputs/maijing_auth_context.json \
  --confirmation-json runs/YYYY-MM-DD/maijing-public-sea-export-execute-长沙市-001/input/human_confirmation.json \
  --execute-export \
  --batch 001
```

迈鲸公海客户导出文件本地校验：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/validate_export_file.py \
  --file runs/YYYY-MM-DD/maijing-public-sea-export-execute-长沙市-001/outputs/maijing_public_sea_customers_长沙市_001.xlsx \
  --export-run-dir runs/YYYY-MM-DD/maijing-public-sea-export-execute-长沙市-001 \
  --batch 001
```

迈鲸手机号拉取（在品类拆分后执行，生成 mobile_list_{品类}.json）：

```bash
python3 workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/fetch_phone_by_id.py \
  --split-file runs/YYYY-MM-DD/.../outputs/split/category_餐饮.xlsx \
  --auth-context runs/YYYY-MM-DD/maijing-login-admin-001/outputs/maijing_auth_context.json \
  --category 餐饮 \
  --batch 001
```

火山外呼任务创建 dry-run（使用 mobile_list JSON，含真实号码）：

```bash
python3 workflows/火山外呼任务创建-volcengine-call-task-create/create_task_dry_run.py \
  --phone-list-json runs/YYYY-MM-DD/.../outputs/mobile_list_餐饮.json \
  --category 餐饮 \
  --task-date 2026-05-14 \
  --number-pool 塔外 \
  --batch 001
```

火山外呼任务真实创建（需人工确认；注意：Python urllib 调用火山 API 会 401，须 agent-browser eval）：

```bash
python3 workflows/火山外呼任务创建-volcengine-call-task-create/create_task_dry_run.py \
  --phone-list-json runs/YYYY-MM-DD/.../outputs/mobile_list_餐饮.json \
  --category 餐饮 \
  --task-date 2026-05-14 \
  --number-pool 塔外 \
  --auth-context runs/YYYY-MM-DD/volcengine-login-.../outputs/volcengine_auth_context.json \
  --confirmation-json runs/YYYY-MM-DD/volcengine-call-task-create-.../input/human_confirmation.json \
  --execute-create \
  --batch 001
```

火山引擎浏览器登录（需 playwright）：

```bash
VOLCENGINE_MAIN_ACCOUNT="从本地 secrets 读取" \
VOLCENGINE_USERNAME="从本地 secrets 读取" \
VOLCENGINE_PASSWORD="从本地 secrets 读取" \
python3 login/火山登录-volcengine-login/login_browser.py \
  --account-ref DXZG-1 \
  --batch 001
```

迈鲸侦查结论见：

```text
workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/RECON_FINDINGS.md
```

火山侦查结论见：

```text
login/火山登录-volcengine-login/RECON_FINDINGS.md
```

## 特别注意

稳定性优先于聪明。任何 agent 如果没有创建运行目录和 `state/run_state.json`，就不应该继续执行 workflow。
