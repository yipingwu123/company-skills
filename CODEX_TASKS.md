# Codex 任务分配

**给 Codex 的指令**：按照本文档实现指定脚本。
- 只创建或修改本文档明确列出的文件
- 不得修改任何其他已有文件（包括 common/、login/、已有 workflows/）
- 不得调用任何真实 API，不得读取 .secrets/ 目录
- 遇到不确定的地方，按照现有同类脚本的风格和模式实现

---

## 必读背景文件（只读，不修改）

按顺序阅读：

1. `NEXT_AGENT_HANDOFF.md` — 项目整体进度和已完成内容
2. `common/断点续跑-checkpoint-runner/checkpoint_runner.py` — 运行目录和断点续跑框架（所有 workflow 必须用这个）
3. `workflows/火山外呼任务创建-volcengine-call-task-create/create_task_dry_run.py` — 参考：完整 workflow 脚本范例
4. `workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/fetch_phone_by_id.py` — 参考：API 拉取 + 断点续跑范例
5. `login/火山登录-volcengine-login/RECON_FINDINGS.md` — 火山 API 侦查结论（含接口路径、参数）

---

## 任务一：火山外呼结果导出脚本

### 目标

实现 `workflows/火山外呼结果导出-volcengine-call-result-export/` workflow，
用于任务跑完后从火山引擎导出外呼结果，生成本地 CSV/JSON。

### 要创建的文件

#### `workflows/火山外呼结果导出-volcengine-call-result-export/SKILL.md`

简短说明：此 workflow 从火山引擎下载指定任务的外呼结果，并生成本地摘要。

#### `workflows/火山外呼结果导出-volcengine-call-result-export/export_result_dry_run.py`

**功能**：

1. 默认 dry-run：只生成导出计划和人工确认清单，不调用任何 API
2. `--execute-readonly`：调用 QueryTask 接口（只读），获取任务状态和通话汇总
3. `--execute-export`：提交导出任务（写操作），轮询完成后下载结果文件

**参数**（CLI argparse）：

```
--task-id         火山任务 ID（如 1778676465986TH972IWOR7U94NO0Y）
--category        品类名称（如 餐饮），仅用于命名输出文件
--auth-context    volcengine_auth_context.json 路径（execute 模式必填）
--execute-readonly  调用只读接口查询任务状态
--execute-export    提交导出并下载（须先有 human_confirmation.json）
--confirmation-json  人工确认 JSON 路径（execute-export 必填）
--batch           批次号（默认 001）
--base-dir        运行产物根目录（默认 ROOT）
```

**Steps**（checkpoint.StepDef）：

```python
STEPS = [
    StepDef("query_task_status",  "查询任务状态"),
    StepDef("submit_export",      "提交导出任务"),
    StepDef("poll_export_status", "轮询导出状态"),
    StepDef("download_result",    "下载结果文件"),
    StepDef("parse_result",       "解析结果"),
    StepDef("write_summary",      "写入摘要"),
]
```

**火山 API 信息**（从 `RECON_FINDINGS.md` 提取）：

```
API base:  /console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01
认证：     X-Csrf-Token header（从 auth_context.json 读取）
           httpOnly cookie 由浏览器持有，Python urllib 调用会 401
           → execute 模式下，API 调用部分写成函数占位符，函数体抛出 NotImplementedError
             并打印提示："请使用 agent-browser eval 执行此调用"

QueryTask: GET /QueryTask?TaskId={task_id}
  返回字段（已知）：
    Status: "RUNNING" | "FINISHED" | "PAUSED" | "CANCELED"
    TotalCount, AnswerCount, ConnectedCount 等统计

ExportTask（名称待确认）: POST /ExportTask  body: {"TaskId": task_id}
  返回字段（推测，按 CreateTask 风格）：
    ExportId 或 TaskId

QueryExportStatus: GET /QueryExportStatus?ExportId={id}
  Status: "PROCESSING" | "SUCCESS" | "FAILED"
  DownloadUrl: "https://..."
```

**重要约束**：

- auth_context 的 `api_base` 字段拼接 URL，不硬编码 URL
- httpOnly cookie 问题：`call_api()` 函数实现为 urllib 调用，但在函数 docstring 写明"Python 调用会 401，实际执行需 agent-browser eval"
- 结果文件下载后保存至 `run_dir/outputs/result_{category}.csv`
- 写脱敏摘要（通话数/接通数/不接数），不在 evidence 中保存完整号码

**输出文件结构**：

```
runs/YYYY-MM-DD/volcengine-call-result-export-{category}-{batch}/
  input/human_confirmation.json      （需人工填写后才能 --execute-export）
  outputs/
    task_status.json                 （QueryTask 结果）
    result_{category}.csv            （下载的原始结果）
    result_summary.json              （脱敏摘要：接通数、未接数、转化数）
    confirmation_checklist.md        （dry-run 时生成）
  evidence/api_responses/
    query_task_response.json
  state/run_state.json
  logs/run.log
```

**人工确认 JSON 模板**（写到 confirmation_checklist.md）：

```json
{
  "approved": true,
  "task_id": "...",
  "category": "餐饮",
  "confirmed_by": "操作人姓名",
  "confirmed_at": "YYYY-MM-DD HH:MM:SS"
}
```

**dry-run 行为**：

- 不调用任何 API
- 生成 confirmation_checklist.md，打印任务 ID、品类、预计操作
- 所有 execute 步骤标记 "skipped"

---

## 任务二：迈鲸商机导入脚本（骨架）

### 目标

实现 `workflows/迈鲸商机导入-maijing-lead-import/` workflow 骨架，
用于将火山外呼接通/有意向的客户作为商机导入回迈鲸 CRM。

