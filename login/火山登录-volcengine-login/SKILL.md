---
name: volcengine-login
description: 登录火山引擎控制台，为火山外呼任务创建和结果导出提供认证上下文。
version: 0.1.0
metadata:
  cn_name: 火山登录
  stage: dry-run
  tags: [login, volcengine, dry-run]
---

# 火山登录

## 这个 skill 是做什么的

登录火山引擎控制台。后续供“火山外呼任务创建”和“火山外呼结果导出”复用。

## 当前阶段

第一版只做 dry-run 设计，不执行真实登录。

## 什么时候用

- 需要进入火山智能外呼任务管理。
- 需要创建外呼任务。
- 需要导出外呼任务结果。

## 输入

| 字段 | 说明 |
|---|---|
| login_type | 登录方式，例如 IAM 子用户 |
| account_ref | 账号引用，正式版从本地 secrets 读取 |
| headless | 是否无头浏览器 |

## 输出

| 输出 | 说明 |
|---|---|
| browser_context | 已登录浏览器上下文 |
| auth_state | 可复用认证状态 |

## 人工确认规则

登录本身可自动化，但创建任务、设置并发、设置拨打时间前必须人工确认。

## 失败时怎么定位

查看：

```text
evidence/screenshots/
logs/run.log
```

## 可恢复点

登录失败可以直接重试，不影响业务数据。
