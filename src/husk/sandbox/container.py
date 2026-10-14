"""Ephemeral, isolated execution sandbox.

Tier 1 (preferred): a throwaway Docker container -- no network by default,
non-root, all capabilities dropped, read-only rootfs with writable tmpfs for
/work and /tmp, CPU/memory/PID limited, auto-removed on exit. This is the real
isolation boundary for anything the model decides to run.

Tier 0 (fallback): a subprocess confined to a temporary working directory on
the host. This has NO real isolation; it exists so the framework still runs
(with a loud warning) on machines without Docker. It prefers a POSIX shell
(sh/bash, e.g. Git Bash on Windows) so model-emitted commands behave like they
would in the container; if only cmd.exe is available it uses that and tells the
model so via the shell hint.

We talk to Docker via its CLI (subprocess), not a Python SDK -- that keeps the
runtime dependency count at one (httpx) and avoids a heavy client library.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile


def has_docker() -> bool:
    """True only if the docker CLI exists AND the daemon answers. Probing the
    daemon (not just the binary) lets 'auto' fall back to local when Docker is
    installed but not running."""
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _pick_local_shell() -> tuple[str, bool]:
    """Return (shell-executable, is_posix) for the local fallback shell."""
    sh = shutil.which("sh") or shutil.which("bash")
    if sh:
        return sh, True
    if os.name == "nt":
        return "cmd", False
    return "sh", True


def _on_rm_error(func, path, _exc):
    """Windows often blocks deleting read-only/locked files; clear the bit and
    retry, and warn (auditably) if it still fails rather than leak silently."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        sys.stderr.write(f"husk: WARNING - could not remove {path}; sandbox may have leaked\n")


class Sandbox:
    """Context manager that owns one ephemeral execution environment.

    Use it with ``with Sandbox() as sb: sb.exec("ls")``. The environment is
    created on ``__enter__`` and destroyed on ``__exit__`` no matter what.
    """

    def __init__(
        self,
        *,
        image: str = "python:3.11-slim",
        network: bool = False,
        workdir: str = "/work",
        backend: str = "auto",   # "auto" | "docker" | "local"
        cpus: str = "1",
        memory: str = "512m",
        pids: int = 256,
        setup_timeout: float = 120.0,
    ) -> None:
        self.image = image
        self.network = network
        self.workdir = workdir
        self.cpus = cpus
        self.memory = memory
        self.pids = pids
        self.setup_timeout = setup_timeout
        self.backend = ("docker" if has_docker() else "local") if backend == "auto" else backend
        self._cid: str | None = None
        self._tmp: str | None = None
        self._shell_bin: str = "sh"
        self._posix: bool = True

    @property
    def shell_hint(self) -> str:
        """Human-readable description of the shell commands run in, for the model."""
        if self.backend == "docker":
            return f"a POSIX shell (sh) inside the {self.image} Linux container"
        if self._posix:
            return "a POSIX shell (sh/bash)"
        return "Windows cmd.exe -- use cmd syntax (type, dir, set), not POSIX tools like cat/ls"

    # -- lifecycle --------------------------------------------------------
    def __enter__(self) -> "Sandbox":
        if self.backend == "docker":
            self._cid = self._sh([
                "docker", "run", "-d", "--rm",
                "--network", "bridge" if self.network else "none",
                "--user", "1000:1000",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--read-only",
                "--tmpfs", f"{self.workdir}:rw,uid=1000,gid=1000,size=64m",
                "--tmpfs", "/tmp:rw,uid=1000,gid=1000,size=64m",
                f"--cpus={self.cpus}", f"--memory={self.memory}",
                f"--pids-limit={self.pids}",
                "-w", self.workdir,
                self.image, "sleep", "86400",
            ]).strip()
        else:
            self._shell_bin, self._posix = _pick_local_shell()
            sys.stderr.write(
                "husk: WARNING - running WITHOUT container isolation (docker not "
                "available). Commands execute on the host in a temp dir. Do not run "
                "untrusted commands in this mode.\n"
            )
            self._tmp = tempfile.mkdtemp(prefix="husk-")
        return self

    def __exit__(self, *exc) -> None:
        if self.backend == "docker" and self._cid:
            subprocess.run(["docker", "rm", "-f", self._cid], capture_output=True)
        elif self._tmp:
            shutil.rmtree(self._tmp, onerror=_on_rm_error)
            if os.path.isdir(self._tmp):
                sys.stderr.write(f"husk: WARNING - ephemeral sandbox dir not fully removed: {self._tmp}\n")

    # -- execution --------------------------------------------------------
    def exec(self, command: str, timeout: float = 60.0) -> tuple[int, str]:
        """Run a shell command in the sandbox. Returns (exit_code, output)."""
        if self.backend == "docker":
            if self._cid is None:
                raise RuntimeError("Sandbox not started: use `with Sandbox() as sb: sb.exec(...)`")
            # `timeout -s KILL` runs INSIDE the container, so the budget actually
            # kills the process at the daemon side; the host timeout is a backstop
            # for a stuck exec client. PYTHONUTF8 keeps child output UTF-8.
            argv = ["docker", "exec", "-e", "PYTHONUTF8=1", "-e", "PYTHONIOENCODING=utf-8",
                    self._cid, "timeout", "-s", "KILL", str(timeout), "sh", "-c", command]
            cwd, env, encoding = None, None, "utf-8"
            host_timeout = timeout + 5
        else:
            # Write the command to a temp script and run the file. The shell
            # reads it from disk, so we never hit Windows list2cmdline mangling
            # cmd.exe's quotes; works identically for sh and cmd.
            if self._posix:
                script = os.path.join(self._tmp, "_husk_cmd.sh")
                with open(script, "w", encoding="utf-8", newline="\n") as f:
                    f.write(command + "\n")
                argv = [self._shell_bin, script]
            else:
                script = os.path.join(self._tmp, "_husk_cmd.cmd")
                with open(script, "w", encoding="utf-8") as f:
                    f.write("@echo off\r\n" + command + "\r\n")
                argv = ["cmd", "/c", script]
            cwd = self._tmp
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            encoding = "oem" if (os.name == "nt" and not self._posix) else "utf-8"
            host_timeout = timeout
        try:
            p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                               text=True, encoding=encoding, errors="replace", timeout=host_timeout)
            out = (p.stdout or "") + (p.stderr or "")
            if self.backend == "docker" and p.returncode == 137:  # 128+SIGKILL from `timeout`
                return 124, out + f"\n[timeout after {timeout}s]"
            return p.returncode, out
        except subprocess.TimeoutExpired:
            return 124, f"[timeout after {timeout}s]"

    def _sh(self, argv: list, timeout: float | None = None) -> str:
        try:
            p = subprocess.run(argv, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=timeout if timeout is not None else self.setup_timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"sandbox setup timed out after {self.setup_timeout}s "
                "(image pull or docker daemon unresponsive?)"
            )
        if p.returncode != 0:
            raise RuntimeError(f"sandbox setup failed: {p.stderr.strip() or p.stdout.strip()}")
        return p.stdout