### 要创建的文件

#### `workflows/迈鲸商机导入-maijing-lead-import/SKILL.md`

简短说明：此 workflow 读取火山外呼结果摘要，将有意向客户批量导入迈鲸商机模块。

#### `workflows/迈鲸商机导入-maijing-lead-import/import_leads_dry_run.py`

**功能**：

1. 默认 dry-run：读取火山结果文件，生成待导入商机清单，不调用任何迈鲸 API
2. `--execute-import`：调用迈鲸 API 批量创建商机（须人工确认）

**参数**：

```
--result-file     火山外呼结果文件路径（result_{category}.csv 或 .json）
--category        品类名称
--auth-context    maijing_auth_context.json 路径（execute 必填）
--execute-import  真实导入（须提供 --confirmation-json）
--confirmation-json
--batch           批次号（默认 001）
--base-dir
```

**Steps**：

```python
STEPS = [
    StepDef("read_result_file",    "读取外呼结果文件"),
    StepDef("filter_leads",        "筛选有意向客户"),
    StepDef("generate_import_plan","生成导入计划"),
    StepDef("write_confirmation",  "写入人工确认清单"),
    StepDef("validate_confirmation","校验人工确认"),
    StepDef("import_to_maijing",   "导入商机到迈鲸"),
    StepDef("write_import_summary","写入导入摘要"),
]
```

**迈鲸 API（占位）**：

- 迈鲸商机创建接口尚未侦查，`import_to_maijing()` 函数体为 `raise NotImplementedError("迈鲸商机导入接口待侦查后实现")`
- 函数签名：`def import_to_maijing(base_url, headers, leads: list[dict]) -> dict`

**筛选逻辑**：

从结果文件中筛选"有意向"客户，筛选条件列名待定（占位常量 `INTERESTED_STATUS_VALUES = ["有意向", "感兴趣", "回调"]`），可通过 `--status-filter` 参数覆盖。

**输出文件结构**：

```
runs/YYYY-MM-DD/maijing-lead-import-{category}-{batch}/
  outputs/
    leads_to_import.json        （待导入商机列表，脱敏：仅显示前3条）
    import_summary.json         （成功数/失败数）
    confirmation_checklist.md
  evidence/
    import_responses/           （每批次导入响应摘要）
  state/run_state.json
  logs/run.log
```

**dry-run 行为**：

- 读取结果文件，按筛选条件统计有意向客户数
- 生成 confirmation_checklist.md 和 leads_to_import.json（脱敏版，只统计数量）
- 打印：品类、有意向客户数、跳过数

---

## 任务三：修复火山结果导出轮询逻辑

### 目标

修复已有脚本 `workflows/火山外呼结果导出-volcengine-call-result-export/export_result_dry_run.py` 中的轮询逻辑。

### 问题描述

当前 `poll_export_status` 步骤只调用一次 `query_export_status()`，直接判断是否 `SUCCESS`。
实际上火山导出任务需要等待几秒到几十秒，必须循环轮询。

### 修改内容

**只修改该文件**：`workflows/火山外呼结果导出-volcengine-call-result-export/export_result_dry_run.py`

在 `execute_export` 分支中，将当前的单次调用替换为带重试的轮询函数：

```python
def poll_export_ready(
    auth_context: dict[str, Any],
    export_id: str,
    max_wait_seconds: int = 300,
    interval_seconds: int = 5,
) -> str:
    """轮询导出状态，返回 DownloadUrl。超时或失败抛出 RuntimeError。
    
    注意：此函数内部调用 call_api()，实际执行需 agent-browser eval。
    """
    import time
    deadline = time.monotonic() + max_wait_seconds
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        resp = query_export_status(auth_context, export_id)
        result = resp.get("Result") or resp
        status = result.get("Status", "")
        download_url = result.get("DownloadUrl", "")
        print(f"  轮询 #{attempt}：状态={status}")
        if status == "SUCCESS" and download_url:
            return download_url
        if status == "FAILED":
            raise RuntimeError(f"导出任务失败：{result}")
        time.sleep(interval_seconds)
    raise RuntimeError(f"导出轮询超时（{max_wait_seconds}s），最后状态：{status}")
```

然后在 `poll_export_status` 步骤中调用：

```python
checkpoint.update_step(run_dir, "poll_export_status", "running", "轮询导出状态")
download_url = poll_export_ready(auth_context, str(export_id))
checkpoint.update_step(run_dir, "poll_export_status", "completed", f"导出就绪，URL 已获取")
```

删除原来的 `export_status = query_export_status(...)` 单次调用及其相关判断代码。

**验收**：
- `--help` 正常
- dry-run 不报错
- 不修改其他任何文件

---

## 任务四：电话号码类型分析工具

### 背景说明

迈鲸公海客户导出后，电话号码分三类：

| 类型 | 特征 | 能否做外呼 |
|------|------|-----------|
| **移动手机号** | 11位纯数字，首位为 `1` | ✅ 可以 |
| **固定电话（含区号）** | 以 `0` 开头，后跟 7-8 位数字（如 `0731-88888888` 或 `073188888888`）| ❌ 不能外呼 |
| **400/800 服务号** | 以 `400` 或 `4008` 或 `800` 开头，共 10-11 位 | ❌ 不能外呼 |
| **其他/无效** | 长度不符、含非数字字符（除 `-`）、空 | ❌ 不能外呼 |

**问题**：休闲娱乐品类 311 条客户中，绝大多数是固定电话，仅 3 个移动号（0.97%），无法建外呼任务。
需要一个分析工具，帮助判断哪些品类/批次的数据值得跑外呼。

