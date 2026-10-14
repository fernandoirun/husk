"""Safety rails: iteration/time caps, a command policy, and an approval hook.

These are deliberately *generic* (domain-agnostic). The deny list only blocks
things that are dangerous to the *host* regardless of task; anything more
specific belongs in a plugin, not the core.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# Generic, host-protecting deny patterns. Matched against the string form of a
# tool call's arguments. These are not a security boundary by themselves (the
# sandbox is) -- they are a cheap first filter and a HITL trigger.
DEFAULT_DENY = [
    r"\brm\s+-rf\s+/(?!\w)",            # wipe filesystem root
    r"\bmkfs\b",                         # format a filesystem
    r"\bdd\s+if=.*\bof=/dev/",           # overwrite a raw device
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",  # classic fork bomb
    r"\b(shutdown|reboot|halt|poweroff)\b",       # kill the host
]


def _always_yes(prompt: str) -> bool:
    """Default HITL hook: auto-approve (non-interactive runs)."""
    return True


@dataclass
class Safety:
    """Bundle of safety limits applied by the agent loop.

    max_steps: hard cap on loop iterations (prevents runaway loops / cost).
    wall_clock_s: wall-clock timeout for the whole run.
    deny: regex patterns that force a call through HITL approval.
    allow: if non-empty, *only* calls matching one of these skip HITL;
        everything else is treated as risky. (Opt-in allowlist mode.)
    hitl: callable(prompt)->bool. Return True to approve a risky/denied call.
    """

    max_steps: int = 12
    wall_clock_s: float = 300.0
    deny: list = field(default_factory=lambda: list(DEFAULT_DENY))
    allow: list = field(default_factory=list)
    hitl: Callable[[str], bool] = _always_yes

    def __post_init__(self) -> None:
        self._deny = [re.compile(p) for p in self.deny]
        self._allow = [re.compile(p) for p in self.allow]

    def approve(self, tool, args: dict) -> bool:
        """Decide whether a tool call may run. Risky calls defer to ``hitl``."""
        haystack = " ".join(str(v) for v in args.values())
        risky = tool.risky or any(p.search(haystack) for p in self._deny)
        if self._allow and not any(p.search(haystack) for p in self._allow):
            risky = True
        if not risky:
            return True
        return bool(self.hitl(f"Approve tool '{tool.name}'? args={args}"))
