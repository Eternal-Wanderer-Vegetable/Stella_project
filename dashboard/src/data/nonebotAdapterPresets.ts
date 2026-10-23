export type AdapterValueType = 'text' | 'secret' | 'number' | 'boolean' | 'select' | 'url' | 'multiline' | 'string-list' | 'json';

export interface AdapterPresetOption {
  value: string;
  label: string;
}

export interface AdapterPresetField {
  path?: string;
  envKey?: string;
  label: string;
  type?: AdapterValueType;
  required?: boolean;
  defaultValue?: string | boolean;
  placeholder?: string;
  hint?: string;
  options?: AdapterPresetOption[];
}

export interface AdapterPresetSection {
  envKey?: string;
  title: string;
  description?: string;
  kind?: 'fields' | 'bot-list';
  addLabel?: string;
  itemLabel?: string;
  fields: AdapterPresetField[];
}

export interface AdapterConfigPreset {
  description: string;
  sections: AdapterPresetSection[];
  info?: string;
}

const field = (
  path: string,
  label: string,
  type: AdapterValueType = 'text',
  options?: AdapterPresetOption[],
  extra: Pick<AdapterPresetField, 'required' | 'defaultValue' | 'placeholder' | 'hint'> = {},
): AdapterPresetField => ({ path, label, type, ...(options ? { options } : {}), ...extra });

const envField = (
  envKey: string,
  label: string,
  type: AdapterValueType = 'text',
  extra: Pick<AdapterPresetField, 'required' | 'defaultValue' | 'placeholder' | 'hint' | 'options'> = {},
): AdapterPresetField => ({ envKey, label, type, ...extra });

const botList = (
  envKey: string,
  title: string,
  fields: AdapterPresetField[],
  description?: string,
): AdapterPresetSection => ({
  envKey,
  title,
  description,
  kind: 'bot-list',
  addLabel: '添加一项',
  itemLabel: '配置项',
  fields,
});

const fields = (title: string, entries: AdapterPresetField[], description?: string): AdapterPresetSection => ({
  title,
  description,
  kind: 'fields',
  fields: entries,
});

/**
 * Fields here are transcribed from each project's configuration docs or model.
 * This is deliberately a form preset catalog, not a claim of Stella compatibility.
 */