### 要创建的文件

#### `common/Excel处理-excel-transform/phone_analysis_report.py`

**功能**：

读取一个或多个 `phone_list_{品类}.json`（`fetch_phone_by_id.py` 输出），
按品类统计各类电话数量，输出分析报告，标注是否达到外呼阈值。

**参数**：

```
--phone-list  一个或多个 phone_list_{品类}.json 路径，可重复使用
              如: --phone-list a.json --phone-list b.json
--threshold   移动号占比阈值，低于此值标注为"不建议外呼"（默认 0.10，即 10%）
--out-dir     输出目录（默认：当前目录）
--batch       批次号（默认 001）
--base-dir
```

**号码分类规则**（必须按此实现，不得自行发挥）：

```python
def classify_phone(raw: str) -> str:
    """
    返回: "mobile" | "landline" | "toll_free" | "invalid"
    """
    phone = raw.strip()
    # 去除常见分隔符后取纯数字
    digits = "".join(ch for ch in phone if ch.isdigit())
    
    # 移动号：11位纯数字，首位1
    if len(digits) == 11 and digits[0] == "1":
        return "mobile"
    
    # 400/800 服务号：400/4008/800开头，10-11位
    if digits.startswith(("400", "4008", "800")) and 10 <= len(digits) <= 11:
        return "toll_free"
    
    # 固定电话：0开头，去掉区号后剩7-8位
    # 区号长度：3位（如010）或4位（如0731），后跟7或8位号码
    if digits.startswith("0") and 10 <= len(digits) <= 12:
        return "landline"
    
    # 8位纯数字（无区号的本地号）也归为固定电话
    if len(digits) == 8:
        return "landline"
    
    return "invalid"
```

**输出**：

1. 终端打印表格（示例）：

```
品类        总号码  移动号  固话  400/800  无效  移动占比  建议
餐饮        554     196     301   45       12    35.4%    ✅ 可外呼
休闲娱乐    309     3       280   20       6     1.0%     ❌ 不建议
```

2. 写入 `{out_dir}/phone_analysis_{batch}.json`：

```json
{
  "generated_at": "2026-05-13 xx:xx:xx",
  "threshold": 0.10,
  "categories": [
    {
      "category": "餐饮",
      "total": 554,
      "mobile": 196,
      "landline": 301,
      "toll_free": 45,
      "invalid": 12,
      "mobile_ratio": 0.354,
      "recommended": true
    }
  ]
}
```

**Steps（不需要 checkpoint，这是纯分析工具，直接用 argparse + json 输出即可）**：
- 不需要 ensure_run_dir
- 不需要 checkpoint_runner
- 直接在 main() 里读文件、分类、输出

**注意**：
- `phone_list_{品类}.json` 的结构是 `{phone_list: [{Phone: "...", store_name: "..."}]}`，读 `phone_list` 字段
- `mobile_list_{品类}.json` 的结构是 `{phone_list: [{Phone: "...", store_name: "..."}]}`，可以复用同一读取逻辑
- 输入文件允许混合传入，程序从文件名或 JSON 里的 `category` 字段识别品类

**验收**：
- `python3 phone_analysis_report.py --help` 正常输出
- 用现有的 `runs/2026-05-13/maijing-fetch-phone-by-id-餐饮-001/outputs/phone_list_餐饮.json` 跑，能正确输出分类结果
- 不引入第三方库
- 不修改任何其他文件

---

## 编码规范（必须遵守）

1. **只用 Python 标准库**：不引入 requests、pandas、openpyxl 等第三方库
2. **复用 checkpoint_runner**：用 `load_module()` 加载，参考 create_task_dry_run.py 的做法
3. **复用 excel_validator.read_table**：读 xlsx/csv 时优先复用
4. **dry_run 默认 True**：只有明确传 `--execute-*` 才执行真实动作
5. **不写明文账号密码**：auth_context 通过文件路径传入，不读 .secrets/
6. **脱敏输出**：evidence 中不保存完整手机号；摘要只写条数
7. **中文注释和打印**：与现有脚本风格一致
8. **run_dir 命名**：`workflow_id` 用英文 kebab-case，`city` 参数传品类名

---

## 验收标准（任务 1-6，已完成）

- [x] 所有脚本 `python3 xxx.py --help` 正常输出
- [x] 任务一、二 dry-run 不报错，生成 run_dir、state/run_state.json、outputs/confirmation_checklist.md
- [x] execute 步骤在 dry-run 时标记 "skipped"
- [x] 任务三：export_result_dry_run.py dry-run 仍正常；`poll_export_ready` 函数存在且有轮询逻辑
- [x] 任务四：phone_analysis_report.py 用现有 phone_list_餐饮.json 能输出分类表格，不报错
- [x] 不修改 common/、login/、其他已有 workflows/ 下任何文件（任务三除外，只改 export_result_dry_run.py）
- [x] 任务五：run_status_report.py 用 --date 2026-05-13 不报错，打印表格
- [x] 任务六：browser_eval/ 目录下四个 .js 文件存在

---

## 任务七：外呼结果解析 → 商机名单

### 背景

火山外呼任务结束后，`receive_browser_result.py` 会下载 result CSV 到本地。
但下一步的商机导入需要：
1. 从 CSV 中找出"接通"的号码
2. 用号码在 mobile_list 里查找对应的 poi_code、store_name、category
3. 输出可直接传给 `import_leads_dry_run.py --mobile-list` 的 JSON（格式相同）

### 要创建的文件

**`workflows/火山外呼结果导出-volcengine-call-result-export/parse_result_to_leads.py`**

**功能**：

