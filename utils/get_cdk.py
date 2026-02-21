#!/usr/bin/env python3
"""
CDK 获取模块

提供各个 provider 的 CDK 获取函数
同步函数返回 Generator[tuple[bool, dict], None, None]，每次 yield 一个元组：
  - (True, {"code": "xxx"}) 表示成功获取 CDK，code 可为空字符串表示不需要充值
  - (False, {"error": "error message"}) 表示失败，调用方应停止 topup
异步函数返回 AsyncGenerator[tuple[bool, dict], None]，格式同上
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from typing import TYPE_CHECKING, Generator, AsyncGenerator
from urllib.parse import urlparse, parse_qs

from camoufox.async_api import AsyncCamoufox
from curl_cffi import requests as curl_requests

from utils.browser_utils import take_screenshot, save_page_content_to_file
from utils.http_utils import proxy_resolve, response_resolve
from utils.get_headers import get_curl_cffi_impersonate
from utils.get_cf_clearance import get_cf_clearance

if TYPE_CHECKING:
    from utils.config import AccountConfig


def get_runawaytime_cdk(
    account_config: "AccountConfig",
) -> Generator[tuple[bool, dict], None, None]:
    """获取 runawaytime CDK（签到 + 大转盘）

    通过 fuli.hxi.me 签到和大转盘获取 CDK

    Args:
        account_config: 账号配置对象，需要包含 get_cdk_cookies 在 extra 中

    Yields:
        tuple[bool, dict]: (True, {"code": "xxx"}) 成功，(False, {"error": "msg"}) 失败
    """
    account_name = account_config.get_display_name()
    
    # 优先使用 fuli_cookies 兼容之前的配置，如果没有则使用 get_cdk_cookies 新的配置
    get_cdk_cookies = account_config.get("fuli_cookies") or account_config.get("get_cdk_cookies")

    if not get_cdk_cookies:
        print(f"❌ {account_name}: get_cdk_cookies not found in account config")
        yield False, {"error": "get_cdk_cookies not found in account config"}
        return

    # 代理优先级: 账号配置 > 全局配置
    proxy_config = account_config.proxy or account_config.get("global_proxy")
    http_proxy = proxy_resolve(proxy_config)

    try:
        session = curl_requests.Session(proxy=http_proxy, timeout=30)
        try:
            # 构建基础请求头
            headers = {
                "accept": "*/*",
                "accept-language": "en,en-US;q=0.9,zh;q=0.8",
                "cache-control": "no-cache",
                "pragma": "no-cache",
                "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            }

            # 设置 cookies
            session.cookies.update(get_cdk_cookies)
            session.cookies.set("i18next", "en")

            # ===== 第一部分：签到 =====
            # 先检查签到状态
            status_headers = headers.copy()
            status_headers.update(
                {
                    "referer": "https://fuli.hxi.me/",
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                }
            )

            status_response = session.get(
                "https://fuli.hxi.me/api/checkin/status",
                headers=status_headers,
                timeout=30,
            )

            already_checked_in = False
            if status_response.status_code == 200:
                status_data = response_resolve(status_response, "get_checkin_status", account_name)
                if status_data and status_data.get("checked"):
                    print(f"✅ {account_name}: Already checked in today")
                    already_checked_in = True

            if not already_checked_in:
                # 执行签到
                checkin_headers = headers.copy()
                checkin_headers.update(
                    {
                        "content-length": "0",
                        "origin": "https://fuli.hxi.me",
                        "referer": "https://fuli.hxi.me/",
                        "sec-fetch-dest": "empty",
                        "sec-fetch-mode": "cors",
                        "sec-fetch-site": "same-origin",
                    }
                )

                response = session.post(
                    "https://fuli.hxi.me/api/checkin",
                    headers=checkin_headers,
                    timeout=30,
                )

                if response.status_code in [200, 400]:
                    json_data = response_resolve(response, "execute_checkin", account_name)
                    if json_data is not None:
                        if json_data.get("success"):
                            code = json_data.get("code", "")
                            if code:
                                print(f"✅ {account_name}: Checkin successful! Code: {code}")
                                yield True, {"code": code}
                        else:
                            message = json_data.get("message", json_data.get("msg", ""))
                            if "already" in message.lower() or "已经" in message or "已签" in message:
                                print(f"✅ {account_name}: Already checked in today")
                            else:
                                print(f"❌ {account_name}: Checkin failed - {message}")

            # ===== 第二部分：大转盘 =====
            # 先检查大转盘状态
            wheel_status_headers = headers.copy()
            wheel_status_headers.update(
                {
                    "referer": "https://fuli.hxi.me/wheel",
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                }
            )

            wheel_status_response = session.get(
                "https://fuli.hxi.me/api/wheel/status",
                headers=wheel_status_headers,
                timeout=30,
            )

            remaining = 0
            if wheel_status_response.status_code == 200:
                status_data = response_resolve(wheel_status_response, "get_wheel_status", account_name)
                if status_data:
                    remaining = status_data.get("remaining", 0)
                    if remaining <= 0:
                        print(f"ℹ️ {account_name}: No wheel spins remaining")
                    else:
                        print(f"ℹ️ {account_name}: {remaining} wheel spin(s) remaining")

            # 执行大转盘（循环直到 remaining <= 0）
            if remaining > 0:
                wheel_headers = headers.copy()
                wheel_headers.update(
                    {
                        "content-length": "0",
                        "origin": "https://fuli.hxi.me",
                        "referer": "https://fuli.hxi.me/wheel",
                        "sec-fetch-dest": "empty",
                        "sec-fetch-mode": "cors",
                        "sec-fetch-site": "same-origin",
                    }
                )

                spin_count = 0

                while remaining > 0:
                    response = session.post(
                        "https://fuli.hxi.me/api/wheel",
                        headers=wheel_headers,
                        timeout=30,
                    )

                    if response.status_code in [200, 400]:
                        json_data = response_resolve(response, "execute_wheel", account_name)
                        if json_data is None:
                            break

                        if json_data.get("success"):
                            code = json_data.get("code", "")
                            # 从响应中更新 remaining
                            remaining = json_data.get("remaining", remaining - 1)
                            if code:
                                spin_count += 1
                                print(
                                    f"✅ {account_name}: Wheel spin #{spin_count} successful! Code: {code}, remaining: {remaining}"
                                )
                                yield True, {"code": code}
                                continue

                        message = json_data.get("message", json_data.get("msg", ""))
                        if (
                            "already" in message.lower()
                            or "已经" in message
                            or "次数" in message
                            or "no more" in message.lower()
                        ):
                            print(f"ℹ️ {account_name}: No more wheel spins remaining")
                            break

                        print(f"❌ {account_name}: Wheel spin #{spin_count + 1} failed - {message}")
                        break
                    else:
                        break

                if spin_count > 0:
                    print(f"✅ {account_name}: Total {spin_count} CDK(s) obtained from wheel")
        finally:
            session.close()
    except Exception as e:
        print(f"❌ {account_name}: Error getting runawaytime CDK - {e}")
        yield False, {"error": f"Error getting runawaytime CDK - {e}"}


async def _get_x666_user_token(
    account_name: str, username: str, password: str, proxy_config=None
) -> str | None:
    """通过 Linux.do OAuth 自动登录 up.x666.me 获取 userToken

    流程：
    1. 启动 Camoufox 浏览器
    2. 导航到 up.x666.me，检查 localStorage 是否已有 userToken
    3. 如果没有，调用 /api/auth/login 获取 auth_url
    4. 导航到 connect.linux.do 授权页面，登录并授权
    5. 等待重定向回 up.x666.me/?token=JWT_TOKEN
    6. 从 URL 参数或 localStorage 提取 userToken

    Args:
        account_name: 账号名称（用于日志）
        username: Linux.do 用户名
        password: Linux.do 密码
        proxy_config: 代理配置

    Returns:
        userToken 字符串，失败返回 None
    """

    def is_jwt_valid(token: str) -> bool:
        """验证 JWT token 是否有效（未过期）"""
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return False

            # 解码 payload（添加 padding）
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += '=' * padding

            payload = json.loads(base64.b64decode(payload_b64))
            exp = payload.get('exp')

            if not exp:
                return False

            # 检查是否过期（exp 是秒级时间戳）
            return exp > time.time()
        except Exception:
            return False

    username_hash = hashlib.sha256(username.encode()).hexdigest()[:8]
    cache_file_path = f"storage-states/x666_up_{username_hash}.json"

    print(f"ℹ️ {account_name}: Attempting auto-login to up.x666.me via Linux.do")

    try:
        proxy_args = {}
        if proxy_config:
            http_proxy = proxy_resolve(proxy_config)
            if http_proxy:
                proxy_args["proxy"] = {"server": http_proxy} if isinstance(http_proxy, str) else http_proxy

        async with AsyncCamoufox(
            headless=False,
            humanize=True,
            locale="en-US",
            os="macos",
            config={"forceScopeAccess": True},
            **proxy_args,
        ) as browser:
            storage_state = cache_file_path if os.path.exists(cache_file_path) else None
            if storage_state:
                print(f"ℹ️ {account_name}: Found x666 cache file, restoring storage state")
            else:
                print(f"ℹ️ {account_name}: No x666 cache file found, starting fresh")

            context = await browser.new_context(storage_state=storage_state)
            page = await context.new_page()

            try:
                # Step 1: 导航到 up.x666.me 并检查是否已有 userToken
                await page.goto("https://up.x666.me/", wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                # 检查 localStorage 中是否已有 userToken（缓存有效时）
                existing_token = await page.evaluate("() => localStorage.getItem('userToken')")
                if existing_token:
                    print(f"ℹ️ {account_name}: Found existing userToken in localStorage, validating...")
                    if is_jwt_valid(existing_token):
                        print(f"✅ {account_name}: Cached userToken is valid")
                        await context.storage_state(path=cache_file_path)
                        return existing_token
                    else:
                        print(f"⚠️ {account_name}: Cached userToken expired, need to re-login")

                # Step 2: 调用 /api/auth/login 获取 auth_url
                print(f"ℹ️ {account_name}: No cached token, fetching auth_url from /api/auth/login")
                auth_result = await page.evaluate("""
                    async () => {
                        try {
                            const resp = await fetch('/api/auth/login');
                            const data = await resp.json();
                            return data.auth_url || null;
                        } catch (e) {
                            return null;
                        }
                    }
                """)

                if not auth_result:
                    print(f"❌ {account_name}: Failed to get auth_url from /api/auth/login")
                    await take_screenshot(page, "x666_auth_url_failed", account_name)
                    return None

                print(f"ℹ️ {account_name}: Got auth_url, navigating to Linux.do authorization page")

                # Step 3: 导航到 connect.linux.do 授权页面
                await page.goto(auth_result, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                current_url = page.url

                # 检查是否已经被重定向回 up.x666.me（已授权过）
                if "up.x666.me" in current_url and "token=" in current_url:
                    print(f"✅ {account_name}: Already authorized, redirected back with token")
                else:
                    # 检查是否出现授权按钮（已登录 linux.do）
                    allow_btn = await page.query_selector('a[href^="/oauth2/approve"]')

                    if not allow_btn:
                        # 未登录，需要填写用户名密码
                        print(f"ℹ️ {account_name}: Not logged in to Linux.do, performing login")

                        # 如果在 linux.do 登录页面
                        if "linux.do" in current_url:
                            # 可能需要先去登录页面
                            if "/login" not in current_url:
                                await page.goto("https://linux.do/login", wait_until="domcontentloaded")
                                await page.wait_for_timeout(3000)

                            await page.fill("#login-account-name", username)
                            await page.wait_for_timeout(2000)
                            await page.fill("#login-account-password", password)
                            await page.wait_for_timeout(2000)
                            await page.click("#login-button")
                            await page.wait_for_timeout(10000)

                            await save_page_content_to_file(
                                page, "x666_linuxdo_login_result", account_name, prefix="x666"
                            )

                            # 登录后重新访问授权页面
                            await page.goto(auth_result, wait_until="domcontentloaded")
                            await page.wait_for_timeout(3000)
                        else:
                            # 在 connect.linux.do 页面但需要登录
                            login_form = await page.query_selector("#login-account-name")
                            if login_form:
                                await page.fill("#login-account-name", username)
                                await page.wait_for_timeout(2000)
                                await page.fill("#login-account-password", password)
                                await page.wait_for_timeout(2000)
                                await page.click("#login-button")
                                await page.wait_for_timeout(10000)

                        # 再次检查授权按钮
                        allow_btn = await page.query_selector('a[href^="/oauth2/approve"]')

                    # 点击授权按钮
                    if allow_btn:
                        print(f"ℹ️ {account_name}: Clicking authorize button")
                        await allow_btn.click()
                        await page.wait_for_timeout(5000)

                # Step 4: 等待重定向回 up.x666.me
                try:
                    await page.wait_for_url("**/up.x666.me/**", timeout=30000)
                except Exception:
                    pass  # 可能已经在 up.x666.me 了

                await page.wait_for_timeout(3000)
                current_url = page.url

                # Step 5: 从 URL 参数提取 token
                user_token = None
                if "token=" in current_url:
                    parsed = urlparse(current_url)
                    params = parse_qs(parsed.query)
                    token_list = params.get("token", [])
                    if token_list:
                        user_token = token_list[0]
                        print(f"✅ {account_name}: Got userToken from URL parameter")

                # 如果 URL 中没有，尝试从 localStorage 获取
                if not user_token:
                    try:
                        await page.wait_for_timeout(3000)
                        user_token = await page.evaluate("() => localStorage.getItem('userToken')")
                        if user_token:
                            print(f"✅ {account_name}: Got userToken from localStorage")
                    except Exception:
                        pass

                if user_token:
                    # 保存 storage_state 用于下次缓存
                    await context.storage_state(path=cache_file_path)
                    print(f"✅ {account_name}: Storage state saved for x666 up")
                    return user_token
                else:
                    print(f"❌ {account_name}: Failed to obtain userToken from up.x666.me")
                    await take_screenshot(page, "x666_token_failed", account_name)
                    return None

            except Exception as e:
                print(f"❌ {account_name}: Error during x666 auto-login: {e}")
                await take_screenshot(page, "x666_auto_login_error", account_name)
                return None
            finally:
                await page.close()
                await context.close()

    except Exception as e:
        print(f"❌ {account_name}: Failed to launch browser for x666 auto-login: {e}")
        return None


async def get_x666_cdk(
    account_config: "AccountConfig",
) -> AsyncGenerator[tuple[bool, dict], None]:
    """执行 x666 每日抽奖（直接充值到账户）

    通过 up.x666.me 抽奖，奖励直接充值到账户，不返回 CDK
    此函数作为 get_cdk 使用，成功时返回空 code 表示不需要充值

    支持两种方式获取 access_token：
    1. 手动配置 access_token（向后兼容）
    2. 通过 linux.do 账号自动登录 up.x666.me 获取 userToken

    Args:
        account_config: 账号配置对象

    Yields:
        tuple[bool, dict]: (True, {"code": ""}) 成功（不需要充值），(False, {"error": "msg"}) 失败
    """
    account_name = account_config.get_display_name()
    proxy_config = account_config.proxy or account_config.get("global_proxy")

    # 1. 优先使用手动配置的 access_token（向后兼容）
    access_token = account_config.get("access_token")

    # 2. 如果没有手动配置，尝试通过 linux.do 自动登录获取
    if not access_token:
        linux_do_accounts = account_config.linux_do
        if linux_do_accounts and isinstance(linux_do_accounts, list) and len(linux_do_accounts) > 0:
            ld_account = linux_do_accounts[0]
            access_token = await _get_x666_user_token(
                account_name, ld_account.username, ld_account.password, proxy_config
            )
        else:
            print(f"❌ {account_name}: No access_token and no linux.do accounts configured")
            yield False, {"error": "access_token not found and no linux.do accounts available"}
            return

    # 3. 自动登录也失败则报错
    if not access_token:
        print(f"❌ {account_name}: Failed to obtain access_token via auto-login")
        yield False, {"error": "Failed to obtain access_token via auto-login"}
        return

    http_proxy = proxy_resolve(proxy_config)

    try:
        session = curl_requests.Session(proxy=http_proxy, timeout=30)
        try:
            # 构建基础请求头
            headers = {
                "accept": "*/*",
                "accept-language": "en,en-US;q=0.9,zh;q=0.8,en-CN;q=0.7,zh-CN;q=0.6",
                "cache-control": "no-cache",
                "pragma": "no-cache",
                "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            }

            session.cookies.set("i18next", "en")

            # 先获取用户信息，检查是否可以抽奖
            status_headers = headers.copy()
            status_headers.update(
                {
                    "authorization": f"Bearer {access_token}",
                    "referer": "https://up.x666.me/",
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                }
            )

            status_response = session.get(
                "https://up.x666.me/api/checkin/status",
                headers=status_headers,
                timeout=30,
            )

            if status_response.status_code == 200:
                status_data = response_resolve(status_response, "get_checkin_status", account_name)
                if status_data and status_data.get("success"):
                    # API 响应格式：can_spin 和 today_record 直接在顶层
                    # {"success":true,"can_spin":false,"today_record":{...},"total_quota":...}
                    can_spin = status_data.get("can_spin", False)

                    if not can_spin:
                        # 今天已经抽过，显示今日奖励
                        today_record = status_data.get("today_record")
                        today_quota = today_record.get("quota_amount", 0)
                        today_quota_display = round(today_quota / 500, 2)
                        print(f"✅ {account_name}: Already spun today, today's prize: {today_quota_display}")
                        # 已经抽过，返回成功但 code 为空表示不需要充值
                        yield True, {"code": ""}
                        return
                else:
                    error_msg = status_data.get("message", "Unknown error") if status_data else "Invalid response"
                    print(f"❌ {account_name}: Failed to get checkin status: {error_msg}")
                    yield False, {"error": f"Failed to get checkin status: {error_msg}"}
                    return
            else:
                print(f"❌ {account_name}: Failed to get checkin status, HTTP {status_response.status_code}")
                yield False, {"error": f"Failed to get checkin status, HTTP {status_response.status_code}"}
                return

            # 执行抽奖
            spin_headers = headers.copy()
            spin_headers.update(
                {
                    "authorization": f"Bearer {access_token}",
                    "content-length": "0",
                    "content-type": "application/json",
                    "origin": "https://up.x666.me",
                    "referer": "https://up.x666.me/",
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                }
            )

            response = session.post(
                "https://up.x666.me/api/checkin/spin",
                headers=spin_headers,
                timeout=30,
            )

            if response.status_code in [200, 400]:
                json_data = response_resolve(response, "execute_spin", account_name)
                if json_data is None:
                    return

                if json_data.get("success"):
                    # 新 API 响应格式：直接充值到账户
                    # {"success":true,"level":6,"times":150,"quota":75000,"label":"150次","new_balance":33497000,"message":"恭喜获得 150次！"}
                    message = json_data.get("message", "")
                    
                    print(f"✅ {account_name}: Spin successful! {message}")
                    # 成功，返回空 code 表示不需要充值（奖励已直接充值到账户）
                    yield True, {"code": ""}
                    return

                message = json_data.get("message", json_data.get("msg", ""))
                if "already" in message.lower() or "已签到" in message:
                    print(f"✅ {account_name}: Already spun today, {message}")
                    # 已经抽过，返回成功但 code 为空
                    yield True, {"code": ""}
                    return

                print(f"❌ {account_name}: Spin failed - {message}")
                yield False, {"error": f"Spin failed - {message}"}
            else:
                print(f"❌ {account_name}: Spin failed, HTTP {response.status_code}")
                yield False, {"error": f"Spin failed, HTTP {response.status_code}"}
        finally:
            session.close()
    except Exception as e:
        print(f"❌ {account_name}: Error executing x666 spin - {e}")
        yield False, {"error": f"Error executing x666 spin - {e}"}


async def get_b4u_cdk(
    account_config: "AccountConfig",
) -> AsyncGenerator[tuple[bool, dict], None]:
    """获取 b4u 抽奖 CDK（异步生成器）

    通过 tw.b4u.qzz.io/luckydraw 抽奖获取 CDK
    需要先获取 cf_clearance cookie 才能访问接口

    Args:
        account_config: 账号配置对象，需要包含 get_cdk_cookies 在 extra 中

    Yields:
        tuple[bool, dict]: (True, {"code": "xxx"}) 成功，(False, {"error": "msg"}) 失败
    """
    account_name = account_config.get_display_name()
    get_cdk_cookies = account_config.get("get_cdk_cookies")

    if not get_cdk_cookies:
        print(f"❌ {account_name}: get_cdk_cookies not found in account config")
        yield False, {"error": "get_cdk_cookies not found in account config"}
        return

    # 代理优先级: 账号配置 > 全局配置
    proxy_config = account_config.proxy or account_config.get("global_proxy")
    http_proxy = proxy_resolve(proxy_config)

    # 获取 cf_clearance cookie（使用公共方法，直接 await）
    print(f"ℹ️ {account_name}: Getting cf_clearance for tw.b4u.qzz.io...")
    try:
        cf_cookies, browser_headers = await get_cf_clearance(
            url="https://tw.b4u.qzz.io/luckydraw",
            account_name=account_name,
            proxy_config=proxy_config,
        )
    except Exception as e:
        print(f"❌ {account_name}: Failed to get cf_clearance: {e}")
        yield False, {"error": f"Failed to get cf_clearance: {e}"}
        return

    if not cf_cookies or "cf_clearance" not in cf_cookies:
        print(f"❌ {account_name}: Failed to get cf_clearance for tw.b4u.qzz.io, cannot proceed")
        yield False, {"error": "Failed to get cf_clearance for tw.b4u.qzz.io"}
        return

    # 根据浏览器指纹选择 impersonate
    user_agent = browser_headers.get("User-Agent", "") if browser_headers else ""
    impersonate = get_curl_cffi_impersonate(user_agent) if user_agent else "firefox135"

    try:
        session = curl_requests.Session(impersonate=impersonate, proxy=http_proxy, timeout=30)
        try:
            # 构建基础请求头，使用浏览器指纹
            if browser_headers:
                headers = {
                    "Accept": "text/x-component",
                    "Accept-Language": "en,en-US;q=0.9,zh;q=0.8,en-CN;q=0.7,zh-CN;q=0.6",
                    "Content-Type": "text/plain;charset=UTF-8",
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                    "User-Agent": browser_headers.get("User-Agent", ""),
                    "Origin": "https://tw.b4u.qzz.io",
                    "Referer": "https://tw.b4u.qzz.io/luckydraw",
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                }
                # 添加 Client Hints（如果有）
                if "sec-ch-ua" in browser_headers:
                    headers.update(
                        {
                            "sec-ch-ua": browser_headers.get("sec-ch-ua", ""),
                            "sec-ch-ua-mobile": browser_headers.get("sec-ch-ua-mobile", "?0"),
                            "sec-ch-ua-platform": browser_headers.get("sec-ch-ua-platform", ""),
                            "sec-ch-ua-platform-version": browser_headers.get("sec-ch-ua-platform-version", ""),
                            "sec-ch-ua-arch": browser_headers.get("sec-ch-ua-arch", ""),
                            "sec-ch-ua-bitness": browser_headers.get("sec-ch-ua-bitness", ""),
                            "sec-ch-ua-full-version": browser_headers.get("sec-ch-ua-full-version", ""),
                            "sec-ch-ua-full-version-list": browser_headers.get("sec-ch-ua-full-version-list", ""),
                            "sec-ch-ua-model": browser_headers.get("sec-ch-ua-model", '""'),
                        }
                    )
            else:
                headers = {
                    "Accept": "text/x-component",
                    "Accept-Language": "en,en-US;q=0.9,zh;q=0.8,en-CN;q=0.7,zh-CN;q=0.6",
                    "Content-Type": "text/plain;charset=UTF-8",
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
                    "Origin": "https://tw.b4u.qzz.io",
                    "Referer": "https://tw.b4u.qzz.io/luckydraw",    
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",            
                }

            # 设置 cookies（合并 cf_clearance 和用户 cookies）
            session.cookies.update(cf_cookies)
            session.cookies.update(get_cdk_cookies)
            session.cookies.set("i18next", "en")

            # Next.js Server Actions 需要的 next-router-state-tree header
            next_router_state_tree = "%5B%22%22%2C%7B%22children%22%3A%5B%22(dashboard)%22%2C%7B%22children%22%3A%5B%22luckydraw%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2Fluckydraw%22%2C%22refresh%22%5D%7D%5D%7D%5D%7D%2Cnull%2Cnull%2Ctrue%5D"

            # ===== 第一步：检查抽奖状态 =====
            status_headers = headers.copy()
            status_headers["next-action"] = "7a7a7bf7f7c47cf1a8351d225a4338b0f017cd35"
            status_headers["next-router-state-tree"] = next_router_state_tree

            status_response = session.post(
                "https://tw.b4u.qzz.io/luckydraw",
                headers=status_headers,
                data="[]",
                timeout=30,
            )

            import json

            remaining = 0
            if status_response.status_code == 200:
                # 解析响应，格式如: 0:["$@1",["xxx",null]]\n1:1
                # 其中 "1:N" 的 N 表示剩余抽奖次数
                response_text = status_response.text
                print(f"ℹ️ {account_name}: Luckydraw status response: {response_text[:200]}")

                # 解析剩余次数
                lines = response_text.strip().split("\n")
                for line in lines:
                    if line.startswith("1:"):
                        try:
                            remaining = int(line[2:])
                            print(f"ℹ️ {account_name}: Remaining draws: {remaining}")
                        except ValueError:
                            # 不是数字，可能是其他格式
                            print(f"⚠️ {account_name}: Could not parse remaining draws, trying once")
                            remaining = 1
                        break
            else:
                print(f"⚠️ {account_name}: Failed to check luckydraw status, HTTP {status_response.status_code}")
                # 即使状态检查失败，也尝试抽奖一次
                remaining = 1

            if remaining <= 0:
                print(f"ℹ️ {account_name}: No draws remaining today")
                # 没有抽奖次数，返回成功但 code 为空
                yield True, {"code": ""}
                return

            # ===== 第二步：循环执行抽奖直到次数用完 =====
            draw_headers = headers.copy()
            draw_headers["next-action"] = "cfc5966b4123c674815ce067b6b8894545c15604"
            draw_headers["next-router-state-tree"] = next_router_state_tree

            draw_count = 0
            while remaining > 0:
                response = session.post(
                    "https://tw.b4u.qzz.io/luckydraw",
                    headers=draw_headers,
                    data='[{"excludeThankYou":false}]',
                    timeout=30,
                )

                if response.status_code == 200:
                    response_text = response.text
                    print(f"ℹ️ {account_name}: Luckydraw response #{draw_count + 1}: {response_text[:300]}")

                    # 解析响应，格式如:
                    # 0:["$@1",["xxx",null]]
                    # 1:{"success":true,"message":"...","prize":{...},"redemptionCode":"xxx"}

                    # 尝试从响应中提取 JSON 部分
                    # 查找以 "1:" 开头的行
                    lines = response_text.strip().split("\n")
                    for line in lines:
                        if line.startswith("1:"):
                            json_str = line[2:]  # 去掉 "1:" 前缀
                            try:
                                json_data = json.loads(json_str)
                                if isinstance(json_data, dict):
                                    if json_data.get("success"):
                                        redemption_code = json_data.get("redemptionCode", "")
                                        prize = json_data.get("prize", {})
                                        prize_name = prize.get("name", "Unknown")
                                        message = json_data.get("message", "")

                                        if redemption_code:
                                            draw_count += 1
                                            remaining -= 1
                                            print(
                                                f"✅ {account_name}: Luckydraw #{draw_count} successful! Prize: {prize_name}, Code: {redemption_code}, remaining: {remaining}"
                                            )
                                            yield True, {"code": redemption_code}
                                        else:
                                            print(
                                                f"⚠️ {account_name}: Luckydraw successful but no redemption code: {message}"
                                            )
                                            remaining -= 1
                                    else:
                                        message = json_data.get("message", "Unknown error")
                                        print(f"❌ {account_name}: Luckydraw failed - {message}")
                                        yield False, {"error": f"Luckydraw failed - {message}"}
                                        remaining = 0  # 失败时停止
                                        break
                            except json.JSONDecodeError:
                                # 如果不是 JSON，可能是数字（如 "1:0" 表示已抽完）
                                try:
                                    new_remaining = int(json_str)
                                    if new_remaining == 0:
                                        print(f"ℹ️ {account_name}: No more draws remaining")
                                        remaining = 0
                                except ValueError:
                                    pass
                                continue
                            break
                    else:
                        # 如果没有找到有效的 JSON 响应
                        print(f"⚠️ {account_name}: Could not parse luckydraw response")
                        remaining = 0
                else:
                    print(f"❌ {account_name}: Luckydraw failed - HTTP {response.status_code}")
                    yield False, {"error": f"Luckydraw failed - HTTP {response.status_code}"}
                    remaining = 0

            if draw_count > 0:
                print(f"✅ {account_name}: Total {draw_count} CDK(s) obtained from luckydraw")
        finally:
            session.close()
    except Exception as e:
        print(f"❌ {account_name}: Error getting b4u CDK - {e}")
        yield False, {"error": f"Error getting b4u CDK - {e}"}
