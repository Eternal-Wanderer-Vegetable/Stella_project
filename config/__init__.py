# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""配置包入口。

仅将 settings 子模块的公开常量全部再导出，使得业务代码可以写成
``from config import LM_STUDIO_BASE_URL`` 而不是深入 settings 子模块；
所有路径/环境变量解析的逻辑都集中在 config/settings.py 中。
"""

from .settings import *
