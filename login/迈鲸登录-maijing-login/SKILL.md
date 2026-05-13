---
name: maijing-login
description: 登录迈鲸管理系统，为公海客户导出、商机导入、存量门店管理等流程提供认证上下文；优先使用 API 登录。
version: 0.2.0
metadata:
  cn_name: 迈鲸登录
  stage: api-login
  tags: [login, maijing, api]
---

# 迈鲸登录

## 这个 skill 是做什么的

登录迈鲸管理系统，并把登录后的认证信息提供给其他 skill 复用。

本 skill 只负责认证，不负责导出、导入、筛选、上传等业务动作。

## 当前阶段

当前已实现 API 登录：

1. 不保存明文账号密码。
2. 不访问业务页面。
3. 不执行导出、导入、上传等业务动作。
4. 登录后生成认证上下文，供后续 skill 复用。

## 什么时候用

- 需要导出公海客户。
- 需要导入商机名单。
- 需要进入存量门店管理。
- 需要执行批量运维下发。

## 输入

| 字段 | 说明 |
|---|---|
| account_type | 账号类型，例如 `admin`、`管理001` |
| account_ref | 本地 secrets 中的账号引用，不写明文密码 |
| mode | `api` 或 `browser` |
| dry_run | 第一阶段固定为 true |

## 输出

| 输出 | 说明 |
|---|---|
| auth_context | 登录上下文。API 模式包含 token/headers 引用，浏览器模式包含 browser context 引用 |
| evidence | 登录过程截图或接口响应，真实实现时保存到运行目录 |
| status | 登录状态 |

## 脚本入口

推荐使用本地 secrets：

```bash
python3 login/迈鲸登录-maijing-login/login_api.py \
  --account-ref admin \
  --batch 001
```

真实登录验证说明：

如果没有把账号放入 `.secrets/automation_accounts.json`，不要用占位或未经确认的账号直接跑真实登录。真实登录被安全审核拦截时，应先让用户确认凭据来源，或把凭据放入本地 secrets 后再执行。

也可以临时使用环境变量：

```bash
MAIJING_USERNAME="从本地填写" \
MAIJING_PASSWORD="从本地填写" \
python3 login/迈鲸登录-maijing-login/login_api.py \
  --account-ref admin \
  --batch 001
```

输出：

```text
runs/YYYY-MM-DD/maijing-login-admin-001/
  outputs/maijing_auth_context.json
  evidence/api_responses/login_summary.json
  state/run_state.json
  logs/run.log
```

## 后续实现原则

1. 优先使用 API 登录。
2. 如果 API 不稳定，再使用浏览器登录。
3. 账号密码必须从本地 secrets 或环境变量读取。
4. 登录成功后只返回认证上下文，不直接进入业务页面操作。
5. 认证失效时由调用方重新调用本 skill，不在业务 skill 内重复写登录逻辑。

## 人工确认规则

登录本身可以自动化。以下动作不属于本 skill，后续真实执行时需要人工确认：

1. 公海客户筛选条件进入真实系统前。
2. 导出结果行数异常时。
3. 上传或导入客户数据前。
4. 创建外呼任务前。

## 失败时怎么定位

查看运行目录：

```text
logs/run.log
evidence/screenshots/
evidence/api_responses/
state/run_state.json
```

常见问题：

| 问题 | 定位方式 |
|---|---|
| 账号引用不存在 | 检查本地 secrets 配置 |
| API 登录失败 | 查看接口响应证据 |
| 浏览器仍停留登录页 | 查看登录后截图和 cookie 状态 |
| token 过期 | 重新执行登录步骤 |

## 可恢复点

登录失败可以只重试登录步骤，不影响后续已经生成的输入文件、状态文件和本地处理结果。
