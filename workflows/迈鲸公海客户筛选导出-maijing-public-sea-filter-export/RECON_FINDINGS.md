# 迈鲸公海客户接口侦查结论

## 当前结论

已完成迈鲸真实登录验证和公海客户只读接口侦查。

本次侦查只保存接口结构、筛选选项摘要和分页总量，不保存完整客户明细，不点击导出，不下载客户文件。

2026-05-13 已用有头浏览器执行一次 `manual_filter_capture.py`：

- 页面打开成功，认证上下文有效。
- 已处理页面弹窗“中台审核提醒”。
- 脚本成功捕获初始 `/customer/public/list` 请求。
- 通过可访问性方式给 TDesign 多选下拉框输入城市未成功，因此本次有头浏览器没有形成带筛选条件的请求。
- 结论：迈鲸页面控件不适合作为主路径自动点击，后续应优先走 API 和前端源码确认的参数。

## 已验证内容

| 项目 | 结果 |
|---|---|
| 登录方式 | `login/迈鲸登录-maijing-login/login_api.py` 可生成认证上下文 |
| 公海页面 | `https://mj-whale.com/customer/publicSeas` 可通过认证上下文访问 |
| 选项接口 | 已验证 source clues、history tag、region options、sync detail status |
| 公海列表接口 | `GET /prod-api/customer/public/list?pageNum=1&pageSize=10` 返回 `code=200` |
| 公海列表总量 | 本次摘要显示 `total=662898` |
| 筛选计数校验 | 长沙市、岳麓区、餐饮/休闲娱乐、固定条件只读 total 返回 `869` |
| 导出预检校验 | `/customer/public/export/stat` 只读 total 返回 `869`，未调用导出接口 |
| 导出执行入口 | 已实现 `export_execute.py`，默认 dry-run，未下载真实文件 |
| 导出文件校验 | 已实现 `validate_export_file.py`，用于真实导出后的本地行数和筛选条件校验 |
| 敏感信息检查 | API 侦查目录未检出密码、Authorization、Bearer、Admin-Token、JWT token |

## 已发现接口

| 用途 | 接口 |
|---|---|
| 公海客户列表 | `/prod-api/customer/public/list` |
| 公海客户导出统计 | `/prod-api/customer/public/export/stat` |
| 公海客户同步导出 | `/prod-api/customer/public/export` |
| 公海客户异步导出 | `/prod-api/customer/public/export/async` |
| 城市/区域选项 | `/prod-api/customer/public/regionOptions` |
| 历史标签筛选项 | `/prod-api/customer/public/historyTagFilterOptions` |
| 线索来源字典 | `/prod-api/system/dict/data/listDict?dictType=source_clues` |
| 同步状态 | `/prod-api/customer/sync/detail/status/detail` |

## 重要字段线索

公海列表首行字段名摘要里已经看到这些筛选相关字段：

| 业务含义 | 字段线索 |
|---|---|
| 城市 | `city`, `cityId`, `cityName`, `cityNameList` |
| 区县 | `district`, `districtId`, `districtName`, `districtNameList` |
| 品类 | `categoryId`, `categoryName`, `categoryNameList`, `middleCategoryId`, `middleCategoryName`, `middleCategoryNameList` |
| 是否有号码 | `hasPhone`, `phone`, `hasKpPhone`, `kpPhone` |
| 跟进进度 | `followProgress`, `followProgressList`, `followUpProgress` |
| 认领 | `claimUserName`, `claimUserNameList`, `claimTime`, `claimType`, `allocationStatus` |
| 是否私海 | `isInPrivate`, `isInPrivateList`, `isInPrivateStr` |

## 当前停点

当前停在真实导出前。

当前已经完成查询参数名确认、只读 total 校验和导出统计预检。

下一步仍然不是自动导出，而是由人工确认筛选条件、`total=869`、导出统计结果和推荐导出路径。真实导出执行脚本和导出后文件校验脚本已经具备安全外壳，但没有执行下载。

## 前端源码参数映射

已下载并检查前端资源：

```text
/assets/main.80be2c19.js
/assets/index.deedcb68.js
/assets/public.d6df7e7e.js
```

`public.d6df7e7e.js` 显示列表接口为 `/customer/public/list`。

`index.deedcb68.js` 中公海客户页面的 `queryParams` 和 `Oe()` 转换逻辑显示：

| 业务条件 | API 参数 | 取值规则 |
|---|---|---|
| 所在城市 | `cityName` | 多选值用逗号拼接 |
| 区县 | `districtName` | 多选值用逗号拼接 |
| 一级品类 | `categoryName` | 多选值用逗号拼接 |
| 进店状态：未进店 | `poiState` | `0` |
| 认领状态：待认领 | `isInPrivateStr` | `0` |
| 有无电话：有电话 | `hasPhone` | `1` |
| 门店筛选：有效、误杀 | `storeFilterTags` | `0,2` |
| 跟进进度：未接通、未跟进 | `followProgress` | `未接通,未跟进` |
| 门店状态：营业中 | `closeStatus` | `0` |