export const nonebotAdapterPresets: Record<string, AdapterConfigPreset> = {
  'nonebot.adapters.onebot.v11': {
    description: 'OneBot V11 已在上方提供连接方式、访问 Token 和 WebSocket 字段。',
    sections: [fields('项目文档中的额外配置', [
      envField('ONEBOT_SECRET', 'ONEBOT_SECRET', 'secret', { hint: 'Webhook 上报签名密钥；是否需要取决于 OneBot 实现。' }),
      envField('ONEBOT_API_ROOTS', 'ONEBOT_API_ROOTS', 'json', { hint: 'JSON 对象：账号映射到 HTTP API 根地址。' }),
    ])],
  },
  'nonebot.adapters.ding': {
    description: '填写钉钉机器人凭据。上游配置模型将两个字段定义为可选字符串。',
    sections: [fields('钉钉机器人', [
      envField('DING_ACCESS_TOKEN', 'DING_ACCESS_TOKEN', 'secret'),
      envField('DING_SECRET', 'DING_SECRET', 'secret'),
    ])],
  },
  'nonebot.adapters.feishu': {
    description: '每个 Feishu/Lark 应用添加一项。协议可选 Webhook 或 WebSocket 长连接。',
    sections: [
      botList('FEISHU_BOTS', '飞书机器人', [
        field('app_id', 'App ID', 'text'),
        field('app_secret', 'App Secret', 'secret'),
        field('verification_token', 'Verification Token', 'secret'),
        field('encrypt_key', 'Encrypt Key', 'secret'),
        field('is_lark', '使用海外 Lark', 'boolean', undefined, { defaultValue: false }),
        field('protocol', '连接协议', 'select', [
          { value: 'http', label: 'Webhook HTTP' },
          { value: 'ws', label: 'WebSocket 长连接' },
        ], { defaultValue: 'http' }),
        field('api_base', '单 Bot API Base URL', 'url'),
      ], 'verification_token 按配置模型提供；文档没有对所有字段声明必填性。'),
      fields('Feishu / Lark API 地址', [
        envField('FEISHU_API_BASE', 'FEISHU_API_BASE', 'url', { defaultValue: 'https://open.feishu.cn' }),
        envField('FEISHU_LARK_API_BASE', 'FEISHU_LARK_API_BASE', 'url', { defaultValue: 'https://open.larksuite.com' }),
      ]),
    ],
  },
  'nonebot.adapters.telegram': {
    description: 'Telegram 的 Token、长轮询/Webhook、Webhook URL 和代理已在上方提供专用字段。',
    sections: [],
  },
  'nonebot.adapters.qq': {
    description: 'QQ Bot 凭据、连接方式和常用 intents 已在上方提供专用字段。',
    sections: [fields('QQ 适配器选项', [
      envField('QQ_IS_SANDBOX', 'QQ_IS_SANDBOX', 'boolean', { defaultValue: false }),
    ])],
  },
  'nonebot.adapters.kaiheila': {
    description: '开黑啦 / KOOK 支持配置多个机器人。',
    sections: [
      botList('KAIHEILA_BOTS', '开黑啦机器人', [field('token', 'Bot Token', 'secret')]),
      fields('适配器选项', [envField('KAIHEILA_IGNORE_OTHER_BOTS', '忽略其他机器人消息', 'boolean', { defaultValue: true })]),
    ],
  },
  'nonebot.adapters.mirai': {
    description: '连接到独立运行的 mirai-api-http 服务。Mirai 项目文档提示该生态已停止活跃更新。',
    sections: [botList('MIRAI_CLIENTS', 'Mirai 客户端', [
      field('host', '服务地址', 'text', undefined, { defaultValue: 'localhost' }),
      field('port', '服务端口', 'number', undefined, { defaultValue: '8080' }),
      field('account', '登录账号', 'text'),
      field('verify_key', 'Verify Key', 'secret'),
      field('only_ws', '仅使用 WebSocket', 'boolean', undefined, { defaultValue: false }),
    ])],
  },
  'nonebot.adapters.onebot.v12': {
    description: 'OneBot V12 连接到外部协议端；选择与服务端匹配的 HTTP 或 WebSocket 地址。',
    sections: [fields('OneBot V12 连接配置', [
      envField('ONEBOT_V12_API_ROOTS', 'ONEBOT_V12_API_ROOTS', 'json', { hint: 'JSON 对象：账号映射到 HTTP API 根地址。' }),
      envField('ONEBOT_V12_WS_URLS', 'ONEBOT_V12_WS_URLS', 'string-list', { hint: '每行一个 ws:// 或 wss:// 地址。' }),
      envField('ONEBOT_V12_ACCESS_TOKEN', 'ONEBOT_V12_ACCESS_TOKEN', 'secret'),
      envField('ONEBOT_V12_USE_MSGPACK', 'ONEBOT_V12_USE_MSGPACK', 'boolean'),
    ])],
  },
  'nonebot.adapters.console': {
    description: 'Console 适配器连接终端，不需要平台侧账号或网络凭据；DRIVER 通常使用 ~none。',
    sections: [fields('终端 Bot 信息', [
      envField('CONSOLE_BOT_ID', 'CONSOLE_BOT_ID', 'text', { defaultValue: 'robot' }),
      envField('CONSOLE_BOT_NAME', 'CONSOLE_BOT_NAME', 'text', { defaultValue: 'Bot' }),
      envField('CONSOLE_STRICT_TOME', 'CONSOLE_STRICT_TOME', 'boolean', { defaultValue: false }),
    ])],
  },
  'nonebot.adapters.github': {
    description: '配置 GitHub App 或 OAuth App。私钥与 client secret 会脱敏保存。',
    sections: [botList('GITHUB_APPS', 'GitHub App / OAuth App', [
      field('app_id', 'GitHub App ID', 'text'),
      field('private_key', 'GitHub App Private Key', 'multiline'),
      field('client_id', 'OAuth Client ID', 'text'),
      field('client_secret', 'OAuth Client Secret', 'secret'),
      field('webhook_secret', 'Webhook Secret', 'secret'),
    ], 'GitHub App 需要 App ID 与私钥；OAuth App 使用 Client ID 与 Client Secret。按所用类型填写对应字段。'),
      fields('GitHub API 选项', [
        envField('GITHUB_BASE_URL', 'GITHUB_BASE_URL', 'url'),
        envField('GITHUB_ACCEPT_FORMAT', 'GITHUB_ACCEPT_FORMAT', 'text'),
        envField('GITHUB_PREVIEWS', 'GITHUB_PREVIEWS', 'string-list'),
      ])],
  },
  'nonebot.adapters.minecraft': {
    description: '此预设按仓库 Wiki 的 WebSocket 配置制作。锁定版本 1.8.2 不预设与 Wiki V2 说明冲突的 RCON 项。',
    sections: [fields('Minecraft 连接配置', [
      envField('MINECRAFT_WS_URLS', 'MINECRAFT_WS_URLS', 'json', { hint: 'JSON 对象：服务名称映射到 WebSocket URL 列表。' }),
      envField('MINECRAFT_ACCESS_TOKEN', 'MINECRAFT_ACCESS_TOKEN', 'secret'),
    ])],
  },
  'nonebot.adapters.bilibili': {
    description: 'Bilibili 直播适配器的 README 示例提供房间列表、手动登录开关和 Cookie。',
    sections: [fields('Bilibili 直播配置', [
      envField('ROOMS', '直播间房间号列表', 'string-list'),
      envField('MANUAL_LOGIN', '手动登录', 'boolean', { defaultValue: false }),
      envField('BILI_COOKIE', 'Bilibili Cookie', 'secret'),
    ], 'manual_login 在 README 中标注为默认 false，且注明尚未实现。未设置 Cookie 时可使用二维码登录。')],
  },
  'nonebot.adapters.villa': {
    description: '每个大别野 Bot 分别配置连接方式与回调。上游适配器仓库已归档。',
    info: '需要 bot_id、bot_secret 与平台复制的 pub_key。Webhook 需 ReverseDriver + ForwardDriver；WebSocket 需 ForwardDriver。',
    sections: [
      botList('VILLA_BOTS', '大别野机器人', [
        field('bot_id', 'Bot ID', 'text', undefined, { required: true }),
        field('bot_secret', 'Bot Secret', 'secret', undefined, { required: true }),
        field('pub_key', '平台公钥（pub_key）', 'multiline', undefined, { required: true, hint: '请从大别野开放平台使用复制按钮获取。' }),
        field('test_villa_id', '测试期 Villa ID', 'text'),
        field('connection_type', '连接方式', 'select', [
          { value: 'webhook', label: 'Webhook' }, { value: 'websocket', label: 'WebSocket' },
        ], { defaultValue: 'webhook' }),
        field('callback_url', 'Webhook 回调路径', 'text', undefined, { hint: '仅 Webhook 使用；填写回调路径，例如 /your/callback/url。' }),
        field('verify_event', '校验 Event 签名', 'boolean', undefined, { defaultValue: true }),
      ]),
    ],
  },
  'nonebot.adapters.red': {
    description: 'RED Bot 连接到外部 Chronocat 协议端。',
    sections: [
      botList('RED_BOTS', 'RED 机器人', [
        field('host', 'Chronocat 地址', 'text'),
        field('port', 'Chronocat 端口', 'number'),
        field('token', 'Token', 'secret'),
      ]),
      fields('适配器选项', [envField('RED_AUTO_DETECT', '自动探测', 'boolean', { defaultValue: false })]),
    ],
  },
  'nonebot.adapters.discord': {
    description: 'Token、intents、代理和命令注册已在上方提供专用字段。',
    sections: [fields('Discord API 选项', [
      envField('DISCORD_COMPRESS', 'DISCORD_COMPRESS', 'boolean', { defaultValue: false }),
      envField('DISCORD_API_VERSION', 'DISCORD_API_VERSION', 'number', { defaultValue: '10' }),
      envField('DISCORD_API_TIMEOUT', 'DISCORD_API_TIMEOUT', 'number', { defaultValue: '30' }),
      envField('DISCORD_HANDLE_SELF_MESSAGE', 'DISCORD_HANDLE_SELF_MESSAGE', 'boolean', { defaultValue: false }),
    ])],
  },
  'nonebot.adapters.satori': {
    description: '连接到支持 Satori 协议的服务端。',
    sections: [botList('SATORI_CLIENTS', 'Satori 客户端', [
      field('host', '服务地址', 'text'),
      field('port', '服务端口', 'number'),
      field('path', '路径', 'text', undefined, { defaultValue: '' }),
      field('token', 'Token', 'secret'),
      field('timeout', '请求超时（秒）', 'number', undefined, { defaultValue: '30' }),
    ])],
  },
  'nonebot.adapters.dodo': {
    description: '填写从 DoDo 开放平台取得的客户端凭据；当前适配器使用 WebSocket。',
    sections: [botList('DODO_BOTS', 'DoDo 机器人', [
      field('client_id', 'Client ID', 'text'),
      field('token', 'Bot Token', 'secret'),
    ])],
  },
  'nonebot.adapters.rocketchat': {
    description: '使用 Rocket.Chat 机器人账号连接。上游提示该 REST API 实现不支持启用双重验证的账号。',
    sections: [fields('Rocket.Chat 连接配置', [
      envField('RC_USERNAME', 'RC_USERNAME', 'text'),
      envField('RC_PASSWORD', 'RC_PASSWORD', 'secret'),
      envField('RC_SERVER_HTTP', 'RC_SERVER_HTTP', 'url'),
      envField('RC_SERVER_WSS', 'RC_SERVER_WSS', 'url'),
      envField('RC_PROXIES', 'RC_PROXIES', 'json', { hint: '可选 JSON 对象，支持 http / https 代理。' }),
    ])],
  },
  'nonebot.adapters.kritor': {
    description: '连接到独立 Kritor gRPC 服务；官方 README 建议 DRIVER=~none。',
    sections: [
      botList('KRITOR_CLIENTS', 'Kritor 客户端', [
        field('host', '服务地址', 'text', undefined, { defaultValue: 'localhost' }),
        field('port', '服务端口', 'number'),
        field('account', '账号', 'text'),
        field('ticket', '认证 Ticket', 'secret'),
      ]),
      fields('认证选项', [envField('KRITOR_SKIP_AUTH', '跳过协议端认证', 'boolean')]),
    ],
  },
  'nonebot_adapter_tailchat': {
    description: '配置 Tailchat Bot 与连接地址。',
    sections: [
      botList('TAILCHAT_BOTS', 'Tailchat 机器人', [
        field('url', 'Tailchat 服务地址', 'url'),
        field('appId', 'App ID', 'text'),
        field('appSecret', 'App Secret', 'secret'),
      ]),
      fields('连接选项', [
        envField('TAILCHAT_RECONNECT_INTERVAL', '重连间隔', 'number'),
        envField('TAILCHAT_TIME_OUT', '请求超时', 'number'),
      ])],
  },
  'nonebot.adapters.mail': {
    description: 'Mail 适配器用 IMAP 收取邮件、SMTP 发送邮件；不是 Bot Token 形式的平台。',
    sections: [botList('MAIL_BOTS', '邮箱账号', [
      field('id', '账号 ID', 'text'),
      field('name', '发件人名称', 'text'),
      field('password', '邮箱密码 / 授权码', 'secret'),
      field('subject', '邮件主题筛选', 'text'),
      field('imap.host', 'IMAP 服务器', 'text'),
      field('imap.port', 'IMAP 端口', 'number'),
      field('imap.tls', 'IMAP TLS', 'boolean'),
      field('smtp.host', 'SMTP 服务器', 'text'),
      field('smtp.port', 'SMTP 端口', 'number'),
      field('smtp.tls', 'SMTP TLS', 'boolean'),
    ])],
  },
  'nonebot.adapters.heybox': {
    description: '上游 README 仅给出 id 与 token 的配置示例，未说明字段类型、必填性、Driver 或连接模式。',
    info: '以下字段仅按 README 示例预置，项目资料没有标明是否必填；请勿据此推断平台兼容性。',
    sections: [botList('HEYBOX_BOTS', '黑盒语音机器人（文档示例）', [
      field('id', '机器人 ID（示例字段）', 'text'),
      field('token', 'Token（示例字段）', 'secret'),
    ])],
  },
  'nonebot.adapters.wxmp': {
    description: '配置微信公众号或小程序；Webhook 回调由微信平台请求。',
    sections: [
      botList('WXMP_BOTS', 'WXMP 账号', [
        field('appid', 'App ID', 'text'),
        field('token', 'Token', 'secret'),
        field('secret', 'App Secret', 'secret'),
        field('type', '账号类型', 'select', [
          { value: 'official', label: '微信公众号' }, { value: 'miniprogram', label: '小程序' },
        ]),
        field('callback', 'Webhook 回调地址', 'url'),
        field('approve', '审核模式', 'boolean'),
      ]),
      fields('Webhook 选项', [
        envField('WXMP_OFFICIAL_TIMEOUT', '公众号响应超时（秒）', 'number'),
        envField('WXMP_VERIFY', '校验请求', 'boolean'),
      ])],
  },
  'nonebot.adapters.milky': {
    description: '按部署方式配置 WebSocket 客户端，或使用 Webhook 接收 Milky 协议事件。',
    sections: [
      botList('MILKY_CLIENTS', 'Milky WebSocket 客户端', [
        field('host', 'Milky 服务地址', 'text'),
        field('port', '服务端口', 'number'),
        field('access_token', 'Access Token', 'secret'),
        field('secure', '使用 TLS', 'boolean', undefined, { defaultValue: false }),
      ]),
      fields('Milky Webhook 服务端', [
        envField('MILKY_WEBHOOK', 'MILKY_WEBHOOK', 'json', { hint: '单个 JSON 对象：host、port、可选 access_token、secure。' }),
      ])],
  },
  'nonebot.adapters.efchat': {
    description: 'EFChat 文档要求 Token；如机器人有管理员权限，还可填写密码。',
    sections: [botList('EFCHAT_BOTS', 'EFChat 机器人', [
      field('nick', '机器人昵称', 'text'),
      field('password', '管理员密码（可选）', 'secret'),
      field('channel', '频道', 'text'),
      field('head', '头像地址（可选）', 'url'),
      field('token', 'Token', 'secret', undefined, { required: true }),
      field('ignore_self', '忽略自己的消息', 'boolean', undefined, { defaultValue: true }),
    ])],
  },
  'nonebot.adapters.vocechat': {
    description: '填写 VoceChat 服务器生成的 Bot 用户 ID 与 API Key。',
    sections: [
      botList('VOCECHAT_BOTS', 'VoceChat 机器人', [
        field('name', '机器人名称', 'text'),
        field('user_id', '用户 ID', 'text'),
        field('server', 'VoceChat 服务器地址', 'url'),
        field('api_key', 'API Key', 'secret'),
      ]),
      fields('消息历史', [envField('VOCECHAT_HISTORY_LENGTH', '历史消息条数', 'number', { defaultValue: '100' })]),
    ],
  },
  'nonebot.adapters.bilibili_live': {
    description: '选择填写用户 Bot Cookie，或开放平台 Bot 凭据。文档未标出所有字段的必填性。',
    sections: [botList('BILIBILI_LIVE_BOTS', 'Bilibili 直播 Bot', [
      field('cookie', '用户 Bot Cookie', 'secret'),
      field('room_ids', '直播间房间号', 'string-list'),
      field('access_key', '开放平台 Access Key', 'secret'),
      field('access_secret', '开放平台 Access Secret', 'secret'),
      field('app_id', '开放平台 App ID', 'text'),
      field('identify_codes', '开放平台识别码', 'string-list'),
    ])],
  },
  'nonebot.adapters.yunhu': {
    description: '云湖适配器使用 Webhook，回调路径由 App ID 与 Stella 的 HOST / PORT 组成。',
    sections: [botList('YUNHU_BOTS', '云湖机器人', [
      field('app_id', 'Bot App ID', 'text'),
      field('token', 'Token', 'secret'),
    ])],
  },
  'nonebot.adapters.wxclaw': {
    description: 'WxClaw 通过 HTTP 长轮询连接；Token 留空时可按项目文档使用扫码登录。',
    sections: [
      botList('WXCLAW_ACCOUNTS', 'WxClaw 账号', [
        field('account_id', '账号 ID', 'text', undefined, { required: true }),
        field('token', 'Token', 'secret', undefined, { hint: '可留空，按项目文档通过扫码登录获取。' }),
        field('base_url', '服务地址', 'url', undefined, { defaultValue: 'https://ilinkai.weixin.qq.com' }),
        field('enabled', '启用此账号', 'boolean', undefined, { defaultValue: true }),
      ]),
      fields('WxClaw 通道选项', [
        envField('WXCLAW_ILINK_APP_ID', 'iLink App ID', 'text', { defaultValue: 'bot' }),
        envField('WXCLAW_CHANNEL_VERSION', '通道版本', 'text', { defaultValue: '2.4.1' }),
        envField('WXCLAW_LONG_POLL_TIMEOUT', '长轮询超时（毫秒）', 'number', { defaultValue: '35000' }),
        envField('WXCLAW_API_TIMEOUT', 'API 超时（毫秒）', 'number', { defaultValue: '15000' }),
        envField('WXCLAW_CDN_BASE_URL', 'CDN 基础地址', 'url', { defaultValue: 'https://novac2c.cdn.weixin.qq.com/c2c' }),
        envField('WXCLAW_BOT_AGENT', 'Bot 标识', 'text', { hint: '留空时适配器使用 OpenClaw。' }),
      ]),
    ],
  },
  'nonebot.adapters.matrix': {
    description: '每个 Matrix 账号可使用静态 Token、用户名/密码登录或 OAuth2+PKCE。Homeserver 为必填项。',
    info: '适配器需要 HTTP ForwardDriver。静态 Token 不会自动续期；密码或 OAuth 登录可获取并刷新令牌。JSON 字段按项目 README 格式填写。',
    sections: [
      botList('MATRIX_BOTS', 'Matrix 账号与认证', [
        field('homeserver', 'Homeserver URL', 'url', undefined, { required: true }),
        field('user_id', '用户 ID', 'text'),
        field('access_token', 'Access Token（静态登录）', 'secret'),
        field('refresh_token', 'Refresh Token', 'secret', undefined, { hint: '通常由登录流程自动获取；一般无需手动填写。' }),
        field('access_token_expires_at_ms', 'Access Token 过期时间（毫秒时间戳）', 'number'),
        field('refresh_before_expiry_ms', '提前刷新时间（毫秒）', 'number', undefined, { defaultValue: '60000' }),
        field('device_id', '设备 ID', 'text'),
        field('login_user', '登录用户名 / Matrix 用户 ID', 'text'),
        field('login_password', '登录密码', 'secret'),
        field('login_initial_device_display_name', '初始设备名称', 'text'),
        field('set_presence', '在线状态', 'select', [
          { value: 'online', label: '在线' },
          { value: 'offline', label: '离线' },
          { value: 'unavailable', label: '不可用' },
        ]),
        field('oauth_enabled', '启用 OAuth2 登录', 'boolean'),
        field('oauth_server_url', 'OAuth 服务地址', 'url'),
        field('oauth_metadata_url', 'OAuth Metadata URL', 'url'),
        field('oauth_client_id', 'OAuth Client ID', 'text'),
        field('oauth_client_uri', 'OAuth Client URI', 'url'),
        field('oauth_redirect_uri', 'OAuth Redirect URI', 'url', undefined, { hint: '不填时使用自动选择的本机回调端口。' }),
        field('oauth_scope', 'OAuth Scope', 'text'),
        field('oauth_device_id', 'OAuth 设备 ID', 'text'),
        field('oauth_open_browser', '自动打开浏览器', 'boolean', undefined, { defaultValue: false }),
        field('oauth_callback_timeout', 'OAuth 回调超时（秒）', 'number', undefined, { defaultValue: '300' }),
        field('sync_filter', 'Sync Filter（JSON）', 'json', undefined, { hint: '可填写 Matrix filter ID 或 filter JSON。' }),
        field('auto_accept_invites', '自动接受群聊邀请', 'boolean', undefined, { defaultValue: false }),
        field('auto_accept_whitelist', '邀请用户白名单（JSON）', 'json', undefined, { hint: '填写用户 ID 数组；null 或留空表示不限制邀请人。' }),
        field('auto_accept_blacklist', '邀请用户黑名单（JSON）', 'json', undefined, { defaultValue: '[]', hint: '填写 Matrix 用户 ID 数组。' }),
        field('e2ee_enabled', '启用端到端加密', 'boolean', undefined, { defaultValue: true }),
        field('recovery_key', 'Secret Storage Recovery Key', 'secret'),
        field('recovery_code', 'Recovery Code（兼容字段）', 'secret'),
        field('secret_storage_passphrase', 'Secret Storage 密码', 'secret'),
        field('e2ee_store_path', '加密状态目录', 'text'),
      ]),
      fields('Matrix 连接选项', [
        envField('MATRIX_API_TIMEOUT', 'API 超时（秒）', 'number', { defaultValue: '30' }),
        envField('MATRIX_SYNC_TIMEOUT', 'Sync 长轮询超时（毫秒）', 'number', { defaultValue: '30000' }),
        envField('MATRIX_RETRY_INTERVAL', '重试间隔（秒）', 'number', { defaultValue: '3' }),
        envField('MATRIX_COMMAND_TO_ME', '命令前缀消息视为发给 Bot', 'boolean', { defaultValue: false }),
        envField('MATRIX_HANDLE_SELF_MESSAGE', '处理 Bot 自己发送的消息', 'boolean', { defaultValue: false }),
        envField('MATRIX_HANDLE_OLD_EVENTS', '处理启动前的旧事件', 'boolean', { defaultValue: false }),
        envField('MATRIX_AUTO_ACCEPT_VERIFICATION', '自动接受验证请求', 'boolean'),
        envField('MATRIX_PROXY', 'HTTP 代理', 'secret'),
        envField('MATRIX_TOKEN_STORE_PATH', 'Token 状态文件路径', 'text'),
      ]),
    ],
  },
};
