#!/usr/bin/env python3
"""
配置管理模块
"""

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Generator, AsyncGenerator, List, Literal

from utils.get_check_in_status import newapi_check_in_status
from utils.get_cdk import (
    get_runawaytime_cdk,
    get_x666_cdk,
    get_b4u_cdk,
)


# 前向声明 AccountConfig 类型，用于类型注解
# 实际的 AccountConfig 类在后面定义
# 定义 CDK 获取函数的类型：接收 AccountConfig 参数，返回 Generator[tuple[bool, dict], None, None]
# 每次 yield 一个元组：
#   - (True, {"code": "xxx"}) 表示成功获取 CDK，code 可为空字符串表示不需要充值
#   - (False, {"error": "error message"}) 表示失败，调用方应停止 topup
CdkGetterFunc = Callable[["AccountConfig"], Generator[tuple[bool, dict], None, None]]
AsyncCdkGetterFunc = Callable[["AccountConfig"], AsyncGenerator[tuple[bool, dict], None]]

# 签到状态查询函数类型：接收 ProviderConfig 和 AccountConfig 参数，返回 bool（今日是否已签到）
# 函数签名: (provider_config, account_config, cookies, headers) -> bool
# 代理配置从 account_config.proxy 或 account_config.get("global_proxy") 获取
# headers 中已包含 api_user_key，无需单独传递 api_user
CheckInStatusFunc = Callable[["ProviderConfig", "AccountConfig", dict, dict], bool]


