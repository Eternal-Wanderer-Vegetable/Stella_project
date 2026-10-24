import inspect
import json
import os
import tempfile
from importlib.metadata import version
from pathlib import Path

from nonebot import config, init

original = Path.cwd()
with tempfile.TemporaryDirectory(prefix="stella-corona-framework-probe-") as root:
    try:
        os.chdir(root)
        Path(".env").write_text(
            "ENVIRONMENT=dev\nPORT=19001\nSTELLA_SYNTHETIC_DRIVER_VALUE=live-file\n"
        )
        inherited = config.Config()
        frozen = config.Config(_env_file=None)
        env = config.Env(_env_file=None)
        result = {
            "nonebot_version": version("nonebot2"),
            "init_signature": str(inspect.signature(init)),
            "init_none_parameter_is_not_disable": "_env_file = _env_file or"
            in inspect.getsource(init),
            "default_config_port": inherited.port,
            "explicit_config_no_files_port": frozen.port,
            "explicit_env_no_files_environment": env.environment,
            "default_config_reads_synthetic_extra": getattr(
                inherited, "stella_synthetic_driver_value", None
            ),
            "no_files_config_reads_synthetic_extra": getattr(
                frozen, "stella_synthetic_driver_value", None
            ),
        }
        assert inherited.port == 19001 and frozen.port == 8080
        assert env.environment == "prod"
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        os.chdir(original)
