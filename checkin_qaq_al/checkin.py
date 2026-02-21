#!/usr/bin/env python3
"""
qaq.al 自动签到 - CheckIn 类
PoW 签到流程: 获取 cf_clearance → 检查签到状态 → 获取挑战 → 计算 nonce → 提交签到
"""

import hashlib
import statistics
import sys
import time
from pathlib import Path

from curl_cffi import requests as curl_requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.get_cf_clearance import get_cf_clearance
from utils.get_headers import get_curl_cffi_impersonate
from utils.http_utils import proxy_resolve, response_resolve

BASE_URL = "https://sign.qaq.al"
BENCH_ROUNDS = 3
BENCH_DURATION_MS = 1200


def count_leading_zero_bits(hash_bytes: bytes) -> int:
    """计算哈希值的前导零位数"""
    count = 0
    for byte in hash_bytes:
        if byte == 0:
            count += 8
        else:
            b = byte
            while (b & 0x80) == 0 and count < 256:
                count += 1
                b <<= 1
            break
    return count


def benchmark_hps() -> int:
    """自动测算本机 HPS (Hashes Per Second)

    执行 3 轮测试，每轮 1.2 秒，取中位数。
    使用纯 Python hashlib SHA-256，与 WASM 算法一致。
    """
    print("⚙️ 正在测算本机算力 (HPS)...")
    challenge_prefix = b"benchmark:"
    samples = []

    for i in range(BENCH_ROUNDS):
        nonce = 0
        start = time.time()
        end_time = start + BENCH_DURATION_MS / 1000

        while time.time() < end_time:
            hashlib.sha256(challenge_prefix + str(nonce).encode()).digest()
            nonce += 1

        elapsed = time.time() - start
        hps = round(nonce / elapsed) if elapsed > 0 else 0
        samples.append(hps)
        print(f"  第 {i + 1}/{BENCH_ROUNDS} 轮: {hps:,} H/s")

    final_hps = round(statistics.median(samples))
    print(f"  最终算力 (中位数): {final_hps:,} H/s")
    return final_hps


def calculate_nonce(challenge: str, difficulty: int) -> dict:
    """计算满足难度要求的 nonce

    算法: SHA-256(challenge + ":" + str(nonce))，找到前导零位数 >= difficulty 的 nonce。
    """
    print(f"  开始计算 nonce (difficulty={difficulty})...")
    challenge_prefix = (challenge + ":").encode()
    nonce = 0
    start = time.time()
    last_report = 0

    while True:
        hash_bytes = hashlib.sha256(challenge_prefix + str(nonce).encode()).digest()
        leading = count_leading_zero_bits(hash_bytes)

        if nonce - last_report >= 100000:
            last_report = nonce
            elapsed = time.time() - start
            hps = round(nonce / elapsed) if elapsed > 0 else 0
            print(f"    进度: {nonce:,} | leading={leading} | {hps:,} H/s | {elapsed:.1f}s")

        if leading >= difficulty:
            elapsed = time.time() - start
            hps = round(nonce / elapsed) if elapsed > 0 else 0
            print(f"  ✓ 找到 nonce={nonce}, leading={leading}, 耗时 {elapsed:.1f}s, {hps:,} H/s")
            return {"nonce": nonce, "leading": leading, "hash": hash_bytes.hex(), "elapsed": round(elapsed, 1), "hps": hps}

        nonce += 1