@dataclass
class ProviderConfig:
    """Provider 配置"""

    name: str
    origin: str
    login_path: str = "/login"
    status_path: str = "/api/status"
    auth_state_path: str = "api/oauth/state"
    check_in_path: str | Callable[[str, str | int], str] | None = None
    check_in_status: bool | CheckInStatusFunc = False  # 签到状态查询：True=标准检查，False=不检查，Callable=自定义函数
    user_info_path: str = "/api/user/self"
    topup_path: str | None = "/api/user/topup"
    get_cdk: CdkGetterFunc | AsyncCdkGetterFunc | None = None
    api_user_key: str = "new-api-user"
    github_client_id: str | None = None
    github_auth_path: str = "/api/oauth/github"
    github_auth_redirect_path: str = "/oauth/**"  # OAuth 回调路径匹配模式，支持通配符
    linuxdo_client_id: str | None = None
    linuxdo_auth_path: str = "/api/oauth/linuxdo"
    linuxdo_auth_redirect_path: str = "/oauth/**"  # OAuth 回调路径匹配模式，支持通配符
    aliyun_captcha: bool = False
    bypass_method: Literal["waf_cookies", "cf_clearance"] | None = None
    isCustomize: bool = False  # 是否为自定义 provider（从环境变量加载）

    @classmethod
    def from_dict(cls, name: str, data: dict, is_customize: bool = False) -> "ProviderConfig":
        """从字典创建 ProviderConfig

        配置格式:
        - 基础: {"origin": "https://example.com"}
        - 完整: {"origin": "https://example.com", "login_path": "/login", "api_user_key": "x-api-user", "bypass_method": "waf_cookies", ...}

        Args:
            name: provider 名称
            data: 配置数据字典
            is_customize: 是否为自定义 provider（从环境变量加载）
        """
        return cls(
            name=name,
            origin=data["origin"],
            login_path=data.get("login_path", "/login"),
            status_path=data.get("status_path", "/api/status"),
            auth_state_path=data.get("auth_state_path", "api/oauth/state"),
            check_in_path=data.get("check_in_path"),
            check_in_status=data.get("check_in_status", False),
            user_info_path=data.get("user_info_path", "/api/user/self"),
            topup_path=data.get("topup_path", "/api/user/topup"),
            get_cdk=data.get("get_cdk"),  # 函数类型无法从 JSON 解析，需要代码中设置
            api_user_key=data.get("api_user_key", "new-api-user"),
            github_client_id=data.get("github_client_id"),
            github_auth_path=data.get("github_auth_path", "/api/oauth/github"),
            github_auth_redirect_path=data.get("github_auth_redirect_path", "/oauth/**"),
            linuxdo_client_id=data.get("linuxdo_client_id"),
            linuxdo_auth_path=data.get("linuxdo_auth_path", "/api/oauth/linuxdo"),
            linuxdo_auth_redirect_path=data.get("linuxdo_auth_redirect_path", "/oauth/**"),
            aliyun_captcha=data.get("aliyun_captcha", False),
            bypass_method=data.get("bypass_method"),
            isCustomize=is_customize,
        )

    def needs_waf_cookies(self) -> bool:
        """判断是否需要获取 WAF cookies"""
        return self.bypass_method == "waf_cookies"

    def needs_cf_clearance(self) -> bool:
        """判断是否需要获取 Cloudflare cf_clearance cookie"""
        return self.bypass_method == "cf_clearance"

    def needs_manual_check_in(self) -> bool:
        """判断是否需要手动调用签到接口"""
        return self.check_in_path is not None

    def needs_manual_topup(self) -> bool:
        """判断是否需要手动执行充值（通过 CDK）

        当同时配置了 topup_path 和 get_cdk 时，需要执行 execute_topup
        """
        return self.topup_path is not None and self.get_cdk is not None

    def get_login_url(self) -> str:
        """获取登录 URL"""
        return f"{self.origin}{self.login_path}"

    def get_status_url(self) -> str:
        """获取状态 URL"""
        return f"{self.origin}{self.status_path}"

    def get_auth_state_url(self) -> str:
        """获取认证状态 URL"""
        return f"{self.origin}{self.auth_state_path}"

    def get_check_in_url(self, user_id: str | int) -> str | None:
        """获取签到 URL

        如果 check_in_path 是函数，则调用函数生成带签名的 URL

        Args:
            user_id: 用户 ID

        Returns:
            str | None: 签到 URL，如果不需要签到则返回 None
        """
        if not self.check_in_path:
            return None

        # 如果是函数，则调用函数生成 URL
        if callable(self.check_in_path):
            return self.check_in_path(self.origin, user_id)

        # 否则拼接路径
        return f"{self.origin}{self.check_in_path}"

    def get_check_in_status_func(self) -> CheckInStatusFunc | None:
        """获取签到状态查询函数

        Returns:
            如果 check_in_status 为 True，返回标准的 newapi_check_in_status 函数
            如果 check_in_status 为 callable，返回该函数
            否则返回 None
        """
        if self.check_in_status is True:
            return newapi_check_in_status
        if callable(self.check_in_status):
            return self.check_in_status
        return None

    def get_user_info_url(self) -> str:
        """获取用户信息 URL"""
        return f"{self.origin}{self.user_info_path}"

    def get_topup_url(self) -> str | None:
        """获取充值 URL"""
        if not self.topup_path:
            return None
        return f"{self.origin}{self.topup_path}"

    def get_github_auth_url(self) -> str:
        """获取 GitHub 认证 URL"""
        return f"{self.origin}{self.github_auth_path}"

    def get_github_auth_redirect_pattern(self) -> str:
        """获取 GitHub OAuth 回调 URL 匹配模式

        返回用于 page.wait_for_url() 的匹配模式，支持通配符 **
        例如: "**https://example.com/oauth/**" 或 "**https://example.com/oauth-redirect.html**"
        """
        return f"**{self.origin}{self.github_auth_redirect_path}"

    def get_linuxdo_auth_url(self) -> str:
        """获取 LinuxDo 认证 URL"""
        return f"{self.origin}{self.linuxdo_auth_path}"

    def get_linuxdo_auth_redirect_pattern(self) -> str:
        """获取 LinuxDo OAuth 回调 URL 匹配模式

        返回用于 page.wait_for_url() 的匹配模式，支持通配符 **
        例如: "**https://example.com/oauth/**" 或 "**https://example.com/oauth-redirect.html**"
        """
        return f"**{self.origin}{self.linuxdo_auth_redirect_path}"


