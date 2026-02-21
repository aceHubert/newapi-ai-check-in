# newapi.ai 多账号自动签到

用于公益站多账号每日签到。  

Affs:
- [AnyRouter](https://anyrouter.top/register?aff=wJrb)
- [WONG](https://wzw.pp.ua/register?aff=N6Q9)
- [薄荷 API](https://x666.me/register?aff=dgzt)
- [Huan API](https://ai.huan666.de/register?aff=qEnU)
- [KFC API](https://kfc-api.sxxe.net/register?aff=xPnf)
- [HotaruApi](https://hotaruapi.com/register?aff=q6xq)
- [Elysiver](https://elysiver.h-e.top/register?aff=5JsA)

其它使用 `newapi.ai` 功能相似, 可自定义环境变量 `PROVIDERS` 支持或 `PR` 到仓库。

## 功能特性

- ✅ 单个/多账号自动签到
- ✅ 多种机器人通知（可选）
- ✅ linux.do 登录认证
- ✅ github 登录认证 (with OTP)
- ✅ Cloudflare bypass

## 使用方法

### 1. Fork 本仓库

点击右上角的 "Fork" 按钮，将本仓库 fork 到你的账户。

### 2. 设置 GitHub Environment Secret

1. 在你 fork 的仓库中，点击 "Settings" 选项卡
2. 在左侧菜单中找到 "Environments" -> "New environment"
3. 新建一个名为 `production` 的环境
4. 点击新建的 `production` 环境进入环境配置页
5. 点击 "Add environment secret" 创建 secret：
   - Name: `ACCOUNTS`
   - Value: 你的多账号配置数据

#### 2.1 全局 OAuth 账号配置（可选）

可以配置全局的 Linux.do 和 GitHub 账号，供多个 provider 共享使用。

##### 2.1.1 ACCOUNTS_LINUX_DO

在仓库的 Settings -> Environments -> production -> Environment secrets 中添加：
   - Name: `ACCOUNTS_LINUX_DO`
   - Value: Linux.do 账号列表

```json
[
  {"username": "用户名1", "password": "密码1"},
  {"username": "用户名2", "password": "密码2"}
]
```

##### 2.1.2 ACCOUNTS_GITHUB

在仓库的 Settings -> Environments -> production -> Environment secrets 中添加：
   - Name: `ACCOUNTS_GITHUB`
   - Value: GitHub 账号列表

```json
[
  {"username": "用户名1", "password": "密码1"},
  {"username": "用户名2", "password": "密码2"}
]
```

### 3 多账号配置格式
> 如果未提供 `name` 字段，会使用 `{provider.name} 1`、`{provider.name} 2` 等默认名称。  
> 配置中 `cookies`、`github`、`linux.do` 必须至少配置 1 个。  
> 使用 `cookies` 设置时，`api_user` 字段必填。  

#### 3.1 OAuth 配置支持三种格式

`github` 和 `linux.do` 字段支持以下三种配置格式：

**1. bool 类型 - 使用全局账号**
```json
{"provider": "anyrouter", "linux.do": true}
```
当设置为 `true` 时，使用 `LINUX_DO_ACCOUNTS` 或 `GITHUB_ACCOUNTS` 中配置的所有账号。

**2. dict 类型 - 单个账号**
```json
{"provider": "anyrouter", "linux.do": {"username": "用户名", "password": "密码"}}
```

**3. array 类型 - 多个账号**
```json
{"provider": "anyrouter", "linux.do": [
  {"username": "用户名1", "password": "密码1"},
  {"username": "用户名2", "password": "密码2"}
]}
```

#### 3.2 完整示例

```json
[
    {
      "name": "我的账号",
      "cookies": {
        "session": "account1_session_value"
      },
      "api_user": "account1_api_user_id",
      "github": {
        "username": "myuser",
        "password": "mypass"
      },
      "linux.do": {
        "username": "myuser",
        "password": "mypass"
      },
      // --- 额外的配置说明 ---
      // 当前账号使用代理
      "proxy": {
        "server": "http://username:password@proxy.example.com:8080"
      },
      //provider: x666 可选配置（自动通过 linux.do 登录获取）
      // "access_token": "来自 https://qd.x666.me/",  // 已废弃，会自动获取
      "get_cdk_cookies": {
        // provider: runawaytime 必须配置
        "session": "来自 https://fuli.hxi.me/",
        // provider: b4u 必须配置
        "__Secure-authjs.session-token": "来自 https://tw.b4u.qzz.io/"
      }
    },
    {
      "name": "使用全局账号",
      "provider": "agentrouter",
      "linux.do": true,
      "github": true
    },
    {
      "name": "多个 OAuth 账号",
      "provider": "wong",
      "linux.do": [
        {"username": "user1", "password": "pass1"},
        {"username": "user2", "password": "pass2"}
      ]
    }
  ]
```

#### 3.3 字段说明：

- `name` (可选)：自定义账号显示名称，用于通知和日志中标识账号
- `provider` (可选)：供应商，内置 `anyrouter`、`agentrouter`、`wong`、`huan666`、`x666`、`runawaytime`、`kfc`、`neb`、`elysiver`、`hotaru`、`b4u`、`lightllm`、`takeapi`、`thatapi`、`duckcoding`、`free-duckcoding`、`taizi`、`openai-test`、`chengtx`，默认使用 `anyrouter`
- `proxy` (可选)：单个账号代理配置，支持 `http`、`socks5` 代理
- `cookies`(可选)：用于身份验证的 cookies 数据
- `api_user`(cookies 设置时必需)：用于请求头的 new-api-user 参数
- `linux.do`(可选)：用于登录身份验证，支持三种格式：
  - `true`：使用 `LINUX_DO_ACCOUNTS` 中的全局账号
  - `{"username": "xxx", "password": "xxx"}`：单个账号
  - `[{"username": "xxx", "password": "xxx"}, ...]`：多个账号
- `github`(可选)：用于登录身份验证，支持三种格式：
  - `true`：使用 `GITHUB_ACCOUNTS` 中的全局账号
  - `{"username": "xxx", "password": "xxx"}`：单个账号
  - `[{"username": "xxx", "password": "xxx"}, ...]`：多个账号

#### 3.4 供应商配置：

在仓库的 Settings -> Environments -> production -> Environment secrets 中添加：
   - Name: `PROVIDERS`
   - Value: 供应商
   - 说明: 自定义的 provider 会自动添加到账号中执行（在账号配置中没有使用自定义 provider 情况下, 详见 [PROVIDERS.json](./PROVIDERS.json)）。


#### 3.5 代理配置
> 应用到所有的账号，如果单个账号需要使用代理，请在单个账号配置中添加 `proxy` 字段。  
> 打开 [webshare](https://dashboard.webshare.io/) 注册账号，获取免费代理

在仓库的 Settings -> Environments -> production -> Environment secrets 中添加：
   - Name: `PROXY`
   - Value: 代理服务器地址


```bash
{
  "server": "http://username:password@proxy.example.com:8080"
}

或者

{
  "server": "http://proxy.example.com:8080",
  "username": "username",
  "password": "password"
}
```


#### 3.6 如何获取 cookies 与 api_user 的值。

通过 F12 工具，切到 Application 面板，Cookies -> session 的值，最好重新登录下，但有可能提前失效，失效后报 401 错误，到时请再重新获取。

![获取 cookies](./assets/request-cookie-session.png)

通过 F12 工具，切到 Application 面板，面板，Local storage -> user 对象中的 id 字段。

![获取 api_user](./assets/request-api-user.png)

#### 3.7 `GitHub` 在新设备上登录会有两次验证

通过打印日志中链接打开并输入验证码。

![输入 OTP](./assets/github-otp.png)

### 4. 启用 GitHub Actions

1. 在你的仓库中，点击 "Actions" 选项卡
2. 如果提示启用 Actions，请点击启用
3. 找到 "newapi.ai 自动签到" workflow
4. 点击 "Enable workflow"

### 5. 测试运行

你可以手动触发一次签到来测试：

1. 在 "Actions" 选项卡中，点击 "newapi.ai 自动签到"
2. 点击 "Run workflow" 按钮
3. 确认运行

![运行结果](./assets/check-in.png)

## 执行时间

- 脚本每 8 小时执行一次（1. action 无法准确触发，基本延时 1~1.5h；2. 目前观测到 anyrouter.top 的签到是每 24h 而不是零点就可签到）
- 你也可以随时手动触发签到

## 注意事项

- 可以在 Actions 页面查看详细的运行日志
- 支持部分账号失败，只要有账号成功签到，整个任务就不会失败
- `GitHub` 新设备 OTP 验证，注意日志中的链接或配置了通知注意接收的链接，访问链接进行输入验证码

## 开启通知

脚本支持多种通知方式，可以通过配置以下环境变量开启，如果 `webhook` 有要求安全设置，例如钉钉，可以在新建机器人时选择自定义关键词，填写 `newapi.ai`。

### 邮箱通知

- `EMAIL_USER`: 发件人邮箱地址
- `EMAIL_PASS`: 发件人邮箱密码/授权码
- `CUSTOM_SMTP_SERVER`: 自定义发件人 SMTP 服务器(可选)
- `EMAIL_TO`: 收件人邮箱地址

### 钉钉机器人

- `DINGDING_WEBHOOK`: 钉钉机器人的 Webhook 地址

### 飞书机器人

- `FEISHU_WEBHOOK`: 飞书机器人的 Webhook 地址

### 企业微信机器人

- `WEIXIN_WEBHOOK`: 企业微信机器人的 Webhook 地址

### PushPlus 推送

- `PUSHPLUS_TOKEN`: PushPlus 的 Token

### Server 酱

- `SERVERPUSHKEY`: Server 酱的 SendKey

### Telegram 机器人

- `TELEGRAM_BOT_TOKEN`: Telegram 机器人的 Token
- `TELEGRAM_CHAT_ID`: 接收消息的 Chat ID

## 防止Action因长时间无活动而自动禁止
- `ACTIONS_TRIGGER_PAT`: 在Github Settings -> Developer Settings -> Personal access tokens -> Tokens(classic) 中新建一个包含repo和workflow的令牌

配置步骤：

1. 在仓库的 Settings -> Environments -> production -> Environment secrets 中添加上述环境变量
2. 每个通知方式都是独立的，可以只配置你需要的推送方式
3. 如果某个通知方式配置不正确或未配置，脚本会自动跳过该通知方式

## 故障排除

如果签到失败，请检查：

1. 账号配置格式是否正确
2. 网站是否更改了签到接口
3. 查看 Actions 运行日志获取详细错误信息

## 本地开发环境设置

如果你需要在本地测试或开发，请按照以下步骤设置：

```bash
# 安装所有依赖
uv sync --dev

# 安装 Camoufox 浏览器
python3 -m camoufox fetch

# 按 .env.example 创建 .env
uv run main.py
```

## 测试

```bash
uv sync --dev

# 安装 Camoufox 浏览器
python3 -m camoufox fetch

# 运行测试
uv run pytest tests/
```

## 免责声明

本脚本仅用于学习和研究目的，使用前请确保遵守相关网站的使用条款.
