"""A generic shell tool. Every command runs *inside the sandbox*, never on the
bare host. Output is truncated so one noisy command cannot blow the context
window. This is the only tool the core ships with; everything else is a plugin.
"""
from __future__ import annotations

from .base import Tool

_PARAMS = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Shell command to run inside the isolated sandbox.",
        }
    },
    "required": ["command"],
}


def make_run_tool(sandbox, *, timeout: float = 60.0, max_output: int = 4000, risky: bool = True) -> Tool:
    """Build a ``run`` tool bound to a live :class:`~husk.sandbox.container.Sandbox`.

    risky defaults to True: shell execution always passes through the safety
    layer's approval path (which auto-approves unless a HITL hook is set).
    """

    def run(command: str) -> str:
        code, out = sandbox.exec(command, timeout=timeout)
        if len(out) > max_output:
            half = max_output // 2
            dropped = len(out) - max_output
            out = f"{out[:half]}\n...[{dropped} chars truncated]...\n{out[-half:]}"
        return f"exit_code={code}\n{out}"

    return Tool(
        "run",
        "Run a shell command inside the isolated sandbox and return its combined "
        "stdout/stderr and exit code. Use this to create files, run programs, and "
        "inspect results.",
        _PARAMS,
        run,
        risky=risky,
    )
