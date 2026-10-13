"""User-run login window for the existing MediaCrawler collection adapter.

The persistent profile stays on this computer. No cookies or account details are
exported. This program never closes an existing browser or its pages.
"""
import argparse
import asyncio
import json
import inspect
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
LOGIN_PAGES = (
    ('小红书', 'https://www.xiaohongshu.com/explore'),
    ('抖音', 'https://www.douyin.com/'),
    ('知乎', 'https://www.zhihu.com/signin'),
    ('B站', 'https://www.bilibili.com/'),
)


def debugger_endpoint(port):
    # Resolve locally ourselves: newer Chrome may reject Playwright's trailing
    # /json/version/ probe, and local DevTools must never pass through a proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{port}/json/version', timeout=2) as response:
        data = json.loads(response.read(65536))
    endpoint = data.get('webSocketDebuggerUrl', '')
    target = urlsplit(endpoint)
    if not data.get('Browser') or target.scheme != 'ws' or target.hostname != '127.0.0.1' or target.port != port or target.username or target.password or not target.path.startswith('/devtools/browser/'):
        raise ValueError('不是可信的本机Chrome调试接口。')
    return endpoint


def browser_health(port):
    try:
        return bool(debugger_endpoint(port))
    except Exception:
        return False


async def connect_existing_browser(playwright, port):
    method=playwright.chromium.connect_over_cdp
    options={'timeout':15000}
    # Newer Playwright can preserve the user's default context settings.
    if 'no_defaults' in inspect.signature(method).parameters:
        options['no_defaults']=True
    return await method(debugger_endpoint(port),**options)


def select_browser_port(preferred):
    if browser_health(preferred):
        return preferred
    for candidate in range(preferred, preferred + 20):
        try:
            with socket.socket() as probe:
                if os.name == 'nt':
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(('127.0.0.1', candidate))
            return candidate
        except OSError:
            continue
    raise OSError('没有空闲的本机调试端口。')


def start_collection_browser(port):
    # Never replace a different process using this port or stop the user's Chrome.
    with socket.socket() as probe:
        if os.name == 'nt':
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(('127.0.0.1', port))
    chrome = Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe'
    if not chrome.is_file():
        raise FileNotFoundError('Chrome未找到，请检查安装目录。')
    profile = Path(os.environ['LOCALAPPDATA']) / 'GradHeat' / 'collection-chrome'
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([str(chrome), f'--remote-debugging-port={port}',
        '--remote-debugging-address=127.0.0.1', f'--user-data-dir={profile}',
        '--no-first-run', '--no-default-browser-check', '--new-window', 'about:blank'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if browser_health(port):
            return
        time.sleep(.5)
    raise TimeoutError('Chrome调试连接未就绪，请保留窗口并重新运行启动器。')


async def open_login_pages(port):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await connect_existing_browser(p, port)
        if not browser.contexts:
            raise RuntimeError('浏览器没有可用会话。')
        context = browser.contexts[0]
        for name, url in LOGIN_PAGES:
            host = urlsplit(url).hostname
            existing = next((page for page in context.pages if
                urlsplit(page.url).hostname == host), None)
            page = existing or await context.new_page()
            if existing is None:
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=20000)
                    print(f'{name}：已打开，请在浏览器完成登录。', flush=True)
                except Exception:
                    print(f'{name}：页面加载未完成，请在该标签刷新。', flush=True)
            else:
                print(f'{name}：保留现有标签，请确认已登录。', flush=True)
        # The user's button asks to display the login window, including when it
        # already exists in the background. Keep all existing pages intact.
        await page.bring_to_front()
        # Stop only this Playwright connection. Never browser.close/context.close.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    config_path = ROOT / 'contracts/social-collection.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    port = int(config['cdp_port'])
    if args.check_only:
        print(json.dumps({'port': port, 'browser_available': browser_health(port)}))
        return
    if not browser_health(port):
        selected = select_browser_port(port)
        if selected != port:
            print(f'{port}已占用，采集窗口改用空闲端口{selected}。', flush=True)
            port = selected
        start_collection_browser(port)
        if config['cdp_port'] != port:
            config = json.loads(config_path.read_text(encoding='utf-8'))
            config['cdp_port'] = port
            temporary = config_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temporary.replace(config_path)
    print(f'调试连接就绪：http://127.0.0.1:{port}/json/version', flush=True)
    sys.path.insert(0, str(Path(config['collector']).resolve()))
    asyncio.run(open_login_pages(port))
    print('登录后保留此Chrome窗口；回到采集页面确认登录，选择JSON开始。不要发送Cookie、密码或验证码。', flush=True)


if __name__ == '__main__':
    main()
