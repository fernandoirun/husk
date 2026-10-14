"""husk command-line entry point.

Runs one agent on one task and writes a JSONL audit trail of every event:
model turns, tool calls, tool results, denials, degradations. One JSON object
per line -> trivially greppable, diffable, and replayable.

    husk "create a file hello.txt containing 'hi' and show it" --log run.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .core.context import Context
from .core.loop import Agent
from .core.safety import Safety
from .providers.openai_compat import OpenAICompatProvider
from .sandbox.container import Sandbox
from .tools.run import make_run_tool

SYSTEM = (
    "You are a careful autonomous agent. Accomplish the user's task by calling "
    "tools to act, observing the results, and iterating in small verifiable "
    "steps. When the task is complete, reply with a short final summary and stop "
    "calling tools."
)


def make_logger(path: str | None):
    """Return a log(event, **fields) callback writing JSONL to file or stderr."""
    stream = open(path, "a", encoding="utf-8") if path else sys.stderr

    def log(event: str, **fields) -> None:
        record = {"ts": round(time.time(), 3), "event": event, **fields}
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        stream.flush()

    return log


def interactive_hitl(prompt: str) -> bool:
    sys.stderr.write(prompt + "  [y/N] ")
    sys.stderr.flush()
    return sys.stdin.readline().strip().lower() in ("y", "yes")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="husk", description="Run a minimal tool-using agent.")
    ap.add_argument("task", help="what the agent should do")
    ap.add_argument("--max-steps", type=int, default=12, help="loop iteration cap")
    ap.add_argument("--timeout", type=float, default=300.0, help="wall-clock seconds")
    ap.add_argument("--model", default=None, help="override HUSK_MODEL")
    ap.add_argument("--log", default=None, help="JSONL log file (default: stderr)")
    ap.add_argument("--no-docker", action="store_true", help="force local (unsandboxed) backend")
    ap.add_argument("--approve", action="store_true", help="prompt before risky actions (HITL)")
    args = ap.parse_args(argv)

    # Make stdout robust: on Windows a redirected stream defaults to the ANSI
    # codepage with strict errors, so a final answer containing an emoji/arrow
    # would raise. UTF-8 + backslashreplace can never crash on print.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

    log = make_logger(args.log)
    provider = OpenAICompatProvider(model=args.model)
    safety = Safety(
        max_steps=args.max_steps,
        wall_clock_s=args.timeout,
        hitl=interactive_hitl if args.approve else (lambda prompt: True),
    )
    backend = "local" if args.no_docker else "auto"
    try:
        with Sandbox(backend=backend) as sandbox:
            # Tell the model the truth about its execution environment so it
            # emits commands valid for the actual shell (Linux sh vs cmd.exe).
            system = SYSTEM + (
                f"\nCommands you pass to the run tool execute in {sandbox.shell_hint}; "
                "use syntax and programs valid for that shell."
            )
            agent = Agent(
                provider, [make_run_tool(sandbox)],
                system=system, safety=safety, context=Context(), logger=log,
            )
            answer = agent.run(args.task)
    finally:
        provider.close()
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
