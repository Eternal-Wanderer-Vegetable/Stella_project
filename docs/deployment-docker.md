# Docker 部署指南

> 适用场景：把 Stella 部署到远程 Linux 服务器（或任何有 Docker 的机器）上长期运行。
> 设计依据见 [`design_docs/Docker 化部署方案 v1.0.md`](../design_docs/Docker%20化部署方案%20v1.0.md)。
> Windows 桌面部署（Stella.exe / start.bat）不受影响，见 [README](../README.md)。

## 1. 架构与边界

```
服务器（docker compose）                    其他机器
┌─────────────────────────────┐
│ stella 容器                  │   NapCat（QQ 协议端，反向 WS 客户端）
│  STELLA_HOME=/data ←─挂卷── │ ─────── ws://<服务器>:8080/onebot/v11/ws
│  ./StellaData（宿主机目录）  │   LM Studio / 在线 API（Stella 出站访问）
└─────────────────────────────┘
```

镜像里只有**程序**；全部用户数据落在宿主机 `./StellaData/`（挂到容器 `/data`）：

| 数据 | 位置（StellaData/ 内） | 说明 |
|---|---|---|
| 配置（含 API key） | `.env` | 由 `deploy init` 向导生成，或从旧安装拷贝 |
| 记忆库 | `memory/agent_memory.db` | SQLite，聊天记忆全在这 |
| 插件 / 插件数据 / 渲染缓存 | `data/` | AstrBot 生态插件解压即用 |
| 群空间配置 / 人格 | `config/spaces/`、`system_prompts/` | 出厂人格已内置；改过的那份放这里，读取时优先 |
| 日志 | `logs/` | 含启动诊断 `boot_debug.log` |

由此得到两条基本守则：**升级 = 换镜像，数据不动**；**备份 = 打包 `StellaData/`**。

## 2. 前置要求

