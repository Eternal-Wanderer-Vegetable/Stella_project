from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional
from nonebot import logger
import httpx
from core.llm.base import LLMBackend


# 全局 FlexiWeb 管理器（由 ai_gateway.py 在启动时初始化）
global_manager: Optional[FlexiWebManager] = None


class FlexiWebManager:
    """管理 FlexiWeb 子进程的生命周期"""

    def __init__(self, project_dir: str, base_url: str, site: str, headless: bool = True):
        self.project_dir = Path(project_dir)
        self.base_url = base_url.rstrip("/")
        self.site = site
        self.headless = headless
        self._process: Optional[asyncio.subprocess.Process] = None
        self._ready = False
        self._start_task: Optional[asyncio.Task] = None

    # ── 公共接口 ────────────────────────────────────────

    async def ensure_running(self):
        if self._ready:
            return True
        if self._start_task and not self._start_task.done():
            return await self._start_task
        if await self._probe():
            self._ready = True
            return True
        logger.info("FlexiWeb 未运行，正在自动启动...")
        self._start_task = asyncio.create_task(self._start())
        return await self._start_task

    async def stop(self):
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            self._process = None
            self._ready = False
            logger.info("FlexiWeb 已停止")

    # ── 内部 ────────────────────────────────────────────

    async def _probe(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
                r = await client.get(f"{self.base_url}/docs")
                return r.status_code == 200
        except Exception:
            return False

    def _find_python(self) -> Optional[Path]:
        candidates = [
            self.project_dir / ".venv" / "Scripts" / "python.exe",
            self.project_dir / ".venv" / "bin" / "python",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    async def _ensure_venv(self) -> Optional[Path]:
        """在 FlexiWeb 目录下创建 .venv 并安装 requirements"""
        venv_dir = self.project_dir / ".venv"
        logger.info(f"📦 正在为 FlexiWeb 创建虚拟环境（{venv_dir}）...")

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "venv", str(venv_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"❌ 创建 venv 失败: {stderr.decode('utf-8', errors='ignore')[:200]}")
            return None

        pip_path = venv_dir / "Scripts" / "pip.exe"
        req_path = self.project_dir / "requirements.txt"
        logger.info("📦 正在安装 FlexiWeb 依赖（requirements.txt）...")
        proc = await asyncio.create_subprocess_exec(
            str(pip_path), "install", "-r", str(req_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"❌ 安装依赖失败: {stderr.decode('utf-8', errors='ignore')[:500]}")
            return None

        logger.info("📦 正在安装 Playwright 浏览器（chromium）...")
        proc = await asyncio.create_subprocess_exec(
            str(venv_dir / "Scripts" / "python.exe"), "-m", "playwright", "install", "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        python_path = self._find_python()
        if python_path:
            logger.success("✅ FlexiWeb 虚拟环境已就绪")
            return python_path
        return None

    async def _start(self) -> bool:
        python_path = self._find_python()
        if not python_path:
            python_path = await self._ensure_venv()
        if not python_path:
            logger.error(
                f"❌ 无法准备 FlexiWeb Python 环境\n"
                f"   请先在 {self.project_dir} 中手动运行 universal_setup.ps1"
            )
            return False

        main_py = self.project_dir / "main.py"
        if not main_py.exists():
            logger.error(f"❌ FlexiWeb main.py 不存在: {main_py}")
            return False

        cmd = [
            str(python_path),
            str(main_py),
            "-s", self.site,
        ]
        if self.headless:
            cmd.append("--headless")
        port = self.base_url.rsplit(":", 1)[-1]
        if port.isdigit():
            cmd.extend(["-p", port])

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.project_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        for attempt in range(40):
            await asyncio.sleep(1.5)
            if await self._probe():
                self._ready = True
                logger.success(f"✅ FlexiWeb 已就绪（{self.base_url}）")
                return True
            if self._process.returncode is not None:
                break

        stderr = ""
        if self._process.returncode is not None:
            out, err = await self._process.communicate()
            stderr = err.decode("utf-8", errors="ignore")[:500]
            logger.error(f"❌ FlexiWeb 进程异常退出（code={self._process.returncode}）\n{stderr}")
        else:
            logger.error("❌ FlexiWeb 启动超时（60 秒）")
            await self.stop()

        return False


class FlexiWebBackend(LLMBackend):
    backend_name = "flexiweb"

    def __init__(self, manager: FlexiWebManager, base_url: str, site: str = "deepseek"):
        self.manager = manager
        self.base_url = base_url.rstrip("/")
        self.site = site
        # FlexiWeb 共享同一浏览器页面，必须串行化请求，否则输入会交错乱码
        self._lock = asyncio.Lock()

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not await self.manager.ensure_running():
            raise RuntimeError("FlexiWeb 不可用")

        url = f"{self.base_url}/api/ask_sync"
        async with self._lock:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(180.0), trust_env=False) as client:
                    resp = await client.post(url, json={"site": self.site, "prompt": prompt})
                    resp.raise_for_status()
                    data = resp.json()
                    reply = data.get("reply", "")
                    if not reply:
                        raise ValueError("FlexiWeb 返回空 reply")
                    return reply
            except httpx.ConnectError:
                logger.error(f"无法连接 FlexiWeb（{url}），请确认服务已启动")
                self.manager._ready = False
                raise
            except httpx.HTTPStatusError as e:
                body = e.response.text[:500]
                logger.error(f"FlexiWeb 返回 HTTP {e.response.status_code}\n{body}")
                raise
            except httpx.TimeoutException:
                logger.error(f"FlexiWeb 请求超时（{url}），大语言模型生成耗时过长")
                raise
            except Exception:
                logger.exception(f"FlexiWeb 请求异常（{url}）")
                raise
