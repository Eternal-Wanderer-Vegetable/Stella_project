# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
#
# Stella 机器人镜像。设计说明见 design_docs/Docker 化部署方案 v1.0.md，
# 部署操作手册见 docs/deployment-docker.md。
#
# 构建上下文必须是仓库根目录（.dockerignore 在那里挡掉用户数据与密钥）：
#   docker build -t stella .
#
# 运行期约定：
#   * 用户数据（.env / 记忆库 / 插件 / 日志 / 人格）一律落在 STELLA_HOME=/data
#     （挂卷），镜像里只有程序——换镜像即升级，卷即数据；
#   * 容器内 PORT 固定 8080，对外换端口用端口映射，别改 .env 里的 PORT
#     （否则健康检查与 NapCat 反向 WS 地址都会失配）。

FROM python:3.12-slim

LABEL org.opencontainers.image.title="Stella" \
    org.opencontainers.image.description="Stella - 群聊 AI 伙伴（NoneBot2 + OneBot v11）" \
    org.opencontainers.image.source="https://github.com/Eternal-Wanderer-Vegetable/Stella_project" \
    org.opencontainers.image.licenses="AGPL-3.0-only"

# tzdata：主动搭话、消息新鲜度判定都依赖本地时间语义（TZ），容器默认 UTC 会错；
# fonts-noto-cjk：playwright 渲染插件卡片的中文字体——--with-deps 只装浏览器系统库
#   不装字体，缺了中文渲染成豆腐块；
# curl：HEALTHCHECK 探活 /stella/status（该端点只接受回环访问，而健康检查在
#   容器内执行恰好是回环）。
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata fonts-noto-cjk curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    # 浏览器装到 /opt 并显式指定路径：playwright 默认缓存路径在 /root 下，
    # 切到非 root 用户后就找不到了
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    # 用户数据根目录（config/home.py 定位顺序的第 1 优先级），挂卷到这里
    STELLA_HOME=/data

WORKDIR /app

# 依赖层单独拷贝：requirements.txt 不变时重构建直接命中缓存。
# PIP_INDEX_URL 供国内服务器换源；注意部分国内镜像不收录 playwright
# （requirements.txt 里有备注），换源后装不上就回落官方源。
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt

# 渲染子系统（插件卡片 HTML→图）：浏览器内核烤进镜像（~270MB）。
# 否则 RENDER_AUTO_INSTALL 会在首次渲染时现场下载几分钟，服务器上可能没外网或太慢；
# 装好后该开关自然闲置，无需改代码。
# 不需要渲染的小内存服务器可出精简镜像（省 ~300MB）：
#   docker build --build-arg WITH_RENDER=false -t stella:slim .
# 精简镜像里 playwright 的 pip 包仍在（requirements.txt 直读），但没有浏览器，
# 渲染请求会走既有的降级路径（不渲染、只降级告警），不影响其余功能。
ARG WITH_RENDER=true
RUN if [ "$WITH_RENDER" = "true" ]; \
    then python -m playwright install --with-deps chromium-headless-shell; \
    fi

# 程序层。.dockerignore 已确保拷不进 .env / 记忆库 / 插件数据 / 人格文件。
# 保持 root 属主、对运行用户只读：程序目录不该被运行期改写。
COPY . .

# 非 root 运行，写权限只给数据卷。/data 现在建好并交属主：用 named volume 时
# Docker 会把镜像里这个目录的属主带过去；bind mount 时由宿主机目录属主决定
# （见 docs/deployment-docker.md 的 chown 说明）。
# entrypoint 先剥 \r 再 chmod：Windows 检出（autocrlf）可能把 LF 变 CRLF，带 CRLF
# 的 shebang 在 Linux 里直接 "no such file or directory"——chmod 救不了换行符。
RUN useradd --create-home --uid 1000 stella \
    && sed -i 's/\r$//' entrypoint.sh \
    && chmod +x entrypoint.sh \
    && mkdir -p /data \
    && chown stella:stella /data
USER stella

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/stella/status || exit 1

# 启动 Bot 前校验 /data/.env 存在（缺失则打印引导并退出），其他命令直接放行。
# 想绕过 entrypoint 直接执行命令时用 --entrypoint。
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "bot.py"]
