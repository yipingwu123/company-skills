# 自动化 Secrets 管理规范

本文件规定账号、密码、token、cookie、API key 等敏感信息的存放和引用方式。

## 原则

1. `SKILL.md` 不写明文账号密码。
2. 脚本源码不写明文账号密码。
3. 运行日志不输出完整 token、cookie、密码。
4. 账号只通过 `account_ref` 引用。
5. 本地 secrets 文件不提交版本管理。

## 推荐文件

本地创建：

```text
.secrets/automation_accounts.json
```

`.secrets/` 已被 `.gitignore` 忽略。

## 文件格式

```json
{
  "maijing": {
    "admin": {
      "username": "从本地填写",
      "password": "从本地填写"
    },
    "manager_001": {
      "username": "从本地填写",
      "password": "从本地填写"
    }
  },
  "dingkeduo": {
    "changsha": {
      "username": "从本地填写",
      "password": "从本地填写"
    }
  },
  "volcengine": {
    "iam_sub_user": {
      "tenant": "从本地填写",
      "username": "从本地填写",
      "password": "从本地填写"
    }
  }
}
```

## skill 中的引用方式

只写引用，不写明文：

```json
{
  "system": "maijing",
  "account_ref": "admin"
}
```

## 日志脱敏规则

日志里如果必须展示敏感值，只允许展示前后少量字符：

```text
token: abc123...xyz789
```

禁止：

```text
password: <明文密码>
cookie: 完整 cookie
token: 完整 token
```

## 人工交接规则

新 agent 接手时，只允许读取本规范和 skill 文档。除非用户明确要求并授权，不主动读取 `.secrets/` 内容。
