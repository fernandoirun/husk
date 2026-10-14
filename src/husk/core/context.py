"""Context management: keep the message list under the model's window.

LLMs have a finite context window. A long agent run accumulates messages until
it would overflow (an API error) or simply get expensive. When we approach the
limit we *compact*: keep the system prompt, the original task, and the most
recent turns verbatim, and replace the middle with a short LLM-written summary.
"""
from __future__ import annotations

import json


def estimate_tokens(messages: list, tools: list | None = None) -> int:
    """Rough token estimate (~4 chars/token). Only used to decide *when* to
    compact, so approximate is fine and keeps us dependency-free.

    Crucially we count tool_calls (where a tool-using agent's real payload
    lives -- those messages usually have content=None) and the tool specs sent
    on every request, not just message content; otherwise we would wildly
    undercount and never compact before a real overflow.
    """
    chars = 0
    for m in messages:
        content = m.get("content")
        if content:
            chars += len(str(content))
        for call in m.get("tool_calls") or []:
            fn = call.get("function") or {}
            chars += len(str(fn.get("name") or "")) + len(str(fn.get("arguments") or ""))
    if tools:
        chars += len(json.dumps(tools, default=str))
    return chars // 4


class Context:
    """Compacts the message list when it nears the provider's window.

    keep_last: number of trailing messages kept verbatim.
    threshold: fraction of the window at which compaction triggers (0.8 = 80%).
    """

    def __init__(self, *, keep_last: int = 4, threshold: float = 0.8) -> None:
        self.keep_last = keep_last
        self.threshold = threshold

    def fit(self, messages: list, provider, tools: list | None = None) -> list:
        window = getattr(provider, "context_window", 128000)
        if estimate_tokens(messages, tools) < self.threshold * window:
            return messages

        system = messages[:1]        # the system prompt
        head = messages[1:2]         # the original user task
        # Never start the kept tail on a 'tool' message: it must follow the
        # assistant 'tool_calls' that produced it, or the API rejects it.
        cut = max(2, len(messages) - self.keep_last)
        while cut < len(messages) and messages[cut].get("role") == "tool":
            cut += 1
        middle = messages[2:cut]
        tail = messages[cut:]
        if not middle:
            return messages

        summary = self._summarize(system + head + middle, provider)
        # Use role 'user', not a second 'system' message: a non-leading system
        # message is dropped or rejected by some targeted providers (Ollama
        # templates, strict gateways). 'user' renders everywhere.
        note = {"role": "user", "content": "[earlier steps, compacted]\n" + summary}
        return system + head + [note] + tail

    def _summarize(self, messages: list, provider) -> str:
        ask = messages + [{
            "role": "user",
            "content": (
                "Summarise the work so far in 200 words or fewer: the goal, what "
                "was tried, key results and facts, and open threads. Facts only, "
                "no preamble."
            ),
        }]
        try:
            msg = provider.chat(ask, tools=[])
            return msg.get("content") or "(empty summary)"
        except Exception:
            # Degrade gracefully: drop the middle rather than crash the run.
            return "(summary unavailable; older steps were omitted)"
