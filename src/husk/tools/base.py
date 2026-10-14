"""The tool plugin interface.

A *tool* is the only thing that lets an agent *act* instead of just talk.
Here a tool is a named, described, JSON-schema'd Python callable. The core never
hard-codes any capability: you add new ones by constructing a ``Tool`` and
handing it to the ``Agent``. That is the whole plugin mechanism -- no registry,
no entry points, no base class to subclass. Minimalism on purpose.
"""
from __future__ import annotations

from typing import Any, Callable


class Tool:
    """Wrap a Python function as an LLM-callable tool.

    Args:
        name: unique identifier the model emits to call this tool.
        description: tells the model *when* to reach for it. Write it well:
            this is the model's only documentation.
        parameters: JSON Schema (OpenAI function-calling format) describing the
            arguments. The model fills these in; we pass them as kwargs.
        func: the implementation. Receives the arguments as kwargs and must
            return a string (what the model observes next).
        risky: if True, the safety layer routes every call through the
            human-in-the-loop approval hook before it runs.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        func: Callable[..., str],
        *,
        risky: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.func = func
        self.risky = risky

    def spec(self) -> dict:
        """Return the OpenAI tool spec advertised to the model."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def __call__(self, **kwargs: Any) -> str:
        return self.func(**kwargs)


def tool(name: str, description: str, parameters: dict, *, risky: bool = False):
    """Decorator form of :class:`Tool`.

    Example::

        @tool("add", "Add two integers", {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        })
        def add(a, b):
            return str(a + b)
    """

    def wrap(func: Callable[..., str]) -> Tool:
        return Tool(name, description, parameters, func, risky=risky)

    return wrap