1. 读取火山外呼结果 CSV（`result_{品类}.csv`）
2. 读取 `mobile_list_{品类}.json`（含 poi_code）
3. 按手机号交叉匹配
4. 按状态过滤（默认只保留接通记录）
5. 输出 `leads_for_import_{品类}.json`（格式与 mobile_list 相同，可直接传给 import_leads_dry_run.py）

**参数**：

```
--result-csv     火山结果 CSV 文件路径（receive_browser_result.py 输出）
--mobile-list    mobile_list_{品类}.json 路径（含 poi_code）
--category       品类名称
--status-keywords 接通状态关键词，逗号分隔（默认："接通,已接,ANSWERED,connected"）
--batch          批次号（默认 001）
--base-dir
```

**CSV 格式说明**（火山外呼结果字段尚未确认，代码必须容错）：

- 号码列：可能叫 "手机号"、"电话"、"Phone"、"phone_number"，按顺序尝试这几个列名
- 状态列：可能叫 "通话状态"、"呼叫状态"、"Status"、"status"
- 如果找不到号码列或状态列，打印所有列名并抛出 `SystemExit`（让用户知道实际列名）

**匹配逻辑**：

```python
# 从 CSV 中提取号码（去非数字字符后匹配）
def normalize_phone(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())

# mobile_list 建索引
phone_index = {normalize_phone(r["Phone"]): r for r in mobile_list["phone_list"]}

# 遍历 CSV，找接通记录，查 phone_index
for row in csv_rows:
    phone = normalize_phone(get_phone_from_row(row))
    status = get_status_from_row(row)
    if any(kw in status for kw in status_keywords) and phone in phone_index:
        leads.append(phone_index[phone])
```

**输出格式**（与 mobile_list 相同，import_leads_dry_run.py 可直接读）：

```json
{
  "category": "餐饮",
  "source": "volcengine_call_result",
  "total_in_csv": 196,
  "answered_in_csv": 87,
  "matched_with_poi": 85,
  "phone_list": [
    {"Phone": "...", "poi_code": "...", "store_name": "...", "category": "餐饮"}
  ]
}
```

**Steps（需要 checkpoint_runner）**：

```python
STEPS = [
    StepDef("read_csv",       "读取外呼结果 CSV"),
    StepDef("read_mobile_list","读取手机号列表"),
    StepDef("match_leads",    "匹配接通号码"),
    StepDef("write_leads",    "写入商机名单"),
]
```

**dry-run 行为**：无（此脚本默认执行，只读文件，不调 API）

**输出文件结构**：

```
runs/YYYY-MM-DD/volcengine-parse-result-{category}-{batch}/
  outputs/
    leads_for_import_{category}.json    ← 传给 import_leads_dry_run.py 的文件
    parse_summary.json                  ← 统计：总数/接通数/匹配数/未匹配数
  state/run_state.json
  logs/run.log
```

**验收**：

- `python3 parse_result_to_leads.py --help` 正常
- 用 `--result-csv /dev/null` 会报"CSV 为空"错误（不崩溃）
- dry-run 时用假 CSV（只有 header 行）：打印"接通 0 条"
- 不修改任何其他文件
- 不引入第三方库

---

## 任务八：端到端流程验证脚本

### 背景

整个 SOP 有 5 个主要 workflow，每步都有 run_dir。
需要一个脚本，给定一个日期，找出该天的所有 run_dir，按 SOP 步骤顺序展示流程进度，
并标注哪一步是瓶颈（没有下一步的输入）。

### 要创建的文件

**`common/pipeline_status.py`**

**参数**：

```
--date     YYYY-MM-DD（默认今天）
--base-dir
```

**功能**：

扫描 `{base-dir}/runs/{date}/`，将 run_dir 按 workflow 分类，
按以下顺序展示流程状态：

```
SOP 流程进度（2026-05-14）
════════════════════════════════════════
步骤  Workflow                          品类    批次  输出文件                          状态
 1   maijing-public-sea-export-execute  餐饮   002   split/category_餐饮.xlsx          ✅
 2   maijing-fetch-phone-by-id          餐饮   002   mobile_list_餐饮.json (poi✓)      ✅
 3   volcengine-call-task-create        餐饮   001   task_plan.json                   dry-run
 4   volcengine-call-result-export      餐饮   001   result_餐饮.csv                   ⏳ 等待
 5   volcengine-parse-result            餐饮   001   leads_for_import_餐饮.json        ⏳ 等待
 6   maijing-lead-import                餐饮   001   import_summary.json              ⏳ 等待
════════════════════════════════════════
```

**规则**：

- 按 workflow_id 前缀匹配（不区分品类/批次）
- 对每个品类分别展示
- 检查关键输出文件是否存在（文件路径硬编码在脚本中，对应上面的列）：
  - 步骤 1：`outputs/split/category_{category}.xlsx`
  - 步骤 2：`outputs/mobile_list_{category}.json`，额外检查是否含 `poi_code`（读取第一条记录）
  - 步骤 3：`outputs/task_plan.json`
  - 步骤 4：`outputs/result_{category}.csv`
  - 步骤 5：`outputs/leads_for_import_{category}.json`
  - 步骤 6：`outputs/import_summary.json`
- 状态：✅=文件存在，⏳=文件缺失，⚠️=文件存在但步骤 failed

**不需要** checkpoint_runner，直接扫文件系统。

**验收**：

- `python3 common/pipeline_status.py --date 2026-05-13` 不报错，打印表格
- 不修改任何其他文件

---

## 验收标准（任务 7-8，已完成）

