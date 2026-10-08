# Cometa 外部 Agent 任务层：安装与认证

中文 | [English](cometa.en.md)

Cometa 让 Stella 把编码、调研等长程任务委派给外部编程 Agent（当前支持
[OpenAI Codex](https://github.com/openai/codex)）。任务经确定性的受理门进入
本地任务库，执行进度与结果回投到原会话（QQ/WebChat），认证与权限完全由
管理员掌控。

## 安装

Codex 适配依赖官方 Python SDK（可选依赖，不影响 Stella 其余功能）：

```bash
pip install -e ".[cometa]"          # 源码部署
# 或单独安装（须官方源，镜像没有此包系列）：
pip install openai-codex==0.159.2 -i https://pypi.org/simple
```

版本是 **M0 冻结矩阵**（SDK 0.159.2 + 自带 cli-bin）：Codex 的事件契约随版
本漂移（0.147.0 曾被账号后端全模型拒绝），升级前必须重跑协议探针，不要自
行放宽版本约束。

启用开关：`.env` 设 `COMETA_ENABLED=true`（可选 `COMETA_DELEGATION_MODE=auto`
开启自动委派灰度），并在 `STELLA_HOME/config/cometa.toml` 声明后端：

```toml
[backends.codex_local]
type = "codex"
enabled = true

[backends.codex_local.env]
# 代理透传给 codex 的 app-server 子进程（按部署环境填写；本地端点记得 NO_PROXY）
HTTP_PROXY = "http://127.0.0.1:7890"
HTTPS_PROXY = "http://127.0.0.1:7890"
```

改 toml/env 需重启 bot；**认证不需要**（见下）。

## 认证（WebUI 双路线 + 旧版迁移）

入口：WebUI →「提供商」→「外部 Agent」认证卡片（`/#/providers`）。任务列表与控制仍在「外部 Agent 任务」（`/#/cometa`）。三条路线任选其一，
全部**即时生效，无需重启**——任务启动时现读认证状态。

### 1. ChatGPT 账号登录（设备码，推荐）

点「发起登录」→ 页面给出验证链接与设备码 → 浏览器打开链接、输入设备码并
授权 → 页面 2 秒内自动确认登录完成。无需本机浏览器参与 Stella 进程，远程
/无头部署可用。计费走 ChatGPT 订阅额度。

### 2. OpenAI API Key

粘贴 API Key 点「登录」。计费走 OpenAI **平台额度**（非 ChatGPT 订阅），
适合只有 API 账号的用户。

### 3. 自定义端点（OpenAI 兼容 / 中转）

填 Base URL、模型名、API Key（修改时留空 = 保留原 Key），可先「测试」拉取
模型列表验证连通。**端点必须实现 OpenAI Responses API**——Codex 0.159.2
已移除 chat completions 协议，只有 `/chat/completions` 的中转无法使用；本地
LM Studio 的 Responses 实现若不支持函数工具，也会在真实任务中断流（已知限
制，网上中转大多已支持）。

### 旧版迁移

升级前用 `codex login` 登录过的机器：认证页会显示「检测到旧版登录」，点
「一键迁移」把 `~/.codex/auth.json` 复制进托管目录（托管目录已有认证时拒绝，
可先登出）。

## 认证存在哪里

每个 codex 后端一个托管目录：`STELLA_HOME/cometa/codex_home/<backend_id>/`

| 文件 | 内容 |
| --- | --- |
| `auth.json` | Codex 登录凭据（账号 token 或 API key），由 Codex 自己写入 |
| `config.toml` | 自定义端点声明（Stella 生成，codex 原生格式） |
| `stella_credentials.json` | 自定义端点的 API key（Stella 托管，权限 0600） |

设计约束：认证**不进** `config/cometa.toml`，因此不参与 `config_hash`——改
认证不影响在途任务；key/token 永不出现在 WebUI 响应、审计日志或任务库里，
登出即删除 `auth.json`（自定义端点配置保留）。

## 权限

- QQ 侧：`cometa.toml [access]` 白名单（用户/群/操作员），空表 = 未授权；
- WebUI 侧：现有管理员登录即授权，认证配置是管理操作、逐条审计；
- 子 Agent 的文件系统/网络边界由 `[profiles.*]`（`allow_workspace_write` /
  `allow_network`）决定，落实不了就拒绝启动，不降级。

## 故障诊断

| 现象 | 处理 |
| --- | --- |
| probe 报「未配置认证」 | 在认证页完成任一路线配置 |
| probe 提「检测到旧版认证」 | 点「一键迁移」，或直接重新配置 |
| probe 报 SDK 未安装 | `pip install openai-codex==0.159.2 -i https://pypi.org/simple` |
| 设备码登录发起失败 | 检查 toml `env` 里的代理透传（OpenAI 域名需可达） |
| 设备码会话消失 | 登录会话在内存中，bot 重启后重新发起即可 |
| 自定义端点任务断流 | 确认端点支持 Responses API 且支持函数工具；本地端点记得 `NO_PROXY` |
| 版本不匹配（「模型需要更新版客户端」） | 不要用 PATH 上旧版 codex.exe；SDK 自带版本配对的 cli-bin |

## 会话回投与运行边界（6.1.0）

Origin v2 保存 kind/peer/bot/conversation_key，QQ 群与私聊的受理提示、进度和结果都回到原会话。
短结果回投完整正文；长结果优先 `.md` 文件，失败后走合并转发等降级。结果生成与平台投递
是不同状态，发送窗口内失去回执记录 `delivery_unknown`，不可据此声称成功或盲目重投。
`COMETA_ENABLED=false` 与 `COMETA_DELEGATION_MODE=explicit` 为默认值；自动委派需另行开启。
任务执行、认证、取消与通知的测试位于 `tests/cometa/`，原会话回投还需真实 QQ 验收。
