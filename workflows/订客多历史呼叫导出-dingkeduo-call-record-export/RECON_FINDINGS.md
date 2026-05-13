# 订客多历史呼叫导出侦查结论

## 当前阶段

真实场景只读侦查已完成一轮。没有点击导出，没有下载文件，没有修改业务数据。

## 已确认事实

### 1. 历史呼叫页面 URL

```text
http://dkduo3.rmlx.cc:85/front.html#/service/call-record
```

页面标题：

```text
订客多客户管理系统
```

### 2. 登录方式

登录页使用账号密码表单：

| 字段 | 页面线索 |
|---|---|
| 账号 | `input[placeholder*="账号"]` |
| 密码 | `input[type="password"]` 或 `input[placeholder*="密码"]` |
| 登录按钮 | 文本 `登录` |

注意：登录页加载有时较慢。脚本必须等待输入框出现，不能过早判断“已登录”。

### 3. 历史呼叫日期控件

历史呼叫页面存在两个 `选择日期` 输入框：

| 顺序 | 含义 | 示例值 |
|---|---|---|
| 第 1 个 | 呼叫时间开始 | `2026-05-13 00:00:00` |
| 第 2 个 | 呼叫时间结束 | 空 |

页面文案包含：

```text
历史呼叫记录
呼叫时间
至
搜索
导出
```

### 4. 历史呼叫列表接口

页面加载时会请求：

```text
GET /pbx/cdr-record-list
```

无日期参数时示例：

```text
/pbx/cdr-record-list?duration_start=&duration_end=&caller=&callee=&calldate_start=&calldate_end=&direct=0&page=1&perpage=10&caller_or_callee=&call_name=&remark=&uniqueid=&disposition=&dial_status=&area_code=&call_project_id=&analysis_status=
```

按日期探测时可使用：

```text
/pbx/cdr-record-list?duration_start=&duration_end=&caller=&callee=&calldate_start=YYYY-MM-DD+00%3A00%3A00&calldate_end=YYYY-MM-DD+23%3A59%3A59&direct=0&page=1&perpage=10&caller_or_callee=&call_name=&remark=&uniqueid=&disposition=&dial_status=&area_code=&call_project_id=&analysis_status=
```

### 5. 接口返回结构

已确认顶层结构：

```json
{
  "code": "...",
  "message": "...",
  "data": {
    "field_list": [],
    "record_list": {
      "data": []
    }
  }
}
```

其中：

| 路径 | 含义 |
|---|---|
| `data.field_list` | 字段配置 |
| `data.record_list.data` | 呼叫记录列表 |

在 `2026-05-13` 早间探测时，`record_list.data` 返回 0 行。这不代表接口无效，只代表该时间点目标日期可能没有记录。

在 `2026-05-12` 探测时，接口返回了有效记录。

确认字段：

```text
pbxid
caller
callee
direct
uniqueid
calldate
dnid
billsec
disposition
from
monitor
disposition_name
dial_status_name
service_object_name
detail_service_object_name
service_object_id
user_name
departmentName
format_billsec
```

分页字段：

| 字段 | 示例值 | 含义 |
|---|---:|---|
| `data.record_list.current_page` | 1 | 当前页 |
| `data.record_list.per_page` | 10 | 每页数量 |
| `data.record_list.last_page` | 219 | 最后一页 |
| `data.record_list.total` | 2189 | 总记录数 |
| `data.record_list.next_page_url` | page=2 | 下一页 |

已验证：

1. `page=1&perpage=10` 返回 10 条。
2. `page=2&perpage=10` 返回 10 条。
3. 前 2 页共 20 条的 `calldate` 都在 `2026-05-12`。
4. 脱敏日期样本通过 `excel_validator.py` 日期校验。

## 已修复的问题

### 1. 登录判断过早

早期脚本在登录输入框异步加载前就判断 input 数量，导致误判为已登录。已改为最多等待 45 秒。

### 2. `networkidle` 不适合该系统

订客多可能存在长连接或持续请求，不能用 `networkidle` 判断登录成功。已改成等待 URL 变化或固定短等待。

### 3. 截图不能阻塞流程

Playwright 截图有时卡在字体加载。已改成 `safe_screenshot`，截图失败只写日志，不阻断侦查。

### 4. 网络证据脱敏

登录请求 post_data 曾包含账号密码。已修复为保存前自动脱敏：

```json
{
  "username": "***REDACTED***",
  "password": "***REDACTED***"
}
```

## 建议方案

优先走接口，不优先点页面日期控件。

推荐流程：

1. 登录订客多，获取浏览器会话。
2. 直接调用 `/pbx/cdr-record-list`。
3. 使用 `calldate_start` 和 `calldate_end` 控制日期范围。
4. 分页拉取记录。
5. 本地生成 CSV/XLSX。
6. 用 `excel_validator.py` 校验日期列。
7. 校验通过后再交给人工确认。

这样可以绕开“日期控件点击不准”的主要风险。

## 已实现 dry-run

已新增：

```text
workflows/订客多历史呼叫导出-dingkeduo-call-record-export/export_dry_run.py
```

已验证命令：

```bash
DINGKEDUO_USERNAME="从本地 secrets 读取" \
DINGKEDUO_PASSWORD="从本地 secrets 读取" \
python3 workflows/订客多历史呼叫导出-dingkeduo-call-record-export/export_dry_run.py \
  --target-date 2026-05-12 \
  --batch 102 \
  --headless \
  --perpage 10 \
  --max-pages 2
```

验证结果：

1. 拉取 2 页。
2. 共生成 20 行内部导出 CSV。
3. 接口返回总数 2189。
4. 接口返回总页数 219。
5. 日期校验通过。
6. 状态停在 `human_confirm_result`，等待人工确认。

输出文件：

```text
outputs/dingkeduo_call_records_YYYY-MM-DD.csv
outputs/confirmation_checklist.md
evidence/validation_report.json
evidence/api_responses/fetch_summary.json
```

## 数据安全处理

侦查阶段不保存完整客户明细。

已采取：

1. 登录请求中的账号密码写入证据前自动脱敏。
2. 业务号码允许写入运行目录下的内部流通文件。
3. `runs/` 已加入 `.gitignore`，不提交版本管理。
4. 对外部日志和长期文档不展示完整账号密码。

## 后续待确认

1. 需要确认是否存在官方导出接口。如果列表接口能完整分页拉取，则不一定需要点击页面导出。
2. 需要确认导出的目标字段和业务报表字段映射。
3. 需要确认是否允许全量分页拉取，例如 `2026-05-12` 需要拉取 219 页。

## 当前阻塞

额度恢复后已继续侦查，接口分页和日期校验已验证。当前不再阻塞于额度。
