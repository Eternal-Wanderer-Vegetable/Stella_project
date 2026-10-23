# NoneBot 平台适配器

中文 | [English](platforms.en.md) · [使用指南](README.md) · [文档总览](../README.md)

Stella 使用 NoneBot 适配器连接聊天平台。NoneBot 将适配器包安装与运行时注册分开：已安装的包不会自动启用；Stella 只注册「平台」页中已选择的模块，并在保存后重启生效。NoneBot 也支持在同一 Bot 中注册多个适配器，具体能力取决于各适配器与平台服务。

## 目录与安装

平台页内置的目录快照基于 [NoneBot 官方适配器目录](https://raw.githubusercontent.com/nonebot/nonebot2/master/assets/adapters.json5)，共有 32 条记录。OneBot V11 与 V12 共用 `nonebot-adapter-onebot`；Stella 随常规安装包预装 30 条可选记录对应的 29 个发行包。Walle-Q 和 NTChat 不提供选择，详情见下表。

这些依赖由 `requirements.txt` 与 `pyproject.toml` 声明，因此进入 Docker、在线/离线 Windows 安装器和源码安装。适配器的凭据、平台权限和回调地址仍由各项目文档定义；NoneBot 的 `DRIVER` 是全局设置，可从任一已选适配器的「运行时配置」窗口编辑，并对所有已选适配器生效。安装包不会替你创建平台账号或自动启用适配器。自定义适配器可在对应卡片的「运行时配置」中填写其文档要求的变量。

黑盒语音适配器要求 Python 3.11 或更新版本，因此项目支持的 Python 3.10 环境会跳过这个发行包；内置 Windows 安装器使用 Python 3.12。

## 已屏蔽的适配器

| 目录项 | 模块 | 原因 |
| --- | --- | --- |
| Walle-Q | `nonebot_adapter_walleq` | 上游 0.2.0 发布于 2023-04-10，并要求 `nonebot-adapter-onebot~=2.2.2`；Stella 核心要求 `nonebot-adapter-onebot>=2.4.6`，约束无法同时满足。参见 [PyPI 元数据](https://pypi.org/pypi/nonebot-adapter-walleq/0.2.0/json)。 |
| NTChat | `nonebot.adapters.ntchat` | 上游 0.3.5 发布于 2023-02-03，并固定 `httpx==0.23.0`；Stella 核心要求 `httpx>=0.24.0`。参见 [PyPI 元数据](https://pypi.org/pypi/nonebot-adapter-ntchat/0.3.5/json)。 |

这两个模块不随 Stella 安装包安装；运行时注册器也会跳过它们并记录日志。若升级前的 `.env` 仍列出其中之一，「平台」页会保留可见的旧配置并提示移除；删除对应卡片后保存即可清理。手工环境变量中的同名模块同样不会被注册。

## 接入步骤

1. 在「平台 → 添加适配器」中搜索并选择一个或多个可用平台。
2. 点击已选卡片的「运行时配置」，在悬浮窗口填写按适配器项目文档预设的字段。支持多账号的适配器可在表单中添加多条 Bot 配置；扩展字段收在「高级环境变量」中。旧版未关联环境变量会保留在未分配分组中，可再指定所属卡片。
3. 按该适配器项目的安装/连接说明配置账号、凭据和平台侧权限。安装包内已有受支持目录依赖；Python 3.10 使用黑盒语音时需升级到 Python 3.11+。
4. 关闭窗口返回页面草稿，使用页面底部保存按钮统一写入本机 `.env`，再重启 Stella。启动日志会列出已注册适配器；缺包、模块导入或 Driver 注册错误会给出对应模块路径。

目录收录与依赖预装只表示可在页面选择和尝试装配，不代表该适配器已通过 Stella 行为兼容、真实平台收发或账号验收。适配器文档与平台版本要求可能随上游变化，配置前请打开卡片里的项目主页核对。

表单字段依据各适配器文档或配置模型整理，研究记录见[适配器配置表单研究](../reports/2026-10-23-nonebot-adapter-config-research.md)。Heybox 上游只提供不完整的配置示例，因此其预设字段不标为必填；Minecraft 锁定版本为 1.8.2，因 RCON 文档与新版说明冲突，界面不预设 RCON。适配器目录记录不代表配置字段已针对每个锁定发行包逐项通过运行验证。

部分配置会根据文档拆成多账号 JSON 表单，例如 Matrix 的静态 Token、密码或 OAuth 登录，以及同步、邀请、端到端加密设置；Villa 的 Bot ID、Bot Secret、公钥和连接方式按每个 Bot 配置；WxClaw 同时提供账号字段和文档列出的通道默认项。表单中的敏感字段在读取时脱敏，提交空白凭据会保留原值。

## 官方文档

- [NoneBot：适配器商店内容安装](https://nonebot.dev/docs/tutorial/store)
- [NoneBot：使用与注册适配器](https://nonebot.dev/docs/advanced/adapter)
- [NoneBot 官方目录快照源](https://raw.githubusercontent.com/nonebot/nonebot2/master/assets/adapters.json5)
- [WebUI 管理](webui.md)
