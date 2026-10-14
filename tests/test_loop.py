from husk import Agent, Safety, Tool
from conftest import FakeProvider, tool_call


def echo_tool():
    return Tool(
        "echo", "echo text back",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        lambda text: f"echoed:{text}",
    )


def test_loop_runs_tool_then_returns_final_answer():
    provider = FakeProvider([
        {"role": "assistant", "tool_calls": [tool_call("c1", "echo", text="hi")]},
        {"role": "assistant", "content": "done"},
    ])
    agent = Agent(provider, [echo_tool()], system="s")
    answer = agent.run("say hi")

    assert answer == "done"
    # Second request must include the tool result from the first call.
    tool_msgs = [m for m in provider.calls[1] if m.get("role") == "tool"]
    assert tool_msgs and tool_msgs[0]["content"] == "echoed:hi"
    assert tool_msgs[0]["tool_call_id"] == "c1"


def test_unknown_tool_is_reported_not_raised():
    provider = FakeProvider([
        {"role": "assistant", "tool_calls": [tool_call("c1", "nope")]},
        {"role": "assistant", "content": "ok"},
    ])
    agent = Agent(provider, [echo_tool()], system="s")
    agent.run("x")
    tool_msgs = [m for m in provider.calls[1] if m.get("role") == "tool"]
    assert "unknown tool" in tool_msgs[0]["content"]


def test_tool_exception_becomes_observation():
    def boom(**_):
        raise ValueError("kaboom")
    bad = Tool("bad", "", {"type": "object", "properties": {}}, boom)
    provider = FakeProvider([
        {"role": "assistant", "tool_calls": [tool_call("c1", "bad")]},
        {"role": "assistant", "content": "recovered"},
    ])
    answer = Agent(provider, [bad], system="s").run("x")
    assert answer == "recovered"


def test_step_limit_triggers_graceful_finish():
    # Always asks for a tool -> never finishes on its own.
    looping = {"role": "assistant", "tool_calls": [tool_call("c1", "echo", text="again")]}
    final = {"role": "assistant", "content": "best effort answer"}
    provider = FakeProvider([looping, looping, final])
    agent = Agent(provider, [echo_tool()], system="s", safety=Safety(max_steps=2))
    answer = agent.run("loop forever")
    assert answer == "best effort answer"


def test_tool_call_without_id_does_not_crash():
    # Some OpenAI-compatible servers omit the tool_call 'id'. Must not raise.
    provider = FakeProvider([
        {"role": "assistant", "tool_calls": [
            {"type": "function", "function": {"name": "echo", "arguments": '{"text": "hi"}'}}]},
        {"role": "assistant", "content": "done"},
    ])
    answer = Agent(provider, [echo_tool()], system="s").run("x")
    assert answer == "done"
    tool_msgs = [m for m in provider.calls[1] if m.get("role") == "tool"]
    assert tool_msgs[0]["tool_call_id"] == ""  # falls back, no crash


def test_tool_call_without_name_is_reported():
    provider = FakeProvider([
        {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {}}]},
        {"role": "assistant", "content": "ok"},
    ])
    Agent(provider, [echo_tool()], system="s").run("x")
    tool_msgs = [m for m in provider.calls[1] if m.get("role") == "tool"]
    assert "missing a function name" in tool_msgs[0]["content"]


def test_provider_error_degrades_instead_of_raising():
    class Flaky:
        context_window = 128000
        def __init__(self):
            self.n = 0
        def chat(self, messages, tools=None):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("429 rate limited")
            return {"role": "assistant", "content": "degraded answer"}
    answer = Agent(Flaky(), [echo_tool()], system="s").run("x")
    assert answer == "degraded answer"


def test_safety_denies_risky_tool_without_approval():
    risky = Tool("danger", "", {"type": "object", "properties": {}}, lambda: "ran", risky=True)
    provider = FakeProvider([
        {"role": "assistant", "tool_calls": [tool_call("c1", "danger")]},
        {"role": "assistant", "content": "ok"},
    ])
    agent = Agent(provider, [risky], system="s", safety=Safety(hitl=lambda prompt: False))
    agent.run("x")
    tool_msgs = [m for m in provider.calls[1] if m.get("role") == "tool"]
    assert "denied" in tool_msgs[0]["content"]
