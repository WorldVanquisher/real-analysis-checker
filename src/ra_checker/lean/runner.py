"""Runs Lean on one assembled file, in a controlled way.

* The file is written to a fresh temporary directory; the Lean project is only
  the working directory (so ``lake env`` can find Mathlib).
* Lean is started with an argument list — never through a shell — with stdin
  closed and secrets (API keys, tokens, …) removed from its environment.
* A wall-clock timeout kills the whole process tree (``lake`` starts ``lean`` as
  a child; killing only ``lake`` would leave ``lean`` running).
* Output is decoded as UTF-8 and capped in size.

Callers handle :class:`LeanUnavailableError` as a ``RUNTIME_ERROR``.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from ra_checker.models import LeanRun

CHECK_FILE_NAME = "Check.lean"
DEFAULT_MAX_OUTPUT_CHARS = 200_000
TRUNCATION_MARKER = "\n…[output truncated]"
_SECRET_ENV_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)


class LeanUnavailableError(RuntimeError):
    """Lean or the Lean project cannot be used (not installed, missing, broken)."""


class LeanRunner(Protocol):
    def run(self, source: str) -> LeanRun: ...


def find_lake() -> Path | None:
    """Locate ``lake``: PATH first, then elan's default install directory."""
    found = shutil.which("lake")
    if found:
        return Path(found)
    exe = "lake.exe" if os.name == "nt" else "lake"
    candidate = Path.home() / ".elan" / "bin" / exe
    return candidate if candidate.is_file() else None


class SubprocessLeanRunner:
    """Runs ``lake env lean <file>`` inside the Lean project directory."""

    def __init__(
        self,
        project_dir: Path,
        timeout_s: float,
        *,
        command: Sequence[str] | None = None,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ) -> None:
        if command is None:
            lake = find_lake()
            if lake is None:
                raise LeanUnavailableError(
                    "Lean is not installed: 'lake' was not found on PATH or in ~/.elan/bin. "
                    "See the README's Lean installation section."
                )
            command = (str(lake), "env", "lean")
        self.project_dir = Path(project_dir)
        self.timeout_s = timeout_s
        self.command = tuple(command)
        self.max_output_chars = max_output_chars
        self._lean_version: str | None = None

    def run(self, source: str) -> LeanRun:
        if not self.project_dir.is_dir():
            raise LeanUnavailableError(f"Lean project directory not found: {self.project_dir}")
        with tempfile.TemporaryDirectory(
            prefix="ra_checker_", ignore_cleanup_errors=True
        ) as tmp:
            path = Path(tmp) / CHECK_FILE_NAME
            path.write_text(source, encoding="utf-8", newline="\n")
            exit_code, timed_out, stdout, stderr, duration = self._execute(
                [*self.command, str(path)], self.timeout_s
            )
        return LeanRun(
            source=source,
            exit_code=None if timed_out else exit_code,
            timed_out=timed_out,
            duration_s=duration,
            stdout=stdout,
            stderr=stderr,
            lean_version=self.lean_version(),
        )

    def lean_version(self) -> str | None:
        """``lean --version`` of the project's toolchain, cached; None if unknown."""
        if self._lean_version is None:
            try:
                code, timed_out, out, _err, _ = self._execute(
                    [*self.command, "--version"], timeout_s=60
                )
            except LeanUnavailableError:
                return None
            if code == 0 and not timed_out and out.strip():
                self._lean_version = out.strip().splitlines()[0]
        return self._lean_version

    def _execute(
        self, args: list[str], timeout_s: float
    ) -> tuple[int | None, bool, str, str, float]:
        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                args,
                cwd=self.project_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_child_environment(Path(args[0]).parent),
                **_process_group_options(),
            )
        except OSError as exc:
            raise LeanUnavailableError(f"could not start Lean ({exc.__class__.__name__})") from exc

        timed_out = False
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(proc)
            try:
                out, err = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:  # a grandchild still holds the pipes
                proc.kill()
                out, err = b"", b""
        duration = time.monotonic() - start
        return (
            proc.returncode,
            timed_out,
            self._decode(out),
            self._decode(err),
            duration,
        )

    def _decode(self, data: bytes) -> str:
        text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
        if len(text) > self.max_output_chars:
            text = text[: self.max_output_chars] + TRUNCATION_MARKER
        return text


class FakeLeanRunner:
    """Test double: returns a canned result and records every source it was given."""

    def __init__(
        self,
        stdout: str = "",
        *,
        exit_code: int | None = 0,
        timed_out: bool = False,
        stderr: str = "",
        lean_version: str | None = "Lean (fake)",
    ) -> None:
        self.stdout, self.stderr = stdout, stderr
        self.exit_code, self.timed_out = exit_code, timed_out
        self.lean_version = lean_version
        self.sources: list[str] = []

    def run(self, source: str) -> LeanRun:
        self.sources.append(source)
        return LeanRun(
            source=source,
            exit_code=None if self.timed_out else self.exit_code,
            timed_out=self.timed_out,
            duration_s=0.0,
            stdout=self.stdout,
            stderr=self.stderr,
            lean_version=self.lean_version,
        )


def _child_environment(executable_dir: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV_NAME.search(k)}
    path = env.get("PATH", "")
    env["PATH"] = f"{executable_dir}{os.pathsep}{path}" if path else str(executable_dir)
    return env


def _process_group_options() -> dict:
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        return {"creationflags": flags}
    return {"start_new_session": True}


def _kill_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if proc.poll() is None:
        proc.kill()
