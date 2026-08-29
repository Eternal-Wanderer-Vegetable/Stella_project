# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""``init`` 向导：生成一份可用的 ``.env``。

设计原则：
1. **必答项收窄到 3 个**（群号、连接方式、地址），其余全部用默认值。
   两个模型 ID 仍会问，但允许留空——纯在线部署由 GUI 的「模型服务」分区给出
   角色模型，本机模型 ID 用不到（判据见 ``validate_answers``）。
   ``.env.example`` 已是完整参考，向导不重复它；
2. **模型 ID 从 LM Studio 拉列表让用户选编号**，而不是让人手打——这从根上
   消灭「漏掉 ``google/`` 前缀」这类错误（实测该错误的表现是兜底回复
   「......？」，真因埋在日志的 JSON 里）；
3. **基于 ``.env.example`` 逐行替换，而非从零拼接**。模板里的注释是给用户的
   说明书，尤其 OneBot 连接那段跨两个软件的配置——从零生成会把它们全丢掉；
4. 纯逻辑（校验、渲染、应答文件）与交互分离，前者可测。

「LM Studio 不可达」不能直接失败：打印警告后退化为手工输入模型 ID，并提示
启动后跑 ``python -m deploy doctor`` 确认。向导不该因为一个可选前提未就绪
就走不下去。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 需要 tomli 兜底
    import tomli as tomllib

from .probe import fetch_loaded_models

_VALID_MODES = ("reverse", "forward")


@dataclass
class Answers:
    """向导答案。字段与应答文件的 TOML 键一一对应。"""

    allowed_groups: list[int] = field(default_factory=list)
    onebot_mode: str = "reverse"  # "reverse" / "forward"
    host: str = "127.0.0.1"
    port: int = 8080
    ws_urls: list[str] = field(default_factory=list)
    access_token: str = ""
    lm_base_url: str = "http://127.0.0.1:1234"
    chat_model: str = ""
    consolidation_model: str = ""


# ── 纯逻辑层（测试重点） ──


def validate_answers(a: Answers) -> list[str]:
    """校验答案，返回问题描述列表；空 = 通过。

    纯函数，GUI 与终端向导共用同一套校验，避免两处判据漂移。
    """
    problems: list[str] = []

    if not a.allowed_groups:
        problems.append("群号：至少填写一个允许响应的 QQ 群号。")
    else:
        for g in a.allowed_groups:
            if not isinstance(g, int) or g <= 0:
                problems.append(f"群号：{g!r} 不是正整数。")

    if a.onebot_mode not in _VALID_MODES:
        problems.append(f"连接方式：必须是 {' 或 '.join(_VALID_MODES)}，当前为 {a.onebot_mode!r}。")

    if a.onebot_mode == "reverse":
        if not 1 <= a.port <= 65535:
            problems.append(f"端口：{a.port} 超出 1~65535 范围。")
    elif a.onebot_mode == "forward":
        if not a.ws_urls:
            problems.append("WS 地址：正向模式至少填一个 ws:// 或 wss:// 地址。")
        else:
            for u in a.ws_urls:
                if not u.startswith(("ws://", "wss://")):
                    problems.append(f"WS 地址：{u!r} 必须以 ws:// 或 wss:// 开头。")

    if not a.lm_base_url.startswith(("http://", "https://")):
        problems.append(f"LM Studio 地址：{a.lm_base_url!r} 必须以 http:// 或 https:// 开头。")

    # 两个本机模型 ID **允许留空**，这与 2026-08-29 之前相反。原因：模型 ID 现在
    # 有两个出处——本机模型（LM_STUDIO_MODEL / CONSOLIDATION_LM_STUDIO_MODEL）与
    # GUI「模型服务」分区里的角色模型（LLM_ROLE_*_MODEL，写在同一份 .env 的另一段）。
    # 纯在线部署的角色模型全部指向在线端点，本机模型 ID 根本不需要填；向导看不到
    # 角色那一段，在这里拦死就等于「配了在线也过不了向导」，与 P2 的验收标准
    # 「全程 GUI 完成本地↔在线切换」直接冲突。
    #
    # 留空的后果由**唯一的配置判据** registry.validate() 判（doctor 的
    # check_llm_config_issues 渲染它，且 deploy init 写完 .env 就会跑一次 doctor）：
    #   · 角色走在线端点而模型为空 → error（在线端点必须显式给模型）；
    #   · 角色走本地端点而模型为空 → warn（LM Studio 会路由到已加载模型，确实能跑）。
    # 分级比这里的一刀切更准，也不会两处判据漂移。

    return problems


