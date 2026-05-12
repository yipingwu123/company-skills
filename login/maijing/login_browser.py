"""
迈鲸浏览器登录 — 用 API token 注入 Cookie，直接打开已登录界面
"""
import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from login_api import login
from playwright.sync_api import sync_playwright


def open_maijing_browser(headless: bool = False):
    token = login()
    print(f"token 获取成功: {token[:40]}...")

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=headless, slow_mo=200)
    context = browser.new_context(viewport={"width": 1440, "height": 900})

    # 注入 Cookie
    context.add_cookies([{
        "name": "Admin-Token",
        "value": token,
        "domain": "mj-whale.com",
        "path": "/",
    }])

    page = context.new_page()
    page.goto("https://mj-whale.com/index", timeout=30000)
    page.wait_for_load_state("networkidle")

    print(f"✅ 已进入: {page.url}")
    page.screenshot(path="/tmp/maijing_loggedin2.png")
    print("截图保存到 /tmp/maijing_loggedin2.png")

    return pw, browser, context, page


if __name__ == "__main__":
    pw, browser, ctx, page = open_maijing_browser(headless=False)
    print("浏览器保持打开，按 Ctrl+C 退出")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        browser.close()
        pw.stop()
