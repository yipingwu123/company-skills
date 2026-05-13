---
name: browser-helpers
description: 为必须使用浏览器的系统提供稳定定位、日期控件校验、截图证据和页面状态读取，避免依赖坐标点击。
version: 0.1.0
metadata:
  cn_name: 浏览器辅助
  stage: dry-run
  tags: [browser, playwright, selector, screenshot, dry-run]
---

# 浏览器辅助

## 这个 skill 是做什么的

封装浏览器操作的通用规则。重点是用页面文字、label、role、placeholder、DOM 状态定位，不使用坐标点击。

## 什么时候用

- 系统没有可用 API，必须页面操作时。
- 日期控件、筛选项、导出按钮容易点错时。
- 需要截图留证据时。

## 输入

| 字段 | 说明 |
|---|---|
| page | Playwright page 对象 |
| action | 点击、填值、选择日期、读取状态等动作 |
| expected_state | 操作后期望页面状态 |

## 输出

| 文件或数据 | 说明 |
|---|---|
| evidence/screenshots/*.png | 操作前后截图 |
| evidence/page_state.json | 页面关键状态 |
| logs/run.log | 中文操作日志 |

## 订客多日期筛选要求

订客多日期筛选必须做到：

1. 设置日期前截图。
2. 设置日期后读取页面当前日期。
3. 导出后校验文件里的日期列。
4. 页面日期和文件日期都符合目标日期，才算成功。

## 失败时怎么定位

查看：

```text
evidence/screenshots/
evidence/page_state.json
logs/run.log
```

## 可恢复点

浏览器步骤失败后，不默认刷新重来。先保存页面状态和截图，再由编排流程决定是否重试当前步骤。