- [x] 任务七：`parse_result_to_leads.py --help` 正常；用空 CSV 运行不崩溃；输出 JSON 格式与 mobile_list 相同
- [x] 任务八：`pipeline_status.py --date 2026-05-13` 不报错，打印流程状态表格

---

## 任务九：迈鲸导入 xlsx 校验工具

### 背景

`import_leads_dry_run.py` 生成的 xlsx 文件在上传前需要人工确认列对齐是否正确。
目前只能用 Excel 打开检查，需要一个自动校验脚本。

### 要创建的文件

**`workflows/迈鲸商机导入-maijing-lead-import/validate_import_xlsx.py`**

**功能**：

读取 `import_leads_dry_run.py` 生成的 xlsx，验证：
1. 第一行（列名行）与 `TEMPLATE_COLUMNS` 完全一致
2. 数据行中 `POI编码`（B列）、`POI名称`（C列）、`电话`（G列）均非空
3. `客户来源(跟进阶段)`（A列）与 `--expected-source` 参数一致
4. `电话`（G列）是11位移动号（首位1，纯数字）
5. 打印各列非空率和样本数据

**参数**：

```
--xlsx-file         要校验的 xlsx 路径
--expected-source   预期客户来源值（如 "AI外呼"，默认不校验）
--show-rows         显示前 N 行数据（默认 3）
```

**实现说明**：

- 只用标准库（zipfile + xml.etree.ElementTree），不引入 openpyxl
- 复用 `common/Excel处理-excel-transform/excel_validator.py` 的 `read_table()` 函数读 xlsx
- 输出格式：每条检查项 "✅ 通过" 或 "❌ 失败: 原因"
- 最终 `sys.exit(0)` = 全部通过，`sys.exit(1)` = 有失败项

**验收**：

- `python3 validate_import_xlsx.py --help` 正常
- 用 `import_leads_dry_run.py --batch test002` 生成的 xlsx 跑，全部通过（因为测试数据是合法的）
- 不修改其他文件

---

## 任务十：批量操作摘要报告

### 背景

每次运行完一批外呼任务（创建、结果导出、商机导入），需要汇总本次操作的关键数字，
便于汇报或记录。

### 要创建的文件

**`common/batch_report.py`**

**功能**：

给定一个日期和品类，扫描该日期下的所有 run_dir，读取关键 JSON 文件，
生成一份纯文字的批次操作摘要。

**参数**：

```
--date      YYYY-MM-DD（默认今天）
--category  品类名称（如 餐饮）
--base-dir
```

**输出示例**：

```
═══════════════════════════════════════════════
AI 外呼批次报告 - 2026-05-14 - 餐饮
═══════════════════════════════════════════════
【外呼任务】
  任务 ID：1778676465986TH972IWOR7U94NO0Y
  计划号码数：196
  任务时段：2026-05-14 09:00 – 20:00

【外呼结果】
  总数：196
  接通：87（44.4%）
  未接：109

【商机导入】
  接通匹配 POI：85
  生成 xlsx：AI外呼商机导入_餐饮_001_20260514.xlsx
  导入成功：83
  导入失败：2

【文件路径】
  结果 CSV：runs/2026-05-14/volcengine-call-result-export-餐饮-001/outputs/result_餐饮.csv
  商机名单：runs/2026-05-14/volcengine-parse-result-餐饮-001/outputs/leads_for_import_餐饮.json
  导入摘要：runs/2026-05-14/maijing-lead-import-餐饮-001/outputs/import_history.json
═══════════════════════════════════════════════
```

**数据来源**（读取以下文件，文件不存在则显示"未完成"）：

- 任务信息：`runs/{date}/volcengine-task-created/task_{category}.json`
- 外呼结果：`runs/{date}/volcengine-call-result-export-{category}-*/outputs/result_summary.json`
- 解析摘要：`runs/{date}/volcengine-parse-result-{category}-*/outputs/parse_summary.json`
- 导入历史：`runs/{date}/maijing-lead-import-{category}-*/outputs/import_history.json`

（使用 glob 匹配，取最新的 run_dir，即按名称排序最后一个）

**不需要** checkpoint_runner，直接读 JSON 文件。

**验收**：

- `python3 common/batch_report.py --date 2026-05-13 --category 餐饮` 不报错，打印报告
- 数据缺失时显示"未完成"而不是报错
- 不修改任何其他文件

---

## 验收标准（任务 9-10）

- [x] 任务九：`validate_import_xlsx.py --help` 正常；用 test002 批次的 xlsx 跑通过；列名不对时显示 ❌
- [x] 任务十：`batch_report.py --date 2026-05-13 --category 餐饮` 不报错，打印报告（数据缺失显示"未完成"）

---

## 任务五：运行状态总览脚本

### 目标

新建 `common/run_status_report.py`，扫描指定日期的所有运行目录，打印各 workflow 运行状态表格。

### 要创建的文件

**`common/run_status_report.py`**

**参数**：
```
--date       运行日期，格式 YYYY-MM-DD（默认今天）
--base-dir   runs 根目录（默认 ROOT/runs）
--workflow   可选，只显示包含此字符串的 workflow（如 maijing、volcengine）
```

**功能**：
- 扫描 `{base-dir}/{date}/` 下所有子目录
- 读取每个子目录的 `state/run_state.json`
- 输出表格：run_dir名称 | 步骤数 | 完成数 | 失败数 | 最新步骤 | 状态
- 不报错时优雅跳过无 run_state.json 的目录
- 支持 `--workflow` 做子字符串过滤

**run_state.json 结构**（参考 `common/断点续跑-checkpoint-runner/checkpoint_runner.py`）：
- `steps`: list，每项有 `step_id`、`status`（pending/running/completed/failed/skipped）、`name_cn`

