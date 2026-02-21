#!/usr/bin/env python3
"""
qaq.al 自动签到脚本
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

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.notify import notify
from utils.balance_hash import load_balance_hash, save_balance_hash

load_dotenv(override=True)

CHECKIN_HASH_FILE = "balance_hash_qaq_al.txt"


def load_accounts() -> list[str] | None:
    """从环境变量加载 sid 列表"""
    sids_str = os.getenv("ACCOUNTS_QAQ_AL")
    if not sids_str:
        print("❌ ACCOUNTS_QAQ_AL 环境变量未设置")
        return None

    try:
        if sids_str.startswith("["):
            sids = json.loads(sids_str)
            if not isinstance(sids, list):
                print("❌ ACCOUNTS_QAQ_AL 必须是数组格式")
                return None
        else:
            sids = [s.strip() for s in sids_str.split(",") if s.strip()]

        valid = [s for s in sids if s]
        if not valid:
            print("❌ 未找到有效的 sid")
            return None

        print(f"✅ 已加载 {len(valid)} 个 sid")
        return valid
    except Exception as e:
        print(f"❌ 解析 ACCOUNTS_QAQ_AL 失败: {e}")
        return None


def generate_checkin_hash(results: dict) -> str:
    """生成签到结果的 hash"""
    if not results:
        return ""
    rewards = {}
    for key, info in results.items():
        if info:
            rewards[key] = info.get("reward_final", "0")
    data = json.dumps(rewards, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()[:16]


async def main():
    """运行签到流程"""
    print("🚀 qaq.al 自动签到脚本启动")
    print(f'🕒 执行时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    sids = load_accounts()
    if not sids:
        print("❌ 无法加载账号，程序退出")
        return 1

    print(f"⚙️ 共 {len(sids)} 个账号待处理")

    last_hash = load_balance_hash(CHECKIN_HASH_FILE)
    if last_hash:
        print(f"ℹ️ 上次签到 hash: {last_hash}")
    else:
        print("ℹ️ 首次运行，无历史 hash")

    # 代理配置
    global_proxy = None
    proxy_str = os.getenv("PROXY")
    if proxy_str:
        try:
            global_proxy = json.loads(proxy_str)
            print("⚙️ 已加载代理配置 (dict)")
        except json.JSONDecodeError:
            global_proxy = {"server": proxy_str}
            print(f"⚙️ 已加载代理配置: {proxy_str}")

    # 签到等级
    tier = int(os.getenv("QAQ_AL_TIER", "4"))
    print(f"⚙️ 签到难度等级: {tier}")

    success_count = 0
    total_count = len(sids)
    notification_content = []
    current_info = {}

    for i, sid in enumerate(sids):
        account_name = f"account_{i + 1}"

        if notification_content:
            notification_content.append("\n-------------------------------")

        try:
            print(f"🌀 处理 {account_name}")
            checkin = CheckIn(account_name, global_proxy=global_proxy)
            success, result = await checkin.execute(sid, tier=tier)

            if success:
                success_count += 1
                current_info[account_name] = result
                if result.get("already_signed"):
                    notification_content.append(
                        f"  📝 {account_name}: "
                        f"✅ 今日已签到 | 💰奖励 {result.get('reward_final', '?')} ({result.get('tier_name', '')})"
                    )
                else:
                    notification_content.append(
                        f"  📝 {account_name}: "
                        f"💰奖励 {result.get('reward_final', '?')} ({result.get('tier_name', '')}) | "
                        f"⚡PoW {result.get('pow_elapsed', '?')}s @ {result.get('pow_hps', 0):,} H/s"
                    )
            else:
                error_msg = result.get("error", "未知错误") if result else "未知错误"
                notification_content.append(f"  ❌ {account_name}: {error_msg}")

        except Exception as e:
            print(f"❌ {account_name} 处理异常: {e}")
            notification_content.append(f"  ❌ {account_name} 异常: {str(e)[:100]}...")

    # hash 比较
    current_hash = generate_checkin_hash(current_info)
    print(f"\nℹ️ 当前 hash: {current_hash}, 上次 hash: {last_hash}")

    need_notify = False
    if not last_hash:
        need_notify = True
        print("🔔 首次运行，发送通知")
    elif current_hash != last_hash:
        need_notify = True
        print("🔔 签到信息有变化，发送通知")
    else:
        print("ℹ️ 签到信息无变化，跳过通知")

    if need_notify and notification_content:
        summary = [
            "-------------------------------",
            "📢 签到结果统计:",
            f"🔵 成功: {success_count}/{total_count}",
            f"🔴 失败: {total_count - success_count}/{total_count}",
        ]

        if success_count == total_count:
            summary.append("✅ 全部签到成功！")
        elif success_count > 0:
            summary.append("⚠️ 部分签到成功")
        else:
            summary.append("❌ 全部签到失败")

        time_info = f'🕓 执行时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
        notify_content = "\n\n".join(
            [time_info, "📊 签到详情:\n" + "\n".join(notification_content), "\n".join(summary)]
        )

        print(notify_content)
        if success_count == total_count:
            notify.push_message("qaq.al 签到成功", notify_content, msg_type="text")
            print("🔔 成功通知已发送")
        else:
            notify.push_message("qaq.al 签到告警", notify_content, msg_type="text")
            print("🔔 告警通知已发送")

    if current_hash:
        save_balance_hash(CHECKIN_HASH_FILE, current_hash)

    sys.exit(0 if success_count > 0 else 1)


def run_main():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 运行异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_main()
