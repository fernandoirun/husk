"""The minimalism invariant, enforced in CI.

Principle #1 of the project is a HARD budget: the core must stay under 800
source lines and at most 3 runtime dependencies. If a change blows the budget,
this test fails -- minimalism as a checked invariant, not a good intention.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

MAX_SLOC = 800
MAX_DEPS = 3

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "husk"


def count_sloc(path: Path) -> int:
    """Source lines: non-blank, non-comment. Docstring lines ARE counted
    (conservative: we never undercount to squeak under budget)."""
    sloc = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            sloc += 1
    return sloc


def test_core_under_sloc_budget():
    files = sorted(SRC.rglob("*.py"))
    assert files, f"no core files found under {SRC}"
    per_file = {f.relative_to(ROOT).as_posix(): count_sloc(f) for f in files}
    total = sum(per_file.values())
    report = "\n".join(f"  {n}: {c}" for n, c in sorted(per_file.items()))
    assert total <= MAX_SLOC, f"core SLOC {total} > {MAX_SLOC}\n{report}"


def test_runtime_dependency_budget():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert len(deps) <= MAX_DEPS, f"{len(deps)} runtime deps > {MAX_DEPS}: {deps}"
