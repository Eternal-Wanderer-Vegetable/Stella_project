# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""重置 WebUI 管理员凭据（回到 setup 向导态）。

用途：忘记管理员密码、或想换账号重新初始化。删掉
``STELLA_HOME/webui/auth.json`` 即可——setup_required 由「凭据文件不
存在」定义（webui/security.py），下次打开控制台会重新走 setup 向导。

JWT 全部失效是自动的：jwt_secret 与凭据同文件存储，删文件即轮换。

用法：
    python scripts/webui_reset_auth.py             # 预览将删除的文件
    python scripts/webui_reset_auth.py --yes       # 确认执行
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="确认删除（默认只预览）")
    args = parser.parse_args()

    from config import STELLA_HOME
    from webui.security import auth_file

    target = auth_file()
    print(f"STELLA_HOME = {STELLA_HOME}")
    if not target.exists():
        print("管理员凭据不存在，无需重置（下次打开即 setup 向导）。")
        return
    print(f"将删除: {target}")
    if not args.yes:
        print("预览模式（加 --yes 执行删除）。")
        return
    target.unlink()
    if not any(target.parent.iterdir()):
        target.parent.rmdir()
    print("已重置：下次打开控制台将进入 setup 向导。")


if __name__ == "__main__":
    main()
