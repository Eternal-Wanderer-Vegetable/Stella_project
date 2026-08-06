from dataclasses import dataclass, field


@dataclass
class ChatContext:
    user_id: int
    group_id: int
    msg_id: int
    message: str

    context: str = ""
    raw_output: str = ""
    thought: str = ""
    action: str = "NONE"
    reply: str = ""
    lines: list[str] = field(default_factory=list)

    # ---- LLM 调用诊断信息（供 thought 日志记录） ----
    trigger: str = "reply"          # reply=@回复 / proactive=主动发言
    llm_backend: str = ""           # 实际调用的后端名（lm_studio / flexiweb）
    llm_model: str = ""             # 实际使用的模型名/站点
    system_prompt_len: int = 0      # 系统提示词字符数
    prompt_log: str = ""            # 发给 LLM 的完整 prompt（含上下文拼接）
    llm_elapsed: float = 0.0        # LLM 调用耗时（秒）
    # ---- 结构化上下文供 prompt_builder 使用 ----
    short_term: str = ""
    user_profile: str = ""
    memories_for_prompt: list[dict] = field(default_factory=list)