注意：这是前端源码确认，不等同于导出验证。进入真实导出前仍需只读 total 校验和人工确认。

## 只读 total 校验

已用 `filter_count_dry_run.py --execute-readonly` 验证：

| 条件 | 值 |
|---|---|
| 城市 | 长沙市 |
| 区县 | 岳麓区 |
| 品类 | 餐饮、休闲娱乐 |
| 进店状态 | 未进店 |
| 认领状态 | 待认领 |
| 有无电话 | 有电话 |
| 门店筛选 | 有效、误杀 |
| 跟进进度 | 未接通、未跟进 |
| 门店状态 | 营业中 |
| 返回状态 | `code=200` |
| total | `869` |
| 客户明细 | 未保存完整客户行 |

运行目录：

```text
runs/2026-05-13/maijing-public-sea-filter-count-dry-run-长沙市-003/
```

## 导出预检 dry-run

已用 `export_preflight_dry_run.py --execute-readonly-stat` 验证：

| 项目 | 值 |
|---|---|
| 导出统计接口 | `/customer/public/export/stat` |
| 返回状态 | `code=200` |
| 返回消息 | `操作成功` |
| export stat total | `869` |
| 保存客户明细 | 否 |
| 调用同步导出 `/customer/public/export` | 否 |
| 调用异步导出 `/customer/public/export/async` | 否 |
| 推荐真实导出路径 | 同步下载 `/customer/public/export` |
| 推荐原因 | `869` 未超过前端阈值 `10000` |

运行目录：

```text
runs/2026-05-13/maijing-public-sea-export-preflight-dry-run-长沙市-002/
```

## 下一步建议

1. 人工确认筛选条件、筛选 total、导出统计 total 和推荐导出路径是否符合业务预期。
2. 如确认无误，再使用 `export_execute.py --execute-export`；脚本必须先校验人工确认记录，再调用 `/customer/public/export`。
3. 真实导出后必须运行 `validate_export_file.py` 校验文件行数、字段、城市、区县、品类和号码列，不通过则停在人工确认点。

## 新增脚本

`filter_count_dry_run.py` 是筛选计数固定入口：

- 默认只生成本地 API 查询计划，不访问真实网站。
- `--execute-readonly` 才会访问 `/customer/public/list` 读取 total。
- 有未映射筛选项时会拒绝访问真实 API。
- 有未验证参数时，必须显式加 `--allow-unverified-params` 才能做只读探测。

`manual_filter_capture.py` 用于确认页面筛选控件对应的 API 参数：

- 打开已登录公海客户页面。
- 由人工设置筛选条件并点击查询。
- 脚本捕获 `/customer/public/list` 请求参数和响应摘要。
- 输出 `suggested_param_mapping_candidates.json`，供人工确认后更新参数映射。

`export_preflight_dry_run.py` 已作为导出前固定入口：

- 默认只生成本地导出计划，不访问真实网站。
- `--execute-readonly-stat` 才会访问 `/customer/public/export/stat` 读取导出统计。
- 永远不调用 `/customer/public/export/async`。
- 永远不调用 `/customer/public/export` 下载文件。
- 生成 `export_preflight_checklist.md`，供人工确认后进入真实导出。

`export_execute.py` 已作为真实导出执行入口：

- 默认只生成执行计划和人工确认模板，不访问真实导出接口。
- 只有同时传入 `--execute-export`、`--auth-context` 和 `--confirmation-json` 才会尝试下载。
- 下载前会重新调用 `/customer/public/export/stat` 复查 total。
- 人工确认的 `expected_total` 必须等于下载前复查 total，否则拒绝导出。
- 当前只实现同步下载路径；如果推荐路径为 `async_task`，脚本会拒绝执行。
- 本轮跑过默认 dry-run 和基于预检目录的执行计划 dry-run，生成了运行目录，未下载真实文件。

`validate_export_file.py` 已作为导出后文件校验入口：

- 读取本地 CSV/XLSX，不访问迈鲸网站。
- 支持从导出运行目录读取筛选计划和 expected total。
- 校验导出行数、号码列、城市、区县、品类。
- 输出 `validation_report.json` 和 `validation_review_checklist.md`。
- 如果列名和默认候选不一致，可传 `--column-map` 扩展字段候选。

## 相关运行目录

```text
runs/2026-05-13/maijing-login-admin-004/
runs/2026-05-13/maijing-public-sea-filter-export-接口侦查-001/
runs/2026-05-13/maijing-public-sea-api-recon-接口侦查-001/
runs/2026-05-13/maijing-public-sea-filter-param-capture-长沙市-002/
runs/2026-05-13/maijing-public-sea-filter-count-dry-run-长沙市-003/
runs/2026-05-13/maijing-public-sea-export-preflight-dry-run-长沙市-002/
runs/2026-05-13/maijing-public-sea-export-execute-长沙市-001/
runs/2026-05-13/maijing-public-sea-export-execute-长沙市-002/
```