@dataclass
class OAuthAccountConfig:
    """OAuth 账号配置（用于 linux.do 和 github）"""

    username: str
    password: str

    @classmethod
    def from_dict(cls, data: dict) -> "OAuthAccountConfig":
        """从字典创建 OAuthAccountConfig"""
        return cls(
            username=data.get("username", ""),
            password=data.get("password", ""),
        )


@dataclass
class AccountConfig:
    """账号配置"""

    provider: str = "anyrouter"
    cookies: dict | str = ""
    api_user: str = ""
    name: str | None = None
    linux_do: List["OAuthAccountConfig"] | None = None  # 改为列表类型
    github: List["OAuthAccountConfig"] | None = None  # 改为列表类型
    proxy: dict | None = None
    extra: dict = field(default_factory=dict)  # 存储额外的配置字段

    @classmethod
    def from_dict(
        cls,
        data: dict,
        linux_do_accounts: List["OAuthAccountConfig"] | None = None,
        github_accounts: List["OAuthAccountConfig"] | None = None,
    ) -> "AccountConfig":
        """从字典创建 AccountConfig

        Args:
            data: 账号配置字典
            linux_do_accounts: 解析后的 Linux.do OAuth 账号列表（可选）
            github_accounts: 解析后的 GitHub OAuth 账号列表（可选）
        """
        provider = data.get("provider", "anyrouter")
        name = data.get("name")

        # Handle different authentication types
        cookies = data.get("cookies", "")
        proxy = data.get("proxy")

        # 提取已知字段
        known_keys = {"provider", "name", "cookies", "api_user", "linux.do", "github", "proxy"}
        # 收集额外的配置字段
        extra = {k: v for k, v in data.items() if k not in known_keys}

        return cls(
            provider=provider,
            name=name if name else None,
            cookies=cookies,
            api_user=data.get("api_user", ""),
            linux_do=linux_do_accounts,
            github=github_accounts,
            proxy=proxy,
            extra=extra,
        )

    def get_display_name(self, index: int = 0) -> str:
        """获取显示名称

        如果设置了 name 则返回 name，否则返回 "{provider} {index + 1}"
        """
        return self.name if self.name else f"{self.provider} {index + 1}"

    def get(self, key: str, default=None):
        """获取配置值，优先从已知属性获取，否则从 extra 中获取"""
        if hasattr(self, key) and key != "extra":
            value = getattr(self, key)
            return value if value is not None else default
        return self.extra.get(key, default)