**输出示例**：
```
2026-05-13 运行状态（共 12 个目录）
────────────────────────────────────────────────────────────────────────
目录名                                     步数  完成  失败  最新步骤          状态
maijing-fetch-phone-by-id-餐饮-001         4     4     0     filter_mobile     ✅
volcengine-call-task-create-餐饮-001       8     5     0     write_confirmation ⏭ dry-run
maijing-lead-import-餐饮-002              6     4     0     write_confirmation ⏭ dry-run
...
```

**不需要** checkpoint_runner，直接读 JSON 文件。不需要 ensure_run_dir。

**验收**：
- `python3 common/run_status_report.py --date 2026-05-13` 不报错，打印出表格
- 不修改任何其他文件

---

## 任务六：火山外呼 agent-browser eval JS 模板

### 目标

新建目录 `workflows/火山外呼结果导出-volcengine-call-result-export/browser_eval/`，
创建三个可直接粘贴到 `agent-browser eval` 的 JavaScript 模板文件。

### 背景

火山控制台 API 依赖 httpOnly cookie，Python urllib 会 401，必须在浏览器上下文里调用。
这些 JS 文件是准备好的模板，到时直接粘贴执行，不需要改代码。

API base：`/console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01`

### 要创建的文件

#### `browser_eval/query_task.js`

```javascript
// 查询火山外呼任务状态
// 用法：在 agent-browser eval 中执行，替换 TASK_ID
const TASK_ID = "1778676465986TH972IWOR7U94NO0Y"; // ← 替换为实际 task_id

const API_BASE = "/console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01";
const csrfToken = decodeURIComponent(
  document.cookie.split(";").find(c => c.trim().startsWith("csrfToken="))?.split("=")[1] || ""
);

const resp = await fetch(`${API_BASE}/QueryTask?TaskId=${encodeURIComponent(TASK_ID)}`, {
  method: "GET",
  headers: { "X-Csrf-Token": csrfToken },
  credentials: "include",
});
const data = await resp.json();
const result = data.Result || {};
console.log("Status:", result.Status);
console.log("TotalCount:", result.TotalCount);
console.log("AnswerCount:", result.AnswerCount);
console.log("ConnectedCount:", result.ConnectedCount);
JSON.stringify({ Status: result.Status, TotalCount: result.TotalCount, AnswerCount: result.AnswerCount, ConnectedCount: result.ConnectedCount }, null, 2);
```

#### `browser_eval/export_task.js`

```javascript
// 提交火山外呼结果导出任务
// 用法：在 agent-browser eval 中执行，替换 TASK_ID
// ⚠️ 这是写操作，确认任务已完成（Status=FINISHED）后再执行
const TASK_ID = "1778676465986TH972IWOR7U94NO0Y"; // ← 替换

const API_BASE = "/console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01";
const csrfToken = decodeURIComponent(
  document.cookie.split(";").find(c => c.trim().startsWith("csrfToken="))?.split("=")[1] || ""
);

const resp = await fetch(`${API_BASE}/ExportTask`, {
  method: "POST",
  headers: { "X-Csrf-Token": csrfToken, "Content-Type": "application/json" },
  credentials: "include",
  body: JSON.stringify({ TaskId: TASK_ID }),
});
const data = await resp.json();
console.log("Response:", JSON.stringify(data, null, 2));
// 记录返回的 ExportId 供后续轮询使用
const exportId = (data.Result || {}).ExportId || data.ExportId || "未找到 ExportId";
console.log("ExportId:", exportId);
JSON.stringify(data, null, 2);
```

#### `browser_eval/download_result.js`

```javascript
// 轮询导出状态并获取下载链接
// 先运行 export_task.js，得到 ExportId 后再运行此文件
const EXPORT_ID = "REPLACE_WITH_EXPORT_ID"; // ← 替换

const API_BASE = "/console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01";
const csrfToken = decodeURIComponent(
  document.cookie.split(";").find(c => c.trim().startsWith("csrfToken="))?.split("=")[1] || ""
);

async function pollStatus(maxAttempts = 20, intervalMs = 3000) {
  for (let i = 0; i < maxAttempts; i++) {
    const resp = await fetch(`${API_BASE}/QueryExportStatus?ExportId=${encodeURIComponent(EXPORT_ID)}`, {
      method: "GET",
      headers: { "X-Csrf-Token": csrfToken },
      credentials: "include",
    });
    const data = await resp.json();
    const result = data.Result || data;
    console.log(`轮询 #${i+1}: Status=${result.Status}, DownloadUrl=${result.DownloadUrl || "无"}`);
    if (result.Status === "SUCCESS" && result.DownloadUrl) {
      return result.DownloadUrl;
    }
    if (result.Status === "FAILED") throw new Error("导出失败: " + JSON.stringify(result));
    await new Promise(r => setTimeout(r, intervalMs));
  }
  throw new Error("轮询超时");
}

