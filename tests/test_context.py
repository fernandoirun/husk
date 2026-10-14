from husk import Context
from husk.core.context import estimate_tokens
from conftest import FakeProvider


def test_estimate_counts_tool_calls_and_specs():
    # A tool-calls-only assistant turn has no 'content' but a big arguments blob.
    big_args = '{"command": "' + "x" * 400 + '"}'
    msgs = [{"role": "assistant", "tool_calls": [
        {"function": {"name": "run", "arguments": big_args}}]}]
    # Content-only estimate would be ~0; counting tool_calls must be >> that.
    assert estimate_tokens(msgs) > 90
    specs = [{"type": "function", "function": {"name": "run", "parameters": {"x": "y" * 400}}}]
    assert estimate_tokens(msgs, specs) > estimate_tokens(msgs)


def _msg(role, content, **extra):
    return {"role": role, "content": content, **extra}


def test_no_compaction_when_small():
    ctx = Context()
    provider = FakeProvider([{"role": "assistant", "content": "x"}])
    msgs = [_msg("system", "s"), _msg("user", "t"), _msg("assistant", "a")]
    assert ctx.fit(msgs, provider) == msgs
    assert provider.calls == []  # summariser not invoked


def test_compaction_preserves_system_task_and_tail():
    # Tiny window so even short messages trip the threshold.
    provider = FakeProvider([{"role": "assistant", "content": "SUMMARY"}])
    provider.context_window = 1
    ctx = Context(keep_last=2)
    big = "x" * 100
    msgs = [_msg("system", "sys"), _msg("user", "task")] + \
           [_msg("assistant", big) for _ in range(6)] + \
           [_msg("assistant", "tail1"), _msg("user", "tail2")]

    out = ctx.fit(msgs, provider)
    assert out[0]["content"] == "sys"
    assert out[1]["content"] == "task"
    assert "SUMMARY" in out[2]["content"]
    assert out[-2]["content"] == "tail1" and out[-1]["content"] == "tail2"


def test_tail_never_starts_on_a_tool_message():
    provider = FakeProvider([{"role": "assistant", "content": "S"}])
    provider.context_window = 1
    ctx = Context(keep_last=1)
    msgs = [_msg("system", "s"), _msg("user", "t"),
            _msg("assistant", "x" * 100, tool_calls=[{"id": "1"}]),
            _msg("tool", "result", tool_call_id="1")]
    out = ctx.fit(msgs, provider)
    # The kept tail must not begin with an orphaned 'tool' message.
    assert out[-1].get("role") != "tool" or any(m.get("role") == "assistant" for m in out[:-1])
