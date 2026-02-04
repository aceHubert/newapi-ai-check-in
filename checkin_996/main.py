#!/usr/bin/env python3
"""
996 hub 自动签到脚本
"""

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from checkin import CheckIn

# Add parent directory to Python path to find utils module
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv(override=True)

from utils.notify import notify
from utils.balance_hash import load_balance_hash, save_balance_hash

CHECKIN_HASH_FILE = "balance_hash_996.txt"


def load_access_tokens() -> list[str] | None:
    """从环境变量加载 access tokens"""
    tokens_str = os.getenv("ACCOUNTS_996")
    if not tokens_str:
        print("❌ ACCOUNTS_996 environment variable not found")
        return None

    try:
        # 支持多种格式
        if tokens_str.startswith("["):
            # JSON 数组格式
            tokens = json.loads(tokens_str)
            if not isinstance(tokens, list):
                print("❌ ACCOUNTS_996 must be an array format")
                return None
        else:
            # 逗号分隔格式
            tokens = [token.strip() for token in tokens_str.split(",") if token.strip()]

        # 验证每个 token
        valid_tokens = []
        for i, token in enumerate(tokens):
            if not token:
                print(f"❌ Token {i + 1} is empty")
                continue
            valid_tokens.append(token)

        if not valid_tokens:
            print("❌ No valid tokens found")
            return None

        print(f"✅ Loaded {len(valid_tokens)} access token(s)")
        return valid_tokens
    except Exception as e:
        print(f"❌ Failed to parse ACCOUNTS_996: {e}")
        return None


def generate_checkin_hash(checkin_results: dict) -> str:
    """生成所有账号签到数据的总hash"""
    if not checkin_results:
        return ""

    # 将所有账号的 total_rewards_usd 合并
    all_rewards = {}
    for account_key, checkin_info in checkin_results.items():
        if checkin_info:
            all_rewards[account_key] = checkin_info.get("total_rewards_usd", "0")

    rewards_json = json.dumps(all_rewards, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rewards_json.encode("utf-8")).hexdigest()[:16]


async def main():
    """运行签到流程"""
    print("🚀 996 hub auto check-in script started")
    print(f'🕒 Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    # 加载 access tokens
    tokens = load_access_tokens()
    if not tokens:
        print("❌ Unable to load access tokens, program exits")
        return 1

    print(f"⚙️ Found {len(tokens)} token(s) to process")

    # 加载签到前 hash
    last_checkin_hash = load_balance_hash(CHECKIN_HASH_FILE)
    if last_checkin_hash:
        print(f"ℹ️ Last check-in hash: {last_checkin_hash}")
    else:
        print("ℹ️ No previous check-in hash found (first run)")

    # 加载全局代理配置
    global_proxy = None
    proxy_str = os.getenv("PROXY")
    if proxy_str:
        try:
            # 尝试解析为 JSON
            global_proxy = json.loads(proxy_str)
            print("⚙️ Global proxy loaded from PROXY environment variable (dict format)")
        except json.JSONDecodeError:
            # 如果不是 JSON，则视为字符串
            global_proxy = {"server": proxy_str}
            print(f"⚙️ Global proxy loaded from PROXY environment variable: {proxy_str}")

    # 执行签到
    success_count = 0
    total_count = len(tokens)
    notification_content = []
    current_checkin_info = {}

    for i, token in enumerate(tokens):
        account_name = f"account_{i + 1}"

        if len(notification_content) > 0:
            notification_content.append("\n-------------------------------")

        try:
            print(f"🌀 Processing {account_name}")

            # 创建 CheckIn 实例
            checkin = CheckIn(account_name, global_proxy=global_proxy)

            # 使用 token 执行签到
            success, user_info = await checkin.execute(token)

            if success:
                success_count += 1
                print(f"✅ {account_name}: Check-in successful")

                # 收集签到后信息
                current_checkin_info[f"account_{i + 1}"] = user_info
                notification_content.append(
                    f"  📝 {account_name}: "
                    f"🔥连续签到{user_info.get('continuous_days', 0)}天 | "
                    f"📈总签到{user_info.get('total_checkins', 0)}次 | "
                    f"💰${user_info.get('total_rewards_usd', '0')}"
                )
            else:
                print(f"❌ {account_name}: Check-in failed")
                error_msg = user_info.get("error", "Unknown error") if user_info else "Unknown error"
                notification_content.append(f"❌ {account_name}: {error_msg}")

        except Exception as e:
            print(f"❌ {account_name} processing exception: {e}")
            notification_content.append(f"❌ {account_name} Exception: {str(e)[:100]}...")

    # 生成当前签到信息的 hash
    current_checkin_hash = generate_checkin_hash(current_checkin_info)
    print(f"\nℹ️ Current check-in hash: {current_checkin_hash}, Last check-in hash: {last_checkin_hash}")

    # 决定是否需要发送通知
    need_notify = False
    if not last_checkin_hash:
        # 首次运行，发送通知
        need_notify = True
        print("🔔 First run detected, will send notification")
    elif current_checkin_hash != last_checkin_hash:
        # 签到信息有变化，发送通知
        need_notify = True
        print("🔔 Check-in info changes detected, will send notification")
    else:
        print("ℹ️ No check-in info changes detected, skipping notification")

    # 构建通知内容
    if need_notify and notification_content:
        # 构建通知内容
        summary = [
            "-------------------------------",
            "📢 Check-in result statistics:",
            f"🔵 Success: {success_count}/{total_count}",
            f"🔴 Failed: {total_count - success_count}/{total_count}",
        ]

        if success_count == total_count:
            summary.append("✅ All accounts check-in successful!")
        elif success_count > 0:
            summary.append("⚠️ Some accounts check-in successful")
        else:
            summary.append("❌ All accounts check-in failed")

        time_info = f'🕓 Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'

        notify_content = "\n\n".join(
            [time_info, "📊 Check-in Summary:\n" + "\n".join(notification_content), "\n".join(summary)]
        )

        print(notify_content)
        # 发送通知
        if success_count == total_count:
            notify.push_message("996 hub Check-in Success", notify_content, msg_type="text")
            print("🔔 Success notification sent")
        else:
            notify.push_message("996 hub Check-in Alert", notify_content, msg_type="text")
            print("🔔 Alert notification sent")

    # 保存当前签到 hash
    if current_checkin_hash:
        save_balance_hash(CHECKIN_HASH_FILE, current_checkin_hash)

    # 设置退出码
    sys.exit(0 if success_count > 0 else 1)


def run_main():
    """运行主函数的包装函数"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Program interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error occurred during program execution: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_main()
