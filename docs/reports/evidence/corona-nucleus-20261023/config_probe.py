"""Synthetic configuration only; never load the user's home or credentials."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
with tempfile.TemporaryDirectory(prefix="stella-corona-config-probe-") as root:
    base = os.environ.copy()
    for key in list(base):
        if key in {"LLM_TIMEOUT", "ENVIRONMENT", "STELLA_RESTART_PARENT_PID"}:
            base.pop(key)
    base["STELLA_HOME"] = root
    base["NO_PROXY"] = "127.0.0.1,localhost"
    outer = """import os,json,subprocess,sys
from pathlib import Path
from config import settings
p=Path(os.environ['STELLA_HOME'])/'.env'
p.write_text('LLM_TIMEOUT=22\\n')
child=subprocess.run([sys.executable,'-c','from config.settings import LLM_TIMEOUT; print(LLM_TIMEOUT)'],env=os.environ.copy(),text=True,capture_output=True,check=True)
print(json.dumps({'parent':settings.LLM_TIMEOUT,'new_file':22,'successor':float(child.stdout.strip())}))"""
    path = Path(root) / ".env"
    path.write_text("LLM_TIMEOUT=11\n")
    p = subprocess.run(
        [sys.executable, "-c", outer],
        env=base,
        text=True,
        capture_output=True,
        check=True,
    )
    inherited = json.loads(p.stdout)
    read = [
        sys.executable,
        "-c",
        "from config.settings import LLM_TIMEOUT; print(LLM_TIMEOUT)",
    ]
    fresh = float(
        subprocess.run(
            read, env=base, text=True, capture_output=True, check=True
        ).stdout.strip()
    )
    path.write_text("")
    deleted = float(
        subprocess.run(
            read, env=base, text=True, capture_output=True, check=True
        ).stdout.strip()
    )
    path.write_text("LLM_TIMEOUT=22\n")
    external = base | {"LLM_TIMEOUT": "44"}
    process_override = float(
        subprocess.run(
            read, env=external, text=True, capture_output=True, check=True
        ).stdout.strip()
    )
    (Path(root) / ".env.prod").write_text("LLM_TIMEOUT=33\n")
    overlay = float(
        subprocess.run(
            read,
            env=external | {"ENVIRONMENT": "prod"},
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    )
    result = {
        "scope": "Actual config.settings in isolated STELLA_HOME; no Bot, model or network",
        "inherited_environment": inherited,
        "fresh_bootstrap_environment": fresh,
        "deleted_key_default": deleted,
        "explicit_external_environment": process_override,
        "production_overlay_overrides_external": overlay,
    }
    assert inherited == {"parent": 11.0, "new_file": 22, "successor": 11.0}
    assert (fresh, deleted, process_override, overlay) == (22.0, 90.0, 44.0, 33.0)
    print(json.dumps(result, ensure_ascii=False, indent=2))
