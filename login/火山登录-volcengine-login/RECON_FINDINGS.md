# 火山引擎智能外呼 侦查结论

侦查日期：2026-05-13  
侦查账号：主账号 `2112175672`，IAM 子用户 `DXZG-1`

---

## 登录方式

- 地址：`https://console.volcengine.com/auth/login`
- 选择「IAM 子用户登录」
- 字段：主账号 ID、子用户名、密码
- 登录成功后页面跳转至控制台，cookie 中含 `csrfToken`

**鉴权头**：所有 API 请求需携带  
```
X-Csrf-Token: <decodeURIComponent(csrfToken cookie)>
```

---

## API 基础信息

```
Base URL: /console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01
Content-Type: application/json
鉴权: X-Csrf-Token header（从 csrfToken cookie 读取，需 decodeURIComponent）
```

---

## 接口清单

### QueryScript（GET）

获取所有话术列表。

```
GET /QueryScript?Env=prod&WithHealthInfo=true
```

响应结构：
```json
{
  "Result": {
    "Scripts": [
      {
        "Script": "llm_xxx",
        "Name": "话术名",
        "Health": true,
        "DsParamSet": ["name"],
        "DsParamNameSet": ["店名"],
        "DsParamIsRequired": {"店名": true},
        "DsParamType": {"店名": "String"}
      }
    ]
  }
}
```

---

### QueryTaskList（POST）

```
POST /QueryTaskList
Body: {"Offset": 0, "Limit": 10}
```

响应结构：
```json
{
  "Result": {
    "Total": 335,
    "DataList": [...]
  }
}
```

---

### QueryTaskDetail（POST）

```
POST /QueryTaskDetail
Body: {"TaskId": "任务ID字符串"}
```

---

### QueryNumberPool（POST）

获取号码池列表。

```
POST /QueryNumberPool
Body: {}
```

响应：
```json
{
  "Result": {
    "Pools": [
      {
        "NumberPoolNo": "250",
        "NumberPoolName": "塔外",
        "NumberRecords": [{"Number": "20260325", "Concurrency": -1}],
        "NumberSelectRules": [{"Rule": "根据号码归属地选号", "Value": 5}]
      }
    ]
  }
}
```

---

### CreateTask（POST）

```
POST /CreateTask
Body: {
  "Name": "任务名称",
  "Script": "llm_xxx_xxx",
  "PhoneList": [{"Phone": "139xxxxxxxx", "Params": {"name": "店名"}}],
  "DefaultPhoneParams": {},
  "NumberPoolNo": "250",
  "NumberList": [],
  "SelectNumberRule": 5,
  "StartTime": "2026-05-14 09:00:00",
  "EndTime": "2026-05-14 20:00:00",
  "RingAgainTimes": 2,
  "RingAgainInterval": 30,
  "ForbidTimeList": [],
  "Concurrency": 10,
  "IsEncryption": false,
  "EncryptionType": 0,
  "InPausedStatus": false,
  "EnableDynamicAppend": false,
  "CallOverStopTask": false,
  "ConcurrentModel": 1,
  "EnableMakeCallCheck": false
}
```

`ConcurrentModel: 1` = 独占模式。

---

## 话术 Script ID 映射表

| 话术名称 | Script ID | Health | 动态参数 |
|---|---|---|---|
| cdb1.1（休娱）（其他）| `llm_gstj_bicdj` | ✅ | 店名（必填）|
| mtcdb | `llm_uzuj_bibia` | ❌ | 无 |
| wdhs | `llm_xzsi_bifjd` | ❌ | 上一轮播报内容（必填）|
| 丽人 | `llm_khrs_bifjj` | ✅ | 无 |
| 休娱和其他 | `llm_divs_bigai` | ✅ | 无 |
| 购物 | `llm_mzsi_bigba` | ✅ | 无 |
| 餐饮 | `llm_fgzo_bifje` | ✅ | 无 |
| 餐饮 副本 | `llm_ihjh_bihic` | ✅ | 店名（必填）|

> Health=false 的话术不可用于新建任务。

---

## 号码池映射

| 号码池名称 | NumberPoolNo | 号码 ID | 选号规则 |
|---|---|---|---|
| 塔外 | `250` | `20260325` | 根据号码归属地选号 |
| 塔思奇 | `220` | `20260305` | 根据号码归属地选号 |

---

## 品类与话术的对应关系（业务规则）

基于话术名称推断（需与业务人员确认）：

| 迈鲸品类 | 推荐话术 | Script ID |
|---|---|---|
| 餐饮 | 餐饮 | `llm_fgzo_bifje` |
| 休闲娱乐 | 休娱和其他 | `llm_divs_bigai` |
| 购物 | 购物 | `llm_mzsi_bigba` |
| 丽人 | 丽人 | `llm_khrs_bifjj` |

---

## 导出中心

- 地址：`https://console.volcengine.com/aibot/export-center`
- 任务结果可在此页面按任务筛选后导出

---

## 已验证

- [x] IAM 子用户登录成功
- [x] csrfToken 提取和 X-Csrf-Token 头工作正常
- [x] QueryScript GET 接口，返回 8 个话术，Script ID 全部已记录
- [x] QueryTaskList，total=335
- [x] QueryTaskDetail，含 Script 字段
- [x] QueryNumberPool，返回 2 个号码池
- [x] CreateTask 参数结构已从 JS bundle 提取