class CheckIn:
    """qaq.al PoW 签到管理类"""

    def __init__(self, account_name: str, global_proxy: dict | None = None):
        self.account_name = account_name
        self.global_proxy = global_proxy
        self.http_proxy_config = proxy_resolve(global_proxy)
        # camoufox 代理格式与 curl_cffi 不同
        self.camoufox_proxy_config = global_proxy if global_proxy else None

    async def _get_cf_clearance(self) -> tuple[dict | None, dict | None]:
        """通过 Camoufox 浏览器获取 cf_clearance cookie 和浏览器指纹"""
        print(f"  {self.account_name}: 正在通过浏览器获取 cf_clearance...")
        try:
            cf_cookies, browser_headers = await get_cf_clearance(
                url=f"{BASE_URL}/app",
                account_name=self.account_name,
                proxy_config=self.camoufox_proxy_config,
            )
            if cf_cookies and "cf_clearance" in cf_cookies:
                print(f"  {self.account_name}: ✓ 已获取 cf_clearance")
            else:
                print(f"  {self.account_name}: ⚠️ 未获取到 cf_clearance")
            return cf_cookies, browser_headers
        except Exception as e:
            print(f"  {self.account_name}: ❌ 获取 cf_clearance 异常: {e}")
            return None, None

    def _build_session(
        self, sid: str, cf_cookies: dict | None, browser_headers: dict | None
    ) -> curl_requests.Session:
        """创建带 cookie 和浏览器指纹的 session"""
        # 根据浏览器指纹选择 impersonate
        impersonate = "chrome"
        if browser_headers and browser_headers.get("User-Agent"):
            impersonate = get_curl_cffi_impersonate(browser_headers["User-Agent"])
            print(f"  {self.account_name}: impersonate={impersonate}")

        session = curl_requests.Session(proxy=self.http_proxy_config, timeout=30, impersonate=impersonate)

        # 设置 cookies
        session.cookies.set("sid", sid, domain="sign.qaq.al")
        if cf_cookies:
            for name, value in cf_cookies.items():
                session.cookies.set(name, value, domain="sign.qaq.al")

        # 设置浏览器指纹 headers
        if browser_headers:
            session.headers.update(browser_headers)

        return session

    def _check_me(self, session: curl_requests.Session) -> dict | None:
        """调用 /api/me 检查当前用户状态和今日签到情况"""
        print(f"  {self.account_name}: 检查签到状态...")
        try:
            resp = session.get(f"{BASE_URL}/api/me", timeout=30)
            data = response_resolve(resp, "check_me", self.account_name)
            if data and "user" in data:
                user = data["user"]
                print(f"  {self.account_name}: ✓ 用户 {user.get('name', '?')} ({user.get('username', '?')})")
                if data.get("signedInToday"):
                    today = data.get("todaySignin", {})
                    print(
                        f"  {self.account_name}: ✓ 今日已签到 - "
                        f"奖励={today.get('reward_final', '?')} ({today.get('tier_name', '?')})"
                    )
                else:
                    print(f"  {self.account_name}: 今日未签到")
                return data
            error = data.get("error", "未知错误") if data else "响应解析失败"
            print(f"  ❌ {self.account_name}: 获取用户信息失败 - {error}")
            return None
        except Exception as e:
            print(f"  ❌ {self.account_name}: 获取用户信息异常 - {e}")
            return None

    def _get_challenge(self, session: curl_requests.Session, tier: int, hps: int) -> dict | None:
        """获取 PoW 挑战"""
        print(f"  {self.account_name}: 获取 tier={tier} 挑战 (hps={hps:,})...")
        try:
            resp = session.get(f"{BASE_URL}/api/pow/challenge", params={"tier": tier, "hps": hps}, timeout=30)
            data = response_resolve(resp, "get_challenge", self.account_name)
            if data and "challenge" in data:
                print(
                    f"  {self.account_name}: ✓ 挑战 ID={data['challengeId']}, "
                    f"difficulty={data['difficulty']}, 预计 {data.get('targetSeconds', '?')}s"
                )
                return data
            error = data.get("error", "未知错误") if data else "响应解析失败"
            print(f"  ❌ {self.account_name}: 获取挑战失败 - {error}")
            return None
        except Exception as e:
            print(f"  ❌ {self.account_name}: 获取挑战异常 - {e}")
            return None

    def _submit(self, session: curl_requests.Session, challenge_id: str, nonce: int, tier: int) -> dict | None:
        """提交签到"""
        print(f"  {self.account_name}: 提交签到...")
        try:
            resp = session.post(
                f"{BASE_URL}/api/pow/submit",
                json={"challengeId": challenge_id, "nonce": nonce, "tier": tier},
                timeout=30,
            )
            data = response_resolve(resp, "submit_checkin", self.account_name)
            if data and "rewardFinal" in data:
                print(
                    f"  {self.account_name}: ✓ 签到成功！"
                    f" 奖励={data['rewardFinal']} ({data.get('tierName', '')})"
                    f" 倍率={data.get('multiplier', '')}"
                )
                return data
            error = data.get("error", "未知错误") if data else "响应解析失败"
            print(f"  ❌ {self.account_name}: 提交失败 - {error}")
            return None
        except Exception as e:
            print(f"  ❌ {self.account_name}: 提交异常 - {e}")
            return None

    async def execute(self, sid: str, tier: int = 4) -> tuple[bool, dict]:
        """执行完整签到流程

        Args:
            sid: 用户 session ID (从 cookie 获取)
            tier: 难度等级 1-4，默认 4 (最高奖励)

        Returns:
            (是否成功, 签到结果或错误信息)
        """
        print(f"\n⏳ 开始处理 {self.account_name}")

        # 1. 获取 cf_clearance
        cf_cookies, browser_headers = await self._get_cf_clearance()

        session = self._build_session(sid, cf_cookies, browser_headers)
        try:
            # 2. 检查是否已签到
            me_data = self._check_me(session)
            if me_data and me_data.get("signedInToday"):
                today = me_data.get("todaySignin", {})
                print(f"  ✅ {self.account_name}: 今日已签到，跳过 PoW")
                return True, {
                    "reward_final": today.get("reward_final", "0"),
                    "tier_name": today.get("tier_name", ""),
                    "already_signed": True,
                }

            if not me_data:
                return False, {"error": "获取用户信息失败，可能 cf_clearance 无效"}

            # 3. 测算 HPS
            hps = benchmark_hps()

            # 4. 获取挑战
            challenge_data = self._get_challenge(session, tier, hps)
            if not challenge_data:
                return False, {"error": "获取挑战失败"}

            # 5. 计算 nonce
            result = calculate_nonce(challenge_data["challenge"], challenge_data["difficulty"])

            # 6. 提交签到
            submit_data = self._submit(session, challenge_data["challengeId"], result["nonce"], tier)
            if not submit_data:
                return False, {"error": "提交签到失败"}

            return True, {
                "reward_final": submit_data.get("rewardFinal", "0"),
                "reward_base": submit_data.get("rewardBase", "0"),
                "multiplier": submit_data.get("multiplier", "1"),
                "tier_name": submit_data.get("tierName", ""),
                "notes": submit_data.get("notes", ""),
                "pow_elapsed": result["elapsed"],
                "pow_hps": result["hps"],
            }
        except Exception as e:
            print(f"❌ {self.account_name}: 签到流程异常 - {e}")
            return False, {"error": f"签到流程异常: {str(e)}"}
        finally:
            session.close()
