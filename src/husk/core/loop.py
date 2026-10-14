"""The agent loop: think -> act -> observe -> repeat.

This is the heart of the framework and the smallest interesting part of it. An
"agent" is just an LLM in a loop with tools:

    1. send the conversation to the model;
    2. if it asks to call tools, run them and feed the results back;
    3. otherwise it produced a final answer -- stop.

Everything else (safety caps, context compaction, logging) wraps this core so
that the loop itself stays readable. Two invariants we defend hard: the loop
never crashes on bad provider output, and a provider error degrades to a
best-effort answer instead of a traceback.
"""
from __future__ import annotations

import json
import time
from typing import Callable


class Agent:
    def __init__(
        self,
        provider,
        tools,
        *,
        system: str,
        safety=None,
        context=None,
        logger: Callable[..., None] | None = None,
    ) -> None:
        from .safety import Safety
        from .context import Context

        self.provider = provider
        self.tools = {t.name: t for t in tools}
        self.system = system
        self.safety = safety or Safety()
        self.context = context or Context()
        self.log = logger or (lambda event, **kw: None)

    def _tool_specs(self) -> list:
        return [t.spec() for t in self.tools.values()]

    def run(self, task: str) -> str:
        """Run the loop until a final answer, the step cap, or the timeout."""
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": task},
        ]
        start = time.monotonic()
        self.log("run_start", task=task, max_steps=self.safety.max_steps)

        for step in range(self.safety.max_steps):
            if time.monotonic() - start > self.safety.wall_clock_s:
                return self._finish(messages, reason="timeout")

            specs = self._tool_specs()
            messages = self.context.fit(messages, self.provider, specs)
            try:
                msg = self.provider.chat(messages, tools=specs)
            except Exception as e:  # rate limit, 5xx, network blip, bad body
                self.log("provider_error", step=step, error=f"{type(e).__name__}: {e}")
                return self._finish(messages, reason="provider_error")
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            self.log(
                "assistant", step=step, content=msg.get("content"),
                tool_calls=[(c.get("function") or {}).get("name") for c in calls],
            )

            if not calls:  # no tools requested -> this is the final answer
                self.log("run_end", step=step, reason="final")
                return msg.get("content") or ""

            for call in calls:
                result = self._dispatch(call)
                # tool_call_id must echo the assistant call's id; fall back to ""
                # if a provider omitted it (some OpenAI-compatible servers do).
                messages.append({"role": "tool", "tool_call_id": call.get("id") or "", "content": result})

        return self._finish(messages, reason="step_limit")

    def _dispatch(self, call: dict) -> str:
        """Validate, authorise and execute one tool call. Never raises."""
        fn = call.get("function") or {}
        name = fn.get("name")
        if not name:
            return "error: tool_call missing a function name"
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError as e:
            return f"error: arguments were not valid JSON: {e}"

        tool = self.tools.get(name)
        if tool is None:
            return f"error: unknown tool '{name}'"
        if not self.safety.approve(tool, args):
            self.log("denied", tool=name, args=args)
            return "error: action denied by the safety policy or human reviewer"

        self.log("tool_call", tool=name, args=args)
        try:
            output = tool(**args)
        except Exception as e:  # a tool must never crash the loop
            output = f"error: tool raised {type(e).__name__}: {e}"
        self.log("tool_result", tool=name, output=output)
        return output

    def _finish(self, messages: list, *, reason: str) -> str:
        """Graceful degradation: ask for a best-effort answer within budget."""
        self.log("degrade", reason=reason)
        prompt = (
            f"[system] Budget exhausted ({reason}). Give your best final answer "
            "now using only what you already know. Do not call any more tools."
        )
        messages = messages + [{"role": "user", "content": prompt}]
        try:
            msg = self.provider.chat(self.context.fit(messages, self.provider, []), tools=[])
            return msg.get("content") or f"[stopped: {reason}]"
        except Exception:
            return f"[stopped: {reason}]"
