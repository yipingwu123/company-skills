"""
迈鲸 API 登录 — 无需浏览器，直接获取 token
用法: python3 login_api.py
"""
import urllib.request
import json

BASE = "https://mj-whale.com/prod-api"
USERNAME = "admin"
PASSWORD = "123456"


def get_captcha() -> dict:
    """获取验证码 uuid（图片不需要真正识别）"""
    req = urllib.request.Request(f"{BASE}/captchaImage",
                                  headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def login() -> str:
    """登录并返回 token"""
    captcha = get_captcha()
    uuid = captcha["uuid"]

    payload = json.dumps({
        "username": USERNAME,
        "password": PASSWORD,
        "code": "1",      # 后端不严格验证验证码
        "uuid": uuid,
    }).encode()

    req = urllib.request.Request(
        f"{BASE}/login",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())

    if data.get("code") == 200:
        token = data["token"]
        print(f"✅ 登录成功！token: {token[:40]}...")
        return token
    else:
        raise Exception(f"登录失败: {data}")


def get_headers(token: str) -> dict:
    """返回带 token 的请求头，供后续 API 调用复用"""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }


if __name__ == "__main__":
    token = login()
    headers = get_headers(token)
    print(f"\n后续请求头已就绪，可直接传给下一个 skill 使用")