def _managed_values(a: Answers) -> dict[str, str]:
    """「向导管理的键 → 目标值」映射（reverse 与 forward 互斥）。"""
    values: dict[str, str] = {
        "ALLOWED_GROUPS": ",".join(str(g) for g in a.allowed_groups),
        "LM_STUDIO_BASE_URL": a.lm_base_url,
        "LM_STUDIO_MODEL": a.chat_model,
        "CONSOLIDATION_LM_STUDIO_MODEL": a.consolidation_model,
        "ONEBOT_ACCESS_TOKEN": a.access_token,
    }
    if a.onebot_mode == "reverse":
        values["HOST"] = a.host
        values["PORT"] = str(a.port)
    else:
        values["ONEBOT_WS_URLS"] = json.dumps(a.ws_urls, ensure_ascii=False)
    return values


def managed_keys(a: Answers) -> set[str]:
    """向导直接管理的键。升级/覆盖时它们以向导答案为准，不被旧 ``.env`` 盖回去。"""
    return set(_managed_values(a))


def render_env(a: Answers, template: str) -> str:
    """逐行扫描模板，把向导管理的键替换为答案值。

    三种行形态：``KEY=旧值`` 替换；``# KEY=旧值`` 取消注释并替换；模板里
    没有的键全部扫描完后追加到末尾（前面加一行 ``# 由 deploy init 追加``）。

    匹配键名用 ``^\\s*#?\\s*KEY\\s*=`` 的形式，且**只替换第一次出现**（模板里
    同名键出现两次时，后者可能是注释里的示例）。替换后其余行原样保留——
    这是保住注释的关键。
    """
    values = _managed_values(a)
    replaced: set[str] = set()
    output: list[str] = []
    for line in template.splitlines():
        matched = False
        for key, value in values.items():
            if key in replaced:
                continue
            if re.match(rf"^\s*#?\s*{re.escape(key)}\s*=", line):
                output.append(f"{key}={value}")
                replaced.add(key)
                matched = True
                break
        if not matched:
            output.append(line)
    for key, value in values.items():
        if key not in replaced:
            output.append("# 由 deploy init 追加")
            output.append(f"{key}={value}")
    return "\n".join(output) + "\n"


def load_answers(path: Path) -> Answers:
    """从 TOML 应答文件读取。"""
    with path.open("rb") as f:
        data = tomllib.load(f)
    return Answers(
        allowed_groups=list(data.get("allowed_groups", [])),
        onebot_mode=str(data.get("onebot_mode", "reverse")),
        host=str(data.get("host", "127.0.0.1")),
        port=int(data.get("port", 8080)),
        ws_urls=[str(u) for u in data.get("ws_urls", [])],
        access_token=str(data.get("access_token", "")),
        lm_base_url=str(data.get("lm_base_url", "http://127.0.0.1:1234")),
        chat_model=str(data.get("chat_model", "")),
        consolidation_model=str(data.get("consolidation_model", "")),
    )


