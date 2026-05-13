# 迈鲸商机导入接口侦查结论

**侦查日期**：2026-05-13  
**侦查方式**：Python urllib 只读探测（GET/OPTIONS）+ 菜单接口

---

## 核心结论

迈鲸商机导入是**文件导入**，不是 JSON REST API。流程：
1. 下载 xlsx 模板
2. 按模板格式填入数据
3. POST multipart/form-data 上传 xlsx 文件

---

## 接口清单

| 用途 | 方法 | 接口 |
|------|------|------|
| 下载导入模板 | GET | `/telesales/import/template` |
| 上传导入文件 | POST multipart | `/telesales/import/upload` |
| 查询导入历史 | GET | `/telesales/import/history?pageNum=1&pageSize=10` |

---

## 导入模板字段

模板列（`*` 为必填）：

| 列名 | 是否必填 | 说明 |
|------|----------|------|
| `客户来源(跟进阶段)*` | 必填 | 来源标识，有效值待确认 |
| `POI编码*` | 必填 | 百度 POI ID（`poi` 字段，如 `1026210038729281`） |
| `POI名称*` | 必填 | 门店名称（`storeName` 字段） |
| `一级品类名` | 可选 | 如"餐饮" |
| `二级品类名` | 可选 | |
| `区域` | 可选 | 所在区县 |
| `电话` | 可选 | |
| `商圈` | 可选 | |
| `跟进情况` | 可选 | |
| `跟进人` | 可选 | |
| `跟进时间` | 可选 | |
| `备注` | 可选 | |
| `跟进详情` | 可选 | |
| `详细地址` | 可选 | |
| `下发状态` | 可选 | |
| `城市` | 可选 | |
| `KPI线索类型` | 可选 | |
| `统计日期` | 可选 | |
| `客户意向等级` | 可选 | |

---

## 数据字段来源

从 `fetch_phone_by_id.py` 输出的 `mobile_list_{品类}.json`：
- `poi_code` → `POI编码`（`GET /customer/public/{id}` 返回的 `poi` 字段）
- `store_name` → `POI名称`（`storeName` 字段）

从外呼结果（火山外呼结果导出后）：
- 接通/有意向状态 → 用于筛选哪些客户要导入

---

## 导入历史观察

导入历史 `GET /telesales/import/history` 返回：
- `importType`: 已观察值仅有 `"normal"`（含 AI 外呼数据批次）
- `totalCount`, `successCount`, `failCount`
- `failReason`: JSON 数组，每项含 `{poi, reason, rowNum}`
- 常见失败原因: `"7天内有大象跟进记录"` (防重机制)

---

## 上传接口参数（推断）

```
POST /telesales/import/upload
Content-Type: multipart/form-data; boundary=xxx

file: <xlsx bytes>
importType: normal  （可能需要，也可能不用）
```

实际参数需在上传一次后从网络抓包确认。

---

## 待确认项

1. `客户来源(跟进阶段)*` 字段的有效枚举值（不能瞎填，否则可能被系统拒绝）
2. `importType` 参数是否需要在 POST body 或 query string 传递
3. 是否有 `importType=ai_follow` 与 `normal` 的区别（仅模板相同，功能可能不同）

建议：在真实上传前，先手动在界面操作一次"AI跟进记录导入"，抓包观察请求格式。

---

## 当前停点

`import_leads_dry_run.py` 已实现：
- dry-run：从火山结果文件 + mobile_list 生成待导入 xlsx（不上传）
- execute：生成 xlsx + POST 上传（需人工确认）

真实上传前需确认 `客户来源` 有效值。