- 服务器：Docker ≥ 20.10 与 docker compose v2（`docker compose version` 能出版本号）
- 内存 ≥ 1GB（镜像约 1.2GB，含渲染用的 Chromium 与中文字体）
- 想清楚模型端点（三种模式的取舍见 [README · 三种部署模式](../README.md#-三种部署模式)）：
  - **全在线**：填在线 API 地址即可，最简单；
  - **混合/全本地**：LM Studio 跑在同一台宿主机上时，端点填 `http://host.docker.internal:1234`（compose 已配好 `host-gateway`）；跑在其他机器上就直接填它的内网地址。

## 3. 快速开始（首次部署）

```bash
# 1) 拿到代码（git clone 或从本地上传；注意 .env 不进 git，不会跟着仓库走）
git clone https://github.com/Eternal-Wanderer-Vegetable/Stella_project.git
cd Stella_project

# 2) 准备数据目录（容器内以 uid 1000 运行；Ubuntu 首个用户通常就是 1000，多数情况天然可写）
mkdir -p StellaData
sudo chown -R 1000:1000 StellaData   # 拿不准就执行这条，必然正确

# 3) 构建镜像（国内服务器可加 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple，
#    但部分国内镜像不收录 playwright，装不上就去掉该参数回落官方源）
docker compose build

# 4) 首次配置：交互向导（监听端口保持 8080 不变、群号、模型端点与 key），写入 StellaData/.env
docker compose run --rm stella python -m deploy init

# 5) 起服务并确认健康（STATUS 列出现 healthy）
docker compose up -d
docker compose ps

# 6) NapCat 侧（在它所在机器的 WebUI 里）：网络配置 → 添加「WebSocket 客户端」
#    URL = ws://<服务器地址>:8080/onebot/v11/ws
#    token = .env 里 ONEBOT_ACCESS_TOKEN 的值（见 §6 安全清单，公网必配）
```

已有现成 `.env` 的话跳过第 4 步，直接把文件放到 `StellaData/.env` 即可。
后续排查：`docker compose logs -f stella`（运行日志）、`docker compose exec stella python -m deploy doctor`（环境自检）、`StellaData/logs/boot_debug.log`（启动期插件加载诊断）。

## 4. 从现有 Windows 安装迁移

1. 本机停掉 Bot（`stop.bat` 或 GUI 停止）；
2. 把下列内容拷到服务器 `StellaData/` 下（对应旧安装的数据目录）：

   | 拷什么 | 到哪 | 不拷的后果 |
   |---|---|---|
   | `.env` | `StellaData/.env` | 全部配置与 key 丢失，需重新 init |
   | `memory/agent_memory.db`（及 `.bak` 备份） | `StellaData/memory/` | 记忆清零 |
   | `data/plugins/`、`data/plugin_data/` | `StellaData/data/` | 插件丢失 |
   | `config/spaces/` | `StellaData/config/spaces/` | 群空间配置回默认 |
   | `system_prompts/`（仅当改过人格） | `StellaData/system_prompts/` | 回退镜像里的出厂人格 |

3. `.env` 里如有 `127.0.0.1`/`localhost` 的模型端点，改成 `http://host.docker.internal:1234`（LM Studio 在同一台服务器宿主机上时）或实际地址；
4. 回到 §3 第 5 步起容器。

`logs/` 可拷可不拷（历史日志，不影响运行）。

## 5. 日常运维

```bash
docker compose stop            # 停（SIGTERM → 5 秒优雅停机，在途记忆整合不丢）
docker compose start           # 起
docker compose restart         # 重启
docker compose logs -f stella  # 跟日志
docker compose pull  # 阶段 3 起：直接拉官方镜像，无需本地构建

# 升级（数据卷不动，这就是 STELLA_HOME 设计的收益）
git pull
docker compose build
docker compose up -d

# 备份（停机备份最稳；SQLite 在线备份也可用 docker compose exec stella python -m deploy doctor 之类自检后再热备）
docker compose stop
tar czf stella-backup-$(date +%F).tar.gz StellaData/
docker compose start

# 恢复 = 解包覆盖 StellaData/ 后 up -d
```

## 6. 安全清单

- **公网暴露 8080 时必须配 token**：`.env` 里 `ONEBOT_ACCESS_TOKEN=<随机串>`，NapCat 侧 WebUI 填同值。没有 token 时任何知道地址的人都能伪装成 QQ 客户端操纵 Bot。
- 有条件就别裸暴露：前置 Caddy/Nginx 做 TLS（WebSocket 反代），或走 WireGuard/Tailscale 内网，compose 里 `ports` 改绑 `127.0.0.1:8080:8080`。
- `StellaData/.env` 与记忆库含 API key 和聊天记录：`chmod 600`、不要放进 git、不要打进镜像（`.dockerignore` 已兜底）。
- 服务器防火墙只放行需要的端口（8080 给 NapCat 用；6099 是 NapCat WebUI，跑在 NapCat 那台机器上，与本文容器无关）。

## 7. 常见问题

| 症状 | 原因与处理 |
|---|---|
| `docker compose ps` 显示 `unhealthy` | 容器内探活 `127.0.0.1:8080/stella/status` 失败。先 `docker compose logs stella` 看启动到哪一步；常见是 `.env` 缺失或模型端点连不上（探活本身不依赖模型，多半是进程没起来） |
| 宿主机 `curl :8080/stella/status` 得 403 | 预期行为：该端点只接受回环访问，且 403 恰好证明 HTTP 服务活着。外部监控请以「非 000/超时」视为存活，或进容器里探 |
| 渲染的卡片中文变方块 | 不会发生——中文字体已烤进镜像。自制精简镜像（去掉 `fonts-noto-cjk`）才会 |
| 主动搭话时间全错 | 检查 `TZ`（镜像默认 `Asia/Shanghai`，compose 里可改） |
| `deploy init` 写不进 `/data` | 宿主机目录属主不是 uid 1000：`sudo chown -R 1000:1000 StellaData`，或改用 named volume（见下） |
| pip 安装 playwright 失败 | 用的镜像源不收录 playwright，去掉 `PIP_INDEX_URL` 回落官方源（`requirements.txt` 里有同样备注） |
| 想换端口 | 改 compose 映射（如 `"9090:8080"`），**不要**改 `.env` 里的 `PORT`——容器内健康检查与 NapCat 反向 WS 地址都锚定 8080 |

**named volume 替代 bind mount**：不想要宿主机目录（或遇到权限纠缠）时，把 compose 里挂载改成 `stella-data:/data` 并在文件末尾加：

```yaml
volumes:
  stella-data:
```

数据由 Docker 管理（`docker volume inspect stella_stella-data` 看位置），备份用 `docker run --rm -v stella_stella-data:/data -v "$PWD":/backup alpine tar czf /backup/stella-data.tar.gz -C /data .`。

## 8. 边界与限制

- **只能单实例**：记忆库是本地 SQLite + 进程内状态，不要 `docker compose up --scale stella=2`，也不要多机共用同一个数据目录。
- 容器内 `PORT` 固定 8080（理由与替代做法见 §7）。
- NapCat 与 Stella 同机的双容器编排（含 WebUI 6099 扫码登录流程）是规划中的阶段 2，见设计文档 §5；在那之前 NapCat 可以跑在同一台服务器上但独立于 compose（如 `docker run mlikiowa/napcat-docker`），把反向 WS 指向宿主机 8080 即可。