@dataclass
class AppConfig:
    """应用配置"""

    providers: Dict[str, ProviderConfig]
    accounts: List["AccountConfig"] = field(default_factory=list)
    linux_do_accounts: List["OAuthAccountConfig"] = field(default_factory=list)  # 全局 Linux.do 账号列表
    github_accounts: List["OAuthAccountConfig"] = field(default_factory=list)  # 全局 GitHub 账号列表
    global_proxy: Dict | None = None

    @classmethod
    def load_from_env(
        cls,
        providers_env: str = "PROVIDERS",
        accounts_env: str = "ACCOUNTS",
        linux_do_accounts_env: str = "ACCOUNTS_LINUX_DO",
        github_accounts_env: str = "ACCOUNTS_GITHUB",
        proxy_env: str = "PROXY",
    ) -> "AppConfig":
        """从环境变量加载配置

        Args:
            providers_env: 自定义 providers 配置的环境变量名称，默认为 "PROVIDERS"
            accounts_env: 账号配置的环境变量名称，默认为 "ACCOUNTS"
            linux_do_accounts_env: Linux.do 账号配置的环境变量名称，默认为 "ACCOUNTS_LINUX_DO"
            github_accounts_env: GitHub 账号配置的环境变量名称，默认为 "ACCOUNTS_GITHUB"
            proxy_env: 全局代理配置的环境变量名称，默认为 "PROXY"
        """
        # 加载 providers 配置
        providers = cls._load_providers(providers_env)

        # 加载全局 OAuth 账号配置
        linux_do_accounts = cls._load_oauth_accounts(linux_do_accounts_env, "Linux.do")
        github_accounts = cls._load_oauth_accounts(github_accounts_env, "GitHub")

        # 加载账号配置（传入全局 OAuth 账号用于解析 bool 类型配置）
        accounts = cls._load_accounts(accounts_env, linux_do_accounts, github_accounts)

        # 自动为自定义 provider 添加账号（如果 accounts 中没有对应的 provider）
        accounts = cls._auto_add_accounts_for_custom_providers(
            providers, accounts, linux_do_accounts, github_accounts
        )

        # 加载全局代理配置
        global_proxy = cls._load_proxy(proxy_env)

        return cls(
            providers=providers,
            accounts=accounts,
            linux_do_accounts=linux_do_accounts,
            github_accounts=github_accounts,
            global_proxy=global_proxy,
        )

    @classmethod
    def _auto_add_accounts_for_custom_providers(
        cls,
        providers: Dict[str, ProviderConfig],
        accounts: List["AccountConfig"],
        global_linux_do_accounts: List["OAuthAccountConfig"],
        global_github_accounts: List["OAuthAccountConfig"],
    ) -> List["AccountConfig"]:
        """为自定义 provider 自动添加账号

        检查所有 isCustomize=True 的 provider，如果 accounts 中没有对应的账号，
        则根据 provider 的 linuxdo_client_id 或 github_client_id 自动创建账号

        Args:
            providers: provider 配置字典
            accounts: 现有账号列表
            global_linux_do_accounts: 全局 Linux.do 账号列表
            global_github_accounts: 全局 GitHub 账号列表

        Returns:
            更新后的账号列表
        """
        # 获取所有已存在的 provider 名称
        existing_providers = {account.provider for account in accounts}

        # 遍历所有自定义 provider
        for provider_name, provider_config in providers.items():
            if not provider_config.isCustomize:
                continue

            # 如果该 provider 已经在 accounts 中，跳过
            if provider_name in existing_providers:
                print(f"ℹ️ Custom provider '{provider_name}' already has account(s), skipping auto-add")
                continue

            # 检查是否有可用的认证方式
            has_linuxdo = provider_config.linuxdo_client_id and global_linux_do_accounts
            has_github = provider_config.github_client_id and global_github_accounts

            if not has_linuxdo and not has_github:
                print(
                    f"⚠️ Custom provider '{provider_name}' has no authentication method "
                    f"(no linuxdo_client_id/github_client_id or no global accounts), skipping auto-add"
                )
                continue

            # 创建新账号配置
            new_account_data = {
                "provider": provider_name,
                "name": f"{provider_name} (auto-added)",
            }

            # 直接复制全局账号列表
            linux_do_accounts = None
            github_accounts = None

            if has_linuxdo:
                linux_do_accounts = global_linux_do_accounts.copy()
                print(f"✅ Auto-adding account for custom provider '{provider_name}' with Linux.do authentication")

            if has_github:
                github_accounts = global_github_accounts.copy()
                print(f"✅ Auto-adding account for custom provider '{provider_name}' with GitHub authentication")

            # 创建 AccountConfig
            new_account = AccountConfig.from_dict(new_account_data, linux_do_accounts, github_accounts)
            accounts.append(new_account)

        return accounts

    @classmethod
    def _load_proxy(cls, proxy_env: str) -> Dict | None:
        """从环境变量加载全局代理配置

        Args:
            proxy_env: 环境变量名称

        Returns:
            代理配置字典，如果未配置则返回 None
        """
        proxy_str = os.getenv(proxy_env)
        if not proxy_str:
            return None

        try:
            # 尝试解析为 JSON
            proxy = json.loads(proxy_str)
            print(f"⚙️ Global proxy loaded from {proxy_env} environment variable (dict format)")
            return proxy
        except json.JSONDecodeError:
            # 如果不是 JSON，则视为字符串
            proxy = {"server": proxy_str}
            print(f"⚙️ Global proxy loaded from {proxy_env} environment variable: {proxy_str}")
            return proxy

    @classmethod
    def _load_providers(cls, providers_env: str) -> Dict[str, ProviderConfig]:
        """从环境变量加载 providers 配置

        Args:
            providers_env: 环境变量名称

        Returns:
            providers 配置字典
        """
        providers = {
            "anyrouter": ProviderConfig(
                name="anyrouter",
                origin="https://anyrouter.top",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/sign_in",
                check_in_status=False,
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                api_user_key="new-api-user",
                github_client_id="Ov23liOwlnIiYoF3bUqw",
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="8w2uZtoWH9AUXrZr1qeCEEmvXLafea3c",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method="waf_cookies",
            ),
            "agentrouter": ProviderConfig(
                name="agentrouter",
                origin="https://agentrouter.org",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path=None,  # 无需签到接口，查询用户信息时自动完成签到
                check_in_status=False,
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                api_user_key="new-api-user",
                github_client_id="Ov23lidtiR4LeVZvVRNL",
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="KZUecGfhhDZMVnv8UtEdhOhf9sNOhqVX",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=True,
                bypass_method=None,
            ),
            "wong": ProviderConfig(
                name="wong",
                origin="https://wzw.pp.ua",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",
                check_in_status=False,
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path=None,
                linuxdo_client_id="451QxPCe4n9e7XrvzokzPcqPH9rUyTQF",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "huan666": ProviderConfig(
                name="huan666",
                origin="https://ai.huan666.de",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path=None,
                linuxdo_client_id="FNvJFnlfpfDM2mKDp8HTElASdjEwUriS",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "runawaytime": ProviderConfig(
                name="runawaytime",
                origin="https://runanytime.hxi.me",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=get_runawaytime_cdk,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path=None,
                linuxdo_client_id="AHjK9O3FfbCXKpF6VXGBC60K21yJ2fYk",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method="cf_clearance",
            ),
            "x666": ProviderConfig(
                name="x666",
                origin="https://x666.me",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path=None,  # 签到通过 up.x666.me 完成
                check_in_status=False,
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=get_x666_cdk,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path=None,
                linuxdo_client_id="4OtAotK6cp4047lgPD4kPXNhWRbRdTw3",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "kfc": ProviderConfig(
                name="kfc",
                origin="https://kfc-api.sxxe.net",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="UZgHjwXCE3HTrsNMjjEi0d8wpcj7d4Of",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "neb": ProviderConfig(
                name="neb",
                origin="https://ai.zzhdsgsss.xyz",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="ZflEL6xK90fbCcuWpHEKAcofgK8B5msn",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "elysiver": ProviderConfig(
                name="elysiver",
                origin="https://elysiver.h-e.top",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                github_auth_redirect_path="/oauth-redirect.html**",  # 使用 oauth-redirect.html 页面
                linuxdo_client_id="E2eaCQVl9iecd4aJBeTKedXfeKiJpSPF",
                linuxdo_auth_path="/api/oauth/linuxdo",
                linuxdo_auth_redirect_path="/oauth-redirect.html**",  # 使用 oauth-redirect.html 页面
                aliyun_captcha=False,
                bypass_method="cf_clearance",
            ),
            "hotaru": ProviderConfig(
                name="hotaru",
                origin="https://hotaruapi.com",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="qVGkHnU8fLzJVEMgHCuNUCYifUQwePWn",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method="cf_clearance",
            ),
            "b4u": ProviderConfig(
                name="b4u",
                origin="https://b4u.qzz.io",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path=None,  # 无签到接口，通过 luckydraw 获取 CDK 并 topup
                check_in_status=False,
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=get_b4u_cdk,  # 通过 tw.b4u.qzz.io/luckydraw 抽奖获取 CDK
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="Cf3PtT3ecj4kzJrMvOGM48FrHFKYXusb",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method="cf_clearance",
            ),
            "lightllm": ProviderConfig(
                name="lightllm",
                origin="https://lightllm.online",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="i7YfDNeJPx8Rbjx8JpD10YgQ2TVElVA4",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "takeapi": ProviderConfig(
                name="takeapi",
                origin="https://codex.661118.xyz",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="CeGKoyvGjd9JuUYOz57qbOqcM3ur3Y69",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "thatapi": ProviderConfig(
                name="thatapi",
                origin="https://gyapi.zxiaoruan.cn",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="doAqU5TVU6L7sXudST9MQ102aaJObESS",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "duckcoding": ProviderConfig(
                name="duckcoding",
                origin="https://duckcoding.com",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id="Ov23liCuWV2QS06gWce0",
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="MGPwGpfcyKGHsdnsY0BMpt6VZPrkxOBd",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "free-duckcoding": ProviderConfig(
                name="free-duckcoding",
                origin="https://free.duckcoding.com",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",
                check_in_status=True,
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="XNJfOdoSeXkcx80mDydoheJ0nZS4tjIf",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "taizi": ProviderConfig(
                name="taizi",
                origin="https://taizi.api.51yp.de5.net",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="ed4CnVPkYpQZSLFdha2pHFtHJOmHQ4bU",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "openai-test": ProviderConfig(
                name="openai-test",
                origin="https://openai.api-test.us.ci",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="65Lj7gYXHoSAVDDUq6Plb11thoqAV1t7",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "icat": ProviderConfig(
                name="icat",
                origin="https://icat.pp.ua",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="BNbUbjpOVvGdht0rnHcE0KvB2gUwCq02",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
            "chengtx": ProviderConfig(
                name="chengtx",
                origin="https://api.chengtx.vip",
                login_path="/login",
                status_path="/api/status",
                auth_state_path="/api/oauth/state",
                check_in_path="/api/user/checkin",  # 标准 newapi checkin 接口
                check_in_status=True,  # 使用标准签到状态查询
                user_info_path="/api/user/self",
                topup_path="/api/user/topup",
                get_cdk=None,
                api_user_key="new-api-user",
                github_client_id=None,
                github_auth_path="/api/oauth/github",
                linuxdo_client_id="pVtvkPeJx1z4OjEmBSHj3rnMvw1lF4Vb",
                linuxdo_auth_path="/api/oauth/linuxdo",
                aliyun_captcha=False,
                bypass_method=None,
            ),
        }

        # 尝试从环境变量加载自定义 providers
        providers_str = os.getenv(providers_env)

        if providers_str:
            try:
                providers_data = json.loads(providers_str)

                if not isinstance(providers_data, dict):
                    print(f"⚠️ {providers_env} must be a JSON object, ignoring custom providers")
                    return providers

                # 解析自定义 providers,会覆盖默认配置
                for name, provider_data in providers_data.items():
                    try:
                        providers[name] = ProviderConfig.from_dict(name, provider_data, is_customize=True)
                    except Exception as e:
                        print(f'⚠️ Failed to parse provider "{name}": {e}, skipping')
                        continue

                print(f"ℹ️ Loaded {len(providers_data)} custom provider(s) from {providers_env} environment variable")
            except json.JSONDecodeError as e:
                print(f"⚠️ Failed to parse {providers_env} environment variable: {e}, using default configuration only")
            except Exception as e:
                print(f"⚠️ Error loading {providers_env}: {e}, using default configuration only")
        else:
            print(f"⚠️ {providers_env} environment variable not found, using default configuration only")

        return providers

    @classmethod
    def _load_oauth_accounts(cls, env_name: str, provider_name: str) -> List["OAuthAccountConfig"]:
        """从环境变量加载 OAuth 账号配置

        Args:
            env_name: 环境变量名称
            provider_name: 提供商名称（用于日志输出）

        Returns:
            OAuth 账号配置列表
        """
        accounts_str = os.getenv(env_name)

        if not accounts_str:
            print(f"⚠️ {env_name} No {provider_name} account(s) from {env_name}")
            return []

        try:
            accounts_data = json.loads(accounts_str)

            # 检查是否为数组格式
            if not isinstance(accounts_data, list):
                print(f"⚠️ {env_name} must be a JSON array, ignoring")
                return []

            accounts = []
            for i, account in enumerate(accounts_data):
                if not isinstance(account, dict):
                    print(f"⚠️ {env_name} account {i + 1} must be a dictionary, skipping")
                    continue

                # 验证必需字段
                if "username" not in account or "password" not in account:
                    print(f"⚠️ {env_name} account {i + 1} must contain username and password, skipping")
                    continue

                # 验证字段不为空
                if not account["username"] or not account["password"]:
                    print(f"⚠️ {env_name} account {i + 1} username and password cannot be empty, skipping")
                    continue

                accounts.append(OAuthAccountConfig.from_dict(account))

            if accounts:
                print(f"⚙️ Loaded {len(accounts)} {provider_name} account(s) from {env_name}")

            return accounts
        except json.JSONDecodeError as e:
            print(f"⚠️ Failed to parse {env_name}: {e}")
            return []
        except Exception as e:
            print(f"⚠️ Error loading {env_name}: {e}")
            return []

    @classmethod
    def _parse_oauth_config(
        cls,
        config_value,
        global_accounts: List["OAuthAccountConfig"],
        config_name: str,
        account_index: int,
    ) -> List["OAuthAccountConfig"] | None:
        """解析 OAuth 配置，支持 bool、单个账号、多个账号三种格式

        Args:
            config_value: 配置值，可以是 bool、dict 或 list
            global_accounts: 全局 OAuth 账号列表
            config_name: 配置名称（用于日志输出，如 "linux.do" 或 "github"）
            account_index: 账号索引（用于日志输出）

        Returns:
            OAuth 账号配置列表，如果配置无效则返回 None
        """
        # bool 类型：使用全局账号
        if isinstance(config_value, bool):
            if config_value:
                if not global_accounts:
                    print(
                        f"⚠️ Account {account_index + 1} {config_name}=true but no global {config_name} accounts configured"
                    )
                    return []
                return global_accounts.copy()
            else:
                return []

        # dict 类型：单个账号
        if isinstance(config_value, dict):
            # 验证必需字段
            if "username" not in config_value or "password" not in config_value:
                print(f"❌ Account {account_index + 1} {config_name} configuration must contain username and password")
                return None

            # 验证字段不为空
            if not config_value["username"] or not config_value["password"]:
                print(f"❌ Account {account_index + 1} {config_name} username and password cannot be empty")
                return None

            return [OAuthAccountConfig.from_dict(config_value)]

        # list 类型：多个账号
        if isinstance(config_value, list):
            accounts = []
            for j, item in enumerate(config_value):
                if not isinstance(item, dict):
                    print(f"❌ Account {account_index + 1} {config_name}[{j}] must be a dictionary")
                    return None

                # 验证必需字段
                if "username" not in item or "password" not in item:
                    print(f"❌ Account {account_index + 1} {config_name}[{j}] must contain username and password")
                    return None

                # 验证字段不为空
                if not item["username"] or not item["password"]:
                    print(f"❌ Account {account_index + 1} {config_name}[{j}] username and password cannot be empty")
                    return None

                accounts.append(OAuthAccountConfig.from_dict(item))
            return accounts

        print(f"❌ Account {account_index + 1} {config_name} configuration must be bool, dict, or array")
        return None

    @classmethod
    def _load_accounts(
        cls,
        accounts_env: str,
        global_linux_do_accounts: List["OAuthAccountConfig"],
        global_github_accounts: List["OAuthAccountConfig"],
    ) -> List["AccountConfig"]:
        """从环境变量加载多账号配置

        Args:
            accounts_env: 环境变量名称或直接的 JSON 字符串值
                         优先尝试作为环境变量名获取，获取不到则作为值使用
            global_linux_do_accounts: 全局 Linux.do 账号列表
            global_github_accounts: 全局 GitHub 账号列表

        Returns:
            账号配置列表，如果加载失败则返回空列表
        """
        # 从环境变量获取账号配置
        accounts_str = os.getenv(accounts_env)

        if not accounts_str:
            print(f"⚠️ {accounts_env} environment variable not found")
            return []

        try:
            accounts_data = json.loads(accounts_str)

            # 检查是否为数组格式
            if not isinstance(accounts_data, list):
                print("❌ Account configuration must use array format [{}]")
                return []

            accounts = []
            # 验证账号数据格式
            for i, account in enumerate(accounts_data):
                if not isinstance(account, dict):
                    print(f"⚠️ Account {i + 1} configuration format is incorrect, skipping")
                    continue

                # 如果有 name 字段,确保它不是空字符串
                if "name" in account and not account["name"]:
                    print(f"⚠️ Account {i + 1} name field cannot be empty, skipping")
                    continue

                account_name = account.get("name") or f"Account {i + 1}"

                # 检查配置键是否存在
                has_linux_do = "linux.do" in account
                has_github = "github" in account
                has_cookies = "cookies" in account

                # 解析 linux.do 配置（支持 bool、单个账号、多个账号）
                linux_do_accounts = None
                if has_linux_do:
                    linux_do_accounts = cls._parse_oauth_config(
                        account["linux.do"],
                        global_linux_do_accounts,
                        "linux.do",
                        i,
                    )
                    if linux_do_accounts is None:
                        print(f"⚠️ {account_name} linux.do configuration is invalid, skipping")
                        continue

                # 解析 github 配置（支持 bool、单个账号、多个账号）
                github_accounts = None
                if has_github:
                    github_accounts = cls._parse_oauth_config(
                        account["github"],
                        global_github_accounts,
                        "github",
                        i,
                    )
                    if github_accounts is None:
                        print(f"⚠️ {account_name} github configuration is invalid, skipping")
                        continue

                # 验证 cookies 配置
                valid_cookies = False
                if has_cookies:
                    cookies_config = account.get("cookies")
                    api_user = account.get("api_user")

                    if cookies_config and api_user:
                        valid_cookies = True
                    elif cookies_config and not api_user:
                        print(f"⚠️ {account_name} with cookies must have api_user field")
                    elif not cookies_config:
                        print(f"⚠️ {account_name} cookies is empty")

                # 检查解析后是否至少有一个有效的认证方式
                has_valid_linux_do = linux_do_accounts is not None and len(linux_do_accounts) > 0
                has_valid_github = github_accounts is not None and len(github_accounts) > 0
                has_valid_cookies = valid_cookies

                if not has_valid_linux_do and not has_valid_github and not has_valid_cookies:
                    print(
                        f"⚠️ {account_name} must have at least one valid authentication method (linux.do, github, or cookies), skipping"
                    )
                    continue

                # 创建 AccountConfig，传入解析后的 OAuth 账号列表
                account_config = AccountConfig.from_dict(account, linux_do_accounts, github_accounts)
                accounts.append(account_config)

            return accounts
        except json.JSONDecodeError as e:
            print(f"❌ Account configuration JSON format is incorrect: {e}")
            return []
        except Exception as e:
            print(f"❌ Account configuration format is incorrect: {e}")
            return []

    def get_provider(self, name: str) -> ProviderConfig | None:
        """获取指定 provider 配置"""
        return self.providers.get(name)
