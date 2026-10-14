"""Shared test doubles. No network, no Docker, fully deterministic."""
from __future__ import annotations

import json


class FakeProvider:
    """A scripted LLM. Returns pre-baked assistant messages in order and records
    every message list it was asked to complete."""

    context_window = 128000

    def __init__(self, script):
        self._script = list(script)
        self._i = 0
        self.calls = []  # the `messages` passed to each chat()

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        msg = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        return msg


def tool_call(cid, name, **arguments):
    """Build an OpenAI-style tool_call entry for scripting FakeProvider."""
    return {
        "id": cid,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
