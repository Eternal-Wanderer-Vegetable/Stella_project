from core.reply_gate import ReplyGate
from core.turn_runtime import TurnRuntime


def test_explicit_reply_is_hard_trigger():
    gate = ReplyGate()
    decision = gate.evaluate(1001, trigger="reply")
    assert decision.allowed is True
    assert decision.path == "hard_trigger"


def test_proactive_gate_blocks_runtime_cooldown():
    gate = ReplyGate()
    gate._runtime = TurnRuntime()
    first = gate.evaluate(1001, trigger="proactive", now=100.0)
    assert first.allowed is True
    gate.start(1001, proactive=True)
    second = gate.evaluate(1001, trigger="proactive", now=100.1)
    assert second.allowed is False
