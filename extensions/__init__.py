# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""扩展自动加载器。

扫描 extensions/ 下的每个子目录，若其中存在 __init__.py 且暴露了
``setup(pipeline)`` 函数，则在启动阶段调用它，让插件可以向统一的
Pipeline 注册前置/后置钩子或替换 LLM 后端，无需改动业务主程序。
"""

import importlib
import pkgutil
from pathlib import Path
from nonebot import logger
from core.pipeline import Pipeline


def load_extensions(pipeline: Pipeline, ext_dir: Path):
    if not ext_dir.is_dir():
        logger.info(f"扩展目录不存在，跳过加载: {ext_dir}")
        return

    for entry in ext_dir.iterdir():
        if not entry.is_dir():
            continue
        init_file = entry / "__init__.py"
        if not init_file.exists():
            continue

        name = entry.name
        if name.startswith("_"):
            continue

        try:
            mod = importlib.import_module(f"extensions.{name}")
            if hasattr(mod, "setup"):
                mod.setup(pipeline)
                logger.success(f"✅ [扩展] {name} 已加载")
            else:
                logger.warning(f"⚠️ [扩展] {name} 缺少 setup(pipeline) 函数")
        except Exception as e:
            logger.error(f"❌ [扩展] {name} 加载失败: {e}")
