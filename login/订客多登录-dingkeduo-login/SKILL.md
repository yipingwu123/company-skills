---
name: dingkeduo-login
description: 登录订客多系统，为历史呼叫、录音和电销效率相关导出提供认证上下文。
version: 0.1.0
metadata:
  cn_name: 订客多登录
  stage: dry-run
  tags: [login, dingkeduo, dry-run]
---

# 订客多登录

## 这个 skill 是做什么的

登录订客多系统。后续供“订客多历史呼叫导出”和“录音导出”复用。

## 当前阶段

第一版只做 dry-run 设计，不执行真实登录。

## 什么时候用

- 需要导出历史呼叫记录。
- 需要按日期筛选呼叫数据。
- 需要批量导出录音。

## 输入

| 字段 | 说明 |
|---|---|
| account_ref | 账号引用，正式版从本地 secrets 读取 |
| target_url | 订客多系统地址 |
| headless | 是否无头浏览器 |

## 输出

| 输出 | 说明 |
|---|---|
| browser_context | 已登录浏览器上下文 |
| auth_state | 可复用认证状态 |

## 重点风险

当前已知痛点是日期筛选不准。后续实现日期筛选时，不能只依赖页面点击成功，必须校验页面条件和导出文件日期列。

## 失败时怎么定位

查看：

```text
evidence/screenshots/
evidence/page_state.json
logs/run.log
```

## 可恢复点

登录失败可以重试。日期筛选失败应停在日期筛选步骤，不应从登录开始重跑。