const downloadUrl = await pollStatus();
console.log("下载链接:", downloadUrl);
downloadUrl;
```

**验收**：
- 三个文件存在，语法正确（node --check 可验证，或目视检查）
- 不修改任何其他文件
- 不需要 dry-run（这是 JS 模板，无法在 Python 环境运行）

---

## 任务十一：Maijing 导入 xlsx 列宽美化

### 背景

当前生成的 xlsx 是"裸"的 xml，没有列宽设置，用 Excel 打开后所有列宽度一样，很难阅读。
需要在 xl/worksheets/sheet1.xml 中加入 `<cols>` 节点设置合理列宽。

### 只修改文件

**`workflows/迈鲸商机导入-maijing-lead-import/import_leads_dry_run.py`**

在 `build_import_xlsx()` 函数中，向 sheetData 前插入 `<cols>` 元素设置列宽：

```python
# 在 root 内找到或创建 cols 节点（必须在 sheetData 之前）
cols_elem = ET.Element(f"{{{NS}}}cols")
col_widths = [18, 20, 20, 10, 10, 8, 16, 10, 12, 10, 14, 10, 14, 20, 10, 8, 14, 12, 12]
for i, w in enumerate(col_widths, 1):
    col = ET.SubElement(cols_elem, f"{{{NS}}}col")
    col.set("min", str(i))
    col.set("max", str(i))
    col.set("width", str(w))
    col.set("customWidth", "1")

# 在 sheetData 之前插入 cols
sheet_data_idx = list(root).index(sheet_data)
root.insert(sheet_data_idx, cols_elem)
```

列宽数组对应 TEMPLATE_COLUMNS 的 19 列（单位：字符宽度）：
- A(客户来源): 18, B(POI编码): 20, C(POI名称): 20, D(一级品类): 10, E(二级品类): 10, F(区域): 8
- G(电话): 16, H(商圈): 10, I(跟进情况): 12, J(跟进人): 10, K(跟进时间): 14, L(备注): 10
- M(跟进详情): 14, N(详细地址): 20, O(下发状态): 10, P(城市): 8, Q(KPI线索类型): 14, R(统计日期): 12, S(客户意向等级): 12

**验收**：
- `import_leads_dry_run.py` dry-run 仍正常（不报错）
- `validate_import_xlsx.py` 仍通过（列结构不变）
- 新生成的 xlsx 用 zipfile 打开 sheet1.xml 可找到 `<cols>` 节点

---

## 任务十二：批量重跑检查脚本

### 背景

`batch_regen_phones.py` 跑完后，需要验证每个品类的 mobile_list 文件：
1. 存在且非空
2. 包含 poi_code 字段（不为空）
3. mobile_count > 0

### 要创建的文件

**`workflows/迈鲸公海客户筛选导出-maijing-public-sea-filter-export/verify_mobile_lists.py`**

**参数**：
```
--run-date  YYYY-MM-DD（默认今天）
--batch     批次号（默认 002）
--categories 品类列表（默认：餐饮 休闲娱乐）
--base-dir
```

**功能**：
- 扫描 `runs/{date}/maijing-fetch-phone-by-id-{category}-{batch}/outputs/mobile_list_{category}.json`
- 每个品类输出：✅ 存在（N 条，poi_code 已填充）或 ❌ 缺失/无 poi_code
- 若全部通过，打印下一步命令（import dry-run）
- 若有失败，打印如何重跑 batch_regen_phones.py

**验收**：
- `python3 verify_mobile_lists.py --help` 正常
- 用 batch 001（缺 poi_code）运行：显示 ❌ poi_code 缺失
- 用 test 数据（有 poi_code）运行：显示 ✅
- 不修改其他文件

---

## 验收标准（任务 11-12）

- [x] 任务十一：dry-run 不报错；validate_import_xlsx 仍通过；xlsx 的 sheet1.xml 含 `<cols>` 节点
- [x] 任务十二：`verify_mobile_lists.py --help` 正常；能正确区分有/无 poi_code 的 mobile_list

---

## 任务十三：导入失败重试名单生成器

### 背景

`parse_import_failures.py` 能识别"7天内有大象跟进记录"失败的 POI，但不生成可直接再次导入的名单。
需要一个脚本将这些 POI 关联回完整手机号/store_name，生成可传给 `import_leads_dry_run.py --mobile-list` 的 JSON。

### 要创建的文件

**`workflows/迈鲸商机导入-maijing-lead-import/schedule_retry.py`**

**功能**：

1. 读取 `import_history.json`，提取 `failReason` 中"7天"防重失败的 POI 列表
2. 读取 `leads_for_import_{category}.json`（含 poi_code、Phone、store_name），按 poi_code 建索引
3. 匹配 → 生成重试名单（格式与 mobile_list 完全相同，可直接传给 import_leads_dry_run.py）
4. 输出到 `runs/{date}/maijing-lead-import-{category}-retry-{retry_date}/outputs/retry_leads_{category}.json`
5. 打印：重试日期（导入日期 + 7天）、重试数量、执行命令

**参数**：

```
--history-json    import_history.json 路径（必填）
--leads-json      leads_for_import_{category}.json 路径（必填）
--category        品类名称（必填）
--import-date     导入发生日期 YYYY-MM-DD（默认今天）
--batch           批次号（默认 001）
--base-dir
```

**失败条目提取逻辑**（`failReason` 可能是 JSON 字符串或 list，与 parse_import_failures.py 一致）：

```python
def parse_fail_reason(raw):
    if isinstance(raw, list): return raw
    if not raw or raw in ("null", "[]", ""): return []
    try: return json.loads(raw) if isinstance(json.loads(raw), list) else []
    except: return []

retryable_pois = {
    item["poi"]
    for item in parse_fail_reason(history.get("failReason", ""))
    if "7天" in item.get("reason", "")
}
```

**输出格式**（与 mobile_list 相同）：

```json
{
  "category": "餐饮",
  "source": "retry_after_7day_block",
  "original_import_date": "2026-05-14",
  "retry_date": "2026-05-21",
  "retry_count": 5,
  "phone_list": [
    {"Phone": "...", "poi_code": "...", "store_name": "...", "category": "餐饮"}
  ]
}
```

**输出目录**：

```
runs/{import-date}/maijing-lead-import-{category}-retry-{retry_date}/
  outputs/retry_leads_{category}.json
