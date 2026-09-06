#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
#
# 容器入口：默认命令（python bot.py）启动前检查 /data/.env 是否存在；
# 其他命令（deploy init / deploy doctor / shell 探查）原样放行，不受影响。
#
# 为什么 .env 缺失要退出而不是带默认值硬跑：NoneBot 会正常起、健康检查会变绿，
# 用户以为部署好了，实际上 ALLOWED_GROUPS 与模型端点全是空的——一个「看起来
# 健康但什么都不会做」的容器，比一个起不来并告诉你为什么的容器更难排查。
#
# 注意：#!/bin/sh 必须保持在第一行（SPDX 头放它后面）。许可头写在首行的脚本内核
# 无法 exec（exec format error）——compose 的 init:true 下 tini 的 execvp 会回落
# /bin/sh 而侥幸能跑，裸 docker run 直接失败，实测踩过。

set -eu

# 裸 docker run（无 CMD 参数）等价于启动 Bot
if [ "$#" -eq 0 ]; then
    set -- python bot.py
fi

if [ "$1" = "python" ] && [ "$2" = "bot.py" ] && [ ! -f /data/.env ] \
    && [ "${STELLA_SKIP_ENV_CHECK:-0}" != "1" ]; then
    cat >&2 <<'EOF'
[stella] /data/.env 不存在，拒绝启动 Bot。

  首次部署   docker compose run --rm stella python -m deploy init
  已有配置   把旧 .env 放到宿主机 StellaData/ 目录（即挂载点 /data）
  跳过检查   设环境变量 STELLA_SKIP_ENV_CHECK=1（仅调试用）

详见 docs/deployment-docker.md
EOF
    exit 1
fi

# deploy init 向导的 host 默认值是 127.0.0.1（Windows 桌面场景：NapCat 在同一台
# 机器上）。容器里这样配会把 napcat 容器挡在外面，而健康检查走的恰好是容器内
# 回环、照样显示 healthy——假绿。这里只警告不拦截：HOST 或许被有意改成过别的值。
if [ "$1" = "python" ] && [ "$2" = "bot.py" ] && [ -f /data/.env ] \
    && grep -q "^HOST=127" /data/.env 2>/dev/null; then
    echo "[stella] 警告：.env 里 HOST 是 127.0.0.1，只有容器自己能连上 Bot，" >&2
    echo "         NapCat（哪怕在同一台服务器的另一个容器里）将连不上。" >&2
    echo "         把 StellaData/.env 里的 HOST 改成 0.0.0.0 后重启。" >&2
fi

exec "$@"
