# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""独立 WebUI 开发服务器（不启动 Bot）。

前端开发与界面冒烟用：把 webui 子应用挂在一个空 FastAPI 宿主上跑起来，
浏览器访问 http://127.0.0.1:8091/ 即可走完整 setup/登录流程。没有 OneBot
路由与 /stella/status——那是 Bot 进程的；本脚本只验证 WebUI 自身。

用法：
    python scripts/dev_webui.py [--port 8091]

凭据与审计落在 STELLA_HOME（config/home.py 既有解析）下的 webui/ 与
logs/，与真实运行共用同一数据目录——想完全隔离可临时设 STELLA_HOME。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    import uvicorn

    from webui.app import create_webui_app

    uvicorn.run(create_webui_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
