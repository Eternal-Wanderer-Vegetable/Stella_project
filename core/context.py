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
