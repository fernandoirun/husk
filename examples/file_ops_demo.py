"""Reproducible, offline demo.

The agent creates a Python script in the sandbox, runs it, and summarises the
output -- driven by a *scripted* (mock) LLM so it runs with no API key and no
network. This is the "see the loop work end to end" artifact.

Run it:  python examples/file_ops_demo.py
To run it against a real model instead, replace MockProvider with
husk.providers.openai_compat.OpenAICompatProvider and set HUSK_* env vars.

Note: file creation/execution happens inside the sandbox. With Docker present
this is a real isolated container (python:3.11-slim). Without Docker it falls
back to a host temp dir (and prints a warning). The commands are written to be
portable across cmd.exe, POSIX sh, and the container, and only require a real
`python` on PATH.
"""
import json

from husk.core.loop import Agent
from husk.core.safety import Safety
from husk.sandbox.container import Sandbox
from husk.tools.run import make_run_tool


class MockProvider:
    """A fixed three-step plan: write the script, run it, summarise."""

    context_window = 128000

    def __init__(self):
        # Portable: write job.py via `python -c` (no heredoc, no nested double
        # quotes) so it works identically under cmd.exe, sh, and the container.
        write_cmd = (
            "python -c \"open('job.py','w')."
            "write('nums=[2,4,6,8]\\nprint(sum(nums))\\nprint(max(nums))\\n'); "
            "print('wrote job.py')\""
        )
        self._tool_steps = iter([
            {"role": "assistant", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "run", "arguments": json.dumps({"command": write_cmd})}}]},
            {"role": "assistant", "tool_calls": [{
                "id": "c2", "type": "function",
                "function": {"name": "run", "arguments": json.dumps({"command": "python job.py"})}}]},
        ])

    def chat(self, messages, tools=None):
        step = next(self._tool_steps, None)
        if step is not None:
            return step
        # Final turn: summarise honestly from the LAST tool observation, so the
        # answer reflects what actually happened (success or failure).
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "tool"), "")
        return {"role": "assistant",
                "content": "Created job.py and ran it in the sandbox. "
                           f"Final observation from the run:\n{last}"}


def log(event, **fields):
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"[{event}] {extra}")


def main():
    provider = MockProvider()
    safety = Safety(max_steps=6, hitl=lambda prompt: True)  # auto-approve for the demo
    with Sandbox(backend="auto") as sandbox:
        agent = Agent(
            provider, [make_run_tool(sandbox)],
            system="demo agent", safety=safety, logger=log,
        )
        answer = agent.run("Create a Python script that sums [2,4,6,8], run it, report the result.")
    print("\nFINAL:", answer)


if __name__ == "__main__":
    main()
