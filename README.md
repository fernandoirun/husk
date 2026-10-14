# husk

[![ci](https://github.com/fernandoirun/husk/actions/workflows/ci.yml/badge.svg)](https://github.com/fernandoirun/husk/actions/workflows/ci.yml)

**A minimal, domain-agnostic agent kernel: an LLM in a tool-using loop.**

`husk` is the thin shell around a language model that turns it from something
that *talks* into something that *acts*. The entire core is under 800 source
lines with a single runtime dependency, and that budget is enforced in CI. It is
a neutral foundation: domain-specific capabilities are added as plugins without
touching the core.

```
core SLOC: 600 / 800      runtime deps: 1 (httpx)      python: 3.11+
```

## Why

Most agent frameworks are tens of thousands of lines of scaffolding wrapped
around a loop that is, at heart, tiny. `husk` keeps only the loop and the
rails that make it safe and auditable, and makes everything else optional:

1. **Minimal.** Core < 800 SLOC, ≤ 3 runtime dependencies. A test fails the
   build if either budget is exceeded.
2. **Plugin-extensible.** A tool is just a named, described, JSON-schema'd
   callable. Add capabilities by passing `Tool`s to the `Agent` — no registry,
   no base classes, no core changes.
3. **Safe by design.** Every side-effecting command runs inside an ephemeral,
   isolated sandbox (Docker; graceful local fallback). Iteration cap, wall-clock
   timeout, a generic command policy, and a human-in-the-loop approval hook.
4. **Auditable.** Every run emits a reproducible JSONL trail: model turns, tool
   calls, results, denials, degradations — one JSON object per line.
5. **Multi-provider.** One OpenAI-compatible client reaches OpenAI, DeepSeek,
   Together, Groq, vLLM, Ollama… — configured by three environment variables.
6. **Open source.** MIT.

## Install

```bash
git clone https://github.com/fernandoirun/husk.git
cd husk
pip install -e ".[dev]"
```

Requires Python 3.11+. For real sandbox isolation, install Docker; without it,
`husk` runs in a clearly-warned local fallback mode.

## Quickstart

Configure a provider (any OpenAI-compatible endpoint):

```bash
export HUSK_BASE_URL="https://api.openai.com/v1"   # or DeepSeek, Ollama, …
export HUSK_API_KEY="sk-..."                         # blank for local servers
export HUSK_MODEL="gpt-4o-mini"
```

Run an agent on a task:

```bash
husk "create a file hello.txt with 'hi', then show its contents" --log run.jsonl
```

### See it work with no API key

The offline demo drives the full loop with a scripted model — no key, no
network — so you can watch the mechanism end to end:

```bash
python examples/file_ops_demo.py
```

## How it works

```
         task
          │
          ▼
   ┌──────────────┐   tools advertised    ┌──────────────┐
   │   Agent      │ ────────────────────▶ │  LLM provider│
   │  (the loop)  │ ◀──────────────────── │ (OpenAI-compat)
   └──────┬───────┘   assistant / calls   └──────────────┘
          │ tool_calls
          ▼
   ┌──────────────┐        runs inside     ┌──────────────┐
   │  Safety      │ ─ approve ──────────▶  │   Sandbox    │
   │ caps · HITL  │                        │  (ephemeral) │
   └──────────────┘                        └──────────────┘
          │  observations fed back into the loop
          ▼
     final answer  +  JSONL audit trail
```

The loop is: send the conversation to the model; if it requests tool calls, run
them (through the safety gate, inside the sandbox) and feed the results back;
otherwise it produced a final answer and we stop. Iteration and time caps bound
every run and degrade gracefully (one last best-effort answer) instead of
hanging or erroring.

## Adding a tool (the plugin model)

```python
from husk import Agent, Tool
from husk.providers.openai_compat import OpenAICompatProvider

wiki = Tool(
    name="wordcount",
    description="Count the words in a piece of text.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    func=lambda text: str(len(text.split())),
)

agent = Agent(OpenAICompatProvider(), [wiki], system="You are helpful.")
print(agent.run("How many words are in 'the quick brown fox'?"))
```

That is the whole extension mechanism. A future domain layer (e.g. security
tooling) is just a package that ships more `Tool`s and hands them to the
`Agent` — the core stays frozen and tiny.

## Safety model

| Tier | Isolation                                              | When            |
|------|--------------------------------------------------------|-----------------|
| 1    | Ephemeral Docker container, no network, CPU/mem/PID caps | default (Docker present) |
| 0    | Host subprocess in a temp dir — **no isolation**, warned | fallback        |

On top of the sandbox: a step cap, a wall-clock timeout, a generic deny list for
host-destructive commands, an optional allowlist mode, and a human-in-the-loop
hook (`--approve`) that must confirm risky actions.

## Audit logs

Each run writes JSONL (`--log run.jsonl`). One line per event:

```json
{"ts": 1760000000.1, "event": "tool_call", "tool": "run", "args": {"command": "ls"}}
{"ts": 1760000000.4, "event": "tool_result", "tool": "run", "output": "exit_code=0\n..."}
```

Greppable, diffable, replayable.

## Development

```bash
pytest -q          # runs unit tests + the SLOC/dependency budget gate
```

## Roadmap

`husk` is the neutral core. Planned on top (as plugins, not core changes):
specialized tool layers, richer sandbox tiers, and verifiable-reward task
runners. The core's job is to stay small enough that it never needs rewriting.

## License

MIT — see [LICENSE](LICENSE).