```

其中 `retry_date` = import_date + 7天，格式 `YYYYMMDD`（用于目录名）。

**打印格式**：

```
重试名单生成完成
════════════════════════════════════════
导入日期：2026-05-14
重试日期：2026-05-21（7天后）
品类    ：餐饮
重试条数：5
输出文件：runs/2026-05-14/maijing-lead-import-餐饮-retry-20260521/outputs/retry_leads_餐饮.json

执行命令（2026-05-21 重新导入）：
python3 workflows/迈鲸商机导入-maijing-lead-import/import_leads_dry_run.py \
  --mobile-list runs/2026-05-14/maijing-lead-import-餐饮-retry-20260521/outputs/retry_leads_餐饮.json \
  --category 餐饮 \
  --customer-source AI外呼 \
  --batch 001
```

**不需要** checkpoint_runner（纯文件操作）。

**验收**：

- `python3 schedule_retry.py --help` 正常
- 用合成数据（history_json 含 failReason，leads_json 含对应 poi_code）运行：生成 retry_leads.json，格式正确
- 若 failReason 无"7天"失败：打印"无需重试"并退出 0
- 不修改其他文件

---

## 任务十四：人工确认 JSON 预填充生成器

### 背景

RUNBOOK 第 10 步要求手动创建 `human_confirmation.json`，需要：
1. 知道 lead_count（来自 dry-run xlsx 的数据行数）
2. 填写 confirmed_at（当前时间）
3. 填写 confirmed_by（操作人姓名）

confirmation_checklist.md 已经有模板，但用户仍需手动复制、填写、保存为 JSON。
本脚本自动生成预填充的 human_confirmation.json（仅缺 confirmed_by）。

### 要创建的文件

**`workflows/迈鲸商机导入-maijing-lead-import/generate_confirmation.py`**

**功能**：

1. 读取 dry-run 生成的 xlsx 文件（`AI外呼商机导入_{category}_{batch}_{date}.xlsx`）
2. 用 `zipfile` + `xml.etree.ElementTree` 统计数据行数（排除 header 行）
3. 读取 run_dir 下的 `state/run_state.json`，提取 category、customer_source、batch 等元信息
4. 生成并写入 `input/human_confirmation.json`（confirmed_by 留空 `""` 让用户填写）
5. 打印 JSON 内容，提示"请填写 confirmed_by 后再执行真实导入"

**参数**：

```
--run-dir       maijing-lead-import-{category}-{batch} 的运行目录（必填）
                脚本在此目录下找 outputs/*.xlsx 和写 input/human_confirmation.json
--confirmed-by  操作人姓名（可选，默认 ""，留空让用户事后编辑）
--category      品类（若 run_state.json 中无此字段，则必填）
--customer-source 客户来源字段（若 run_state.json 中无，则必填）
```

**查找 xlsx 的逻辑**：

```python
xlsx_files = sorted((run_dir / "outputs").glob("*.xlsx"))
if not xlsx_files:
    raise SystemExit("未找到 xlsx 文件，请先运行 import_leads_dry_run.py dry-run")
xlsx_path = xlsx_files[-1]  # 取最新的
```

**统计数据行数**（只用标准库，复用 validate_import_xlsx.py 里的模式）：

```python
import zipfile, xml.etree.ElementTree as ET
with zipfile.ZipFile(xlsx_path) as zf:
    tree = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
NS = "http://schemas.openxmlformats.org/spreadsheetml/ml/2006/main"
# 行数 = sheetData 下所有 row 的数量 - 1（header 行）
sheet_data = tree.find(f".//{{{NS}}}sheetData")
row_count = len(list(sheet_data)) - 1  # 减去 header 行
```

注意：NS 可能不同，参考 import_leads_dry_run.py 中用到的 NS 常量。

**输出的 human_confirmation.json**：

```json
{
  "approved": true,
  "category": "餐饮",
  "lead_count": 87,
  "customer_source": "AI外呼",
  "confirmed_by": "",
  "confirmed_at": "2026-05-14 21:35:12"
}
```

写入路径：`{run_dir}/input/human_confirmation.json`

**打印格式**：

```
═══════════════════════════════
人工确认 JSON 预填充
═══════════════════════════════
xlsx 文件：AI外呼商机导入_餐饮_001_20260514.xlsx
数据行数  ：87
写入路径  ：runs/2026-05-14/maijing-lead-import-餐饮-001/input/human_confirmation.json

⚠️  请打开文件，将 "confirmed_by" 字段填写为操作人姓名，然后再执行真实导入。

确认后的命令：
python3 workflows/迈鲸商机导入-maijing-lead-import/import_leads_dry_run.py \
  --mobile-list <leads_for_import 路径> \
  --category 餐饮 \
  --customer-source AI外呼 \
  --auth-context <auth_context 路径> \
  --confirmation-json runs/2026-05-14/maijing-lead-import-餐饮-001/input/human_confirmation.json \
  --execute-import \
  --batch 001
```

**验收**：

- `python3 generate_confirmation.py --help` 正常
- 用现有 test002 批次的 run_dir（含 xlsx）运行：生成 human_confirmation.json，lead_count 正确
- 若 xlsx 不存在：打印清晰错误信息（"未找到 xlsx，请先运行 dry-run"）
- 不修改其他文件

---

## 验收标准（任务 13-14）

- [x] 任务十三：`schedule_retry.py --help` 正常；合成数据运行能生成 retry_leads.json，格式与 mobile_list 相同
- [x] 任务十四：`generate_confirmation.py --help` 正常；test002 批次 run_dir 运行生成 confirmation.json，lead_count 正确
