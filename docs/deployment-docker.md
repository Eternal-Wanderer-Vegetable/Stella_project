# Docker 部署指南

中文 | [English](deployment-docker.en.md)

> 适用场景：把 Stella 部署到远程 Linux 服务器（或任何有 Docker 的机器）上长期运行。
> 设计依据见 [`design_docs/Docker 化部署方案 v1.0.md`](../design_docs/Docker%20化部署方案%20v1.0.md)。
> Windows 桌面部署（Stella.exe / start.bat）不受影响，见 [README](../README.md)。

## 1. 架构与边界

推荐拓扑（compose 默认形态）：**同机双容器**——NapCat 与 Stella 同服务器，反向 WS 走 compose 内网，不占用任何公网端口：

```
服务器（docker compose）
┌──────────────────────────────────────────┐
│  stella 容器                    napcat 容器               │
│   STELLA_HOME=/data            WebUI 6099（仅回环）       │
│   ./StellaData ←─挂载          反向 WS 客户端 ──────┐     │
│   监听 8080 ←──────────────────────────────────────┘     │
└──────────────────────────────────────────┘
     LM Studio / 在线 API（Stella 出站访问，不进 compose）
```

备选拓扑：**NapCat 在别的机器上**（如你自己的 Windows 电脑跑 NapCatQQ Desktop）——把 compose 里 `stella.ports` 改成 `"8080:8080"`，并务必按 §6 配 `ONEBOT_ACCESS_TOKEN` 与 TLS。

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
#    也可跳过构建直接用官方镜像：把 docker-compose.yml 里 stella 服务的
#    build/image 两行注释换为 GHCR 那行（见文件内注释），然后 docker compose pull stella

# 4) 首次配置：交互向导（监听端口保持 8080 不变、群号、模型端点与 key），写入 StellaData/.env
#    ⚠ 向导问「监听地址」时务必填 0.0.0.0（默认值 127.0.0.1 是 Windows 桌面场景的，
#      容器里配它 NapCat 会连不上；忘了改的话容器启动时也会大声警告）
docker compose run --rm stella python -m deploy init

# 5) 起服务并确认健康（stella 的 STATUS 列出现 healthy；napcat 未登录时也算正常启动）
docker compose up -d
docker compose ps

# 6) NapCat 首次登录与网络配置（人工操作，只需一次）：
#    a. SSH 隧道进 WebUI：本地执行 ssh -L 6099:127.0.0.1:6099 user@<服务器>，
#       然后浏览器打开 http://127.0.0.1:6099/webui（WebUI 只绑了服务器回环，不走隧道打不开）
#    b. WebUI 登录 token 在容器日志里：docker compose logs napcat | grep -i token
#    c. 在 WebUI 里扫码登录 QQ
#    d. 网络配置 → 添加「WebSocket 客户端」：
#       URL   = ws://stella:8080/onebot/v11/ws（compose 服务名即容器间主机名）
#       token = .env 里 ONEBOT_ACCESS_TOKEN 的值（没配就留空）
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

# 升级（数据卷不动，这就是 STELLA_HOME 设计的收益）
git pull
docker compose build          # 本地构建方式；改用 GHCR 官方镜像时：
docker compose pull napcat    #   docker compose pull stella && docker compose pull napcat
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
- 服务器防火墙只放行需要的端口：默认编排下 stella 8080 与 NapCat WebUI 6099 都只绑了 `127.0.0.1`，公网零暴露；远程访问一律走 SSH 隧道或 WireGuard。

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
| 容器一启动就退出，日志提示 `/data/.env 不存在` | 预期行为（entrypoint 守门）：按日志提示跑 `deploy init` 或放好 `.env`。确要带空配置干跑调试：`docker compose run --rm -e STELLA_SKIP_ENV_CHECK=1 stella` |
| stella 显示 healthy 但 NapCat 反复重连失败 | 九成是 `StellaData/.env` 里 `HOST=127.0.0.1`（向导默认值是 Windows 桌面假设）：容器内健康检查走回环所以照样绿，但 NapCat 连不进来。改成 `HOST=0.0.0.0` 重启；容器启动日志里有对应警告 |
| 小内存服务器不需要图片渲染 | 构建精简镜像：`docker build --build-arg WITH_RENDER=false -t stella:slim .`，省约 300MB。渲染请求走既有降级路径（不渲染、只告警），其余功能不受影响 |
| NapCat WebUI（6099）打不开 | 它只绑了服务器回环：先 `ssh -L 6099:127.0.0.1:6099 user@<服务器>` 再本地访问 `http://127.0.0.1:6099/webui`；登录 token 见 `docker compose logs napcat` |

**named volume 替代 bind mount**：不想要宿主机目录（或遇到权限纠缠）时，把 compose 里挂载改成 `stella-data:/data` 并在文件末尾加：

```yaml
volumes:
  stella-data:
```

数据由 Docker 管理（`docker volume inspect stella_stella-data` 看位置），备份用 `docker run --rm -v stella_stella-data:/data -v "$PWD":/backup alpine tar czf /backup/stella-data.tar.gz -C /data .`。

## 8. 边界与限制

- **只能单实例**：记忆库是本地 SQLite + 进程内状态，不要 `docker compose up --scale stella=2`，也不要多机共用同一个数据目录。
- 容器内 `PORT` 固定 8080（理由与替代做法见 §7）。
- NapCat 的登录态在 `./napcat/QQ/`、网络配置在 `./napcat/config/`——这两目录和 `StellaData/` 一样要进备份；丢了分别要重新扫码、重新配 WS。
- QQ 风控提示：服务器机房 IP 上扫码登录新设备可能触发安全验证，属于 QQ 侧策略，与本项目无关；实在过不去就把 NapCat 留在常用网络环境里跑，改用 §1 的备选拓扑。
