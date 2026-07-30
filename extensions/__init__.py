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
