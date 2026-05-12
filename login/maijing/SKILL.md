---
name: maijing-login
description: "登录迈鲸管理系统（mj-whale.com），获取认证 token 或打开已登录浏览器，供后续 skill 复用。"
version: 1.0.0
metadata:
  hermes:
    tags: [login, maijing, 迈鲸, token, browser]
    related_skills: []
---

# 迈鲸登录 Skill

## 这个 skill 是做什么的

迈鲸（mj-whale.com）是公司的核心管理系统，几乎所有业务操作（导出数据、导入商机、批量运维下发等）都需要先登录。

本 skill 封装了迈鲸的登录逻辑，其他 agent / skill 直接调用它，**不需要自己处理登录、验证码、Cookie**。

提供两种模式：
- **API 模式**：拿到 token，用于直接调用迈鲸后台接口（不开浏览器，速度快、省资源）
- **浏览器模式**：拿到已登录的 Playwright page 对象，用于需要在页面上点击操作的场景

---

## 环境要求

| 依赖 | 版本 | 安装命令 |
|------|------|---------|
| Python | 3.8+ | 系统自带 |
| playwright | 任意 | `pip3 install playwright && python3 -m playwright install chromium` |

> 如果已经安装过，跳过安装步骤。

---

## 文件说明

```
login/maijing/
├── SKILL.md          ← 当前文件，使用说明
├── login_api.py      ← 核心模块：API 方式获取 token
└── login_browser.py  ← 浏览器模块：打开已登录的 Chromium
```

---

## 使用方式一：API 模式（推荐，不需要浏览器）

**适用场景**：需要调用迈鲸接口获取/提交数据，但不需要在页面上操作。

### 直接运行（验证是否能登录）

```bash
python3 /Users/wuyiping/skills/login/maijing/login_api.py
```

成功输出：
```
✅ 登录成功！token: eyJhbGciOiJIUzUxMiJ9...
后续请求头已就绪，可直接传给下一个 skill 使用
```

### 在其他脚本中导入使用

```python
import sys
sys.path.insert(0, "/Users/wuyiping/skills/login/maijing")
from login_api import login, get_headers

# 第一步：登录，拿 token
token = login()

# 第二步：构造请求头
headers = get_headers(token)
# headers = {
#   "Authorization": "Bearer eyJhbGci...",
#   "Content-Type": "application/json",
#   "User-Agent": "Mozilla/5.0"
# }

# 第三步：用 headers 调用任意迈鲸接口
import urllib.request, json
req = urllib.request.Request(
    "https://mj-whale.com/prod-api/你的接口路径",
    headers=headers
)
with urllib.request.urlopen(req) as r:
    data = json.loads(r.read())
```

---

## 使用方式二：浏览器模式（需要在页面操作时使用）

**适用场景**：需要在迈鲸网页上点击、填表、下载文件等操作。

### 直接运行（会弹出 Chromium 窗口）

```bash
python3 /Users/wuyiping/skills/login/maijing/login_browser.py
```

Chromium 打开后会停留在 `https://mj-whale.com/index`（已登录状态），按 `Ctrl+C` 退出。

### 在其他脚本中导入使用

```python
import sys
sys.path.insert(0, "/Users/wuyiping/skills/login/maijing")
from login_browser import open_maijing_browser

# 打开已登录的浏览器，拿到 page 对象
pw, browser, context, page = open_maijing_browser(headless=False)
# headless=True 表示不弹出窗口（后台运行）

# page 已停留在 /index，直接操作即可，例如：
page.goto("https://mj-whale.com/customer/publicSeas")  # 跳转到公海客户页面
page.locator("...").click()                             # 点击某个按钮

# 操作完毕后关闭
browser.close()
pw.stop()
```

---

## 账号信息

| 字段 | 值 |
|------|----|
| 网址 | https://mj-whale.com |
| 账号 | admin |
| 密码 | 123456 |

> 注意：SOP 中部分操作需要使用 `管理001` / `123456` 账号（如商机导入），届时在调用处单独传参。

---

## 技术说明（供开发者参考）

- 登录接口：`POST https://mj-whale.com/prod-api/login`
- 验证码接口：`GET https://mj-whale.com/prod-api/captchaImage`（返回 uuid）
- 验证码后端不做严格校验，`code` 字段填任意值（如 `"1"`）即可登录
- token 以 Cookie `Admin-Token` 形式注入浏览器，与前端行为一致
- token 有效期未知，若后续接口返回 `401`，重新调用 `login()` 即可

---

## 常见报错

| 报错 | 原因 | 解决 |
|------|------|------|
| `urllib.error.URLError: timed out` | 网络不通或迈鲸服务器故障 | 检查网络，重试 |
| `Exception: 登录失败: {'code': 500, ...}` | 账号密码错误 | 检查账号密码 |
| `ModuleNotFoundError: playwright` | 未安装 playwright | 运行 `pip3 install playwright && python3 -m playwright install chromium` |
| 浏览器打开后还是登录页 | Cookie 注入失败 | 检查 token 是否为空，重新运行 |