def save_answers(a: Answers, path: Path) -> None:
    """写 TOML 应答文件（手工拼接字符串，不引入 tomli-w 依赖）。

    json.dumps 产生的字符串/数组字面量同时是合法的 TOML basic string 与
    array，因此字段少、格式固定时手写更简单且能带注释。
    """
    lines = [
        "# deploy init 的应答文件。下次可用 python -m deploy init --answers deploy.answers.toml 跳过提问。",
        "# 含群号等个人配置，已在 .gitignore 中排除。",
        "",
        f"allowed_groups = {json.dumps(a.allowed_groups, ensure_ascii=False)}",
        f"onebot_mode = {json.dumps(a.onebot_mode, ensure_ascii=False)}",
        f"host = {json.dumps(a.host, ensure_ascii=False)}",
        f"port = {a.port}",
        f"ws_urls = {json.dumps(a.ws_urls, ensure_ascii=False)}",
        f"access_token = {json.dumps(a.access_token, ensure_ascii=False)}",
        f"lm_base_url = {json.dumps(a.lm_base_url, ensure_ascii=False)}",
        f"chat_model = {json.dumps(a.chat_model, ensure_ascii=False)}",
        f"consolidation_model = {json.dumps(a.consolidation_model, ensure_ascii=False)}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ── 交互层（不测） ──


def _ask(text: str, default: str = "") -> str:
    """提问；有默认值时回车采用默认。"""
    full = f"{text} [默认 {default}]" if default else text
    return input(full + " ").strip() or default


def _ask_groups() -> list[int]:
    while True:
        raw = _ask("允许响应的 QQ 群号（逗号分隔）:")
        parts = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
        try:
            groups = [int(p) for p in parts]
        except ValueError:
            print("群号必须是数字，请重新输入。")
            continue
        if not groups or any(g <= 0 for g in groups):
            print("至少填写一个正整数群号。")
            continue
        return groups


def _pick_model(prompt: str, models: list[str]) -> str:
    while True:
        raw = input(prompt).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(models):
            return models[int(raw) - 1]
        print(f"请输入 1~{len(models)} 之间的编号。")


def _ask_models(models: list[str]) -> tuple[str, str]:
    """编号选择两个模型。非法输入重问；不可达/无模型时退化为手工输入。"""
    if not models:
        print("[警告] LM Studio 不可达或未加载模型，改为手工输入模型 ID。")
        print("无法校验 ID 是否正确，启动后请跑 python -m deploy doctor 确认。")
        return (
            input("主聊天模型完整 ID: ").strip(),
            input("整合模型完整 ID: ").strip(),
        )
    print(f"LM Studio 已加载 {len(models)} 个模型：")
    for i, m in enumerate(models, 1):
        print(f"  {i}) {m}")
    print()
    chat = _pick_model("主聊天模型（建议参数量较大、跑 GPU）请输入编号: ", models)
    consolidation = _pick_model(
        "整合模型（建议参数量较小、GPU Offload 设为 0 跑 CPU）请输入编号: ", models
    )
    return chat, consolidation


def run_interactive() -> Answers:
    """交互式提问顺序：群号 → 连接方式 → 地址/端口 或 WS URL → token → LM → 模型。"""
    print("Stella 配置向导（回车采用默认值）")
    print()

    groups = _ask_groups()

    while True:
        mode = _ask("连接方式（reverse=反向 WS / forward=正向 WS）", "reverse").lower()
        if mode in _VALID_MODES:
            break
        print(f"只能填 {' 或 '.join(_VALID_MODES)}，请重新输入。")

    host = "127.0.0.1"
    port = 8080
    ws_urls: list[str] = []
    if mode == "reverse":
        host = _ask("监听地址（HOST）", "127.0.0.1")
        while True:
            raw_port = _ask("监听端口（PORT）", "8080")
            try:
                port = int(raw_port)
            except ValueError:
                print("端口必须是数字，请重新输入。")
                continue
            if 1 <= port <= 65535:
                break
            print("端口需在 1~65535 之间。")
    else:
        raw_ws = _ask("NapCat WS 服务端地址（多个用逗号分隔）", "ws://127.0.0.1:3001")
        ws_urls = [u.strip() for u in raw_ws.replace("，", ",").split(",") if u.strip()]

    access_token = _ask("OneBot access token（可留空）")
    lm_base_url = _ask("LM Studio 地址", "http://127.0.0.1:1234")

    models, _err = fetch_loaded_models(lm_base_url)
    chat_model, consolidation_model = _ask_models(models)

    return Answers(
        allowed_groups=groups,
        onebot_mode=mode,
        host=host,
        port=port,
        ws_urls=ws_urls,
        access_token=access_token,
        lm_base_url=lm_base_url,
        chat_model=chat_model,
        consolidation_model=consolidation_model,
    )


def print_next_steps(a: Answers) -> None:
    """结尾清单。反向 WS 的 URL 用实际填的 host/port 拼出来，让用户直接复制。"""
    print()
    print("下一步：")
    print("  1. 用 NapCatQQ Desktop 安装并登录 NapCat（需扫码，必须人工）")
    print("     https://github.com/NapNeko/NapCatQQ-Desktop")
    if a.onebot_mode == "reverse":
        print("  2. 在 NapCat WebUI 添加「WebSocket 客户端」，URL 填：")
        print(f"     ws://{a.host}:{a.port}/onebot/v11/ws")
    else:
        print("  2. 在 NapCat WebUI 添加「WebSocket 服务端」")
        if a.ws_urls:
            print(f"     监听 {a.ws_urls[0]} 的端口")
    print("  3. python -m deploy start")
