"""A Lean runner that keeps Mathlib loaded between checks (milestone A8).

The command-line runner pays about 25 s per check to import Mathlib. The
community Lean REPL (``leanprover-community/repl``, pinned in
``lean/lakefile.toml``) loads ``import Mathlib`` and ``import RaChecker`` once
into a base environment; every check then runs as a command *on that base
environment*, so checks never see each other's declarations, and take well
under a second.

Equivalence with the command-line runner is by construction:

* the checked file is the same assembled source, with only its leading import
  lines blanked out (so Lean's positions are the file's own line numbers);
* the REPL's messages carry the same text Lean prints on the command line;
  they are rendered back into that format, so the same parser and the same
  verdict rules decide;
* a source with imports beyond the base environment's goes to the
  command-line runner instead.

Robustness: one check at a time (a lock); a check that exceeds its time limit
kills the REPL's whole process tree and the next check starts a fresh one; the
REPL is also restarted after :data:`MAX_CHECKS_PER_PROCESS` checks to bound
memory; a crash or protocol error becomes a failed run, never a verdict.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from ra_checker.lean.assemble import HEADER_IMPORTS
from ra_checker.lean.runner import (
    CHECK_FILE_NAME,
    LeanUnavailableError,
    SubprocessLeanRunner,
    _child_environment,
    _kill_process_tree,
    _process_group_options,
    find_lake,
)
from ra_checker.models import LeanRun

logger = logging.getLogger(__name__)

MAX_CHECKS_PER_PROCESS = 200
START_TIMEOUT_S = 900.0
_EOF = object()
_AXIOM_REPORT_RE = re.compile(r"^'[^']+' (?:depends on axioms: \[|does not depend on any axioms)")


def find_repl(project_dir: Path) -> Path | None:
    exe = "repl.exe" if os.name == "nt" else "repl"
    path = Path(project_dir) / ".lake" / "packages" / "REPL" / ".lake" / "build" / "bin" / exe
    return path if path.is_file() else None


class ReplLeanRunner:
    def __init__(
        self,
        project_dir: Path,
        timeout_s: float,
        *,
        command: Sequence[str] | None = None,
        fallback: SubprocessLeanRunner | None = None,
        imports: Sequence[str] = HEADER_IMPORTS,
        max_checks_per_process: int = MAX_CHECKS_PER_PROCESS,
        start_timeout_s: float = START_TIMEOUT_S,
        on_stop: Callable[[], None] | None = None,
        version_command: Sequence[str] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.timeout_s = timeout_s
        if command is None:
            lake, repl = find_lake(), find_repl(self.project_dir)
            if lake is None or repl is None:
                raise LeanUnavailableError(
                    "The Lean REPL is not built: run `lake build repl` in the lean/ folder."
                )
            command = (str(lake), "env", str(repl))
        self.command = tuple(command)
        self.fallback = fallback
        self.imports = tuple(imports)
        self.max_checks = max_checks_per_process
        self.start_timeout_s = start_timeout_s
        self._on_stop = on_stop  # e.g. remove the Docker container
        self._version_command = tuple(version_command) if version_command else None
        self._version: str | None = None
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._responses: queue.Queue = queue.Queue()
        self._stderr_tail: list[str] = []
        self._base_env: int | None = None
        self._readers: list[threading.Thread] = []
        self._checks = 0
        self.starts = 0  # how many REPL processes were started (for tests and logs)

    # ------------------------------------------------------------------ public

    def run(self, source: str, timeout_s: float | None = None) -> LeanRun:
        imports, body = _split_imports(source)
        if not set(imports) <= set(self.imports):
            if self.fallback is None:
                raise LeanUnavailableError(f"imports {imports} are not available in the Lean REPL")
            return self.fallback.run(source, timeout_s)
        limit = timeout_s or self.timeout_s
        with self._lock:
            start = time.monotonic()
            if self._checks >= self.max_checks:
                self._stop()
            if self._proc is None or self._proc.poll() is not None:
                self._start(max(limit, self.start_timeout_s))
            self._checks += 1
            response = self._send({"cmd": body, "env": self._base_env}, limit)
            duration = time.monotonic() - start
            if response is None:  # timed out: the process was killed
                return LeanRun(source=source, exit_code=None, timed_out=True, duration_s=duration,
                               lean_version=self.lean_version())
            if response is _EOF:
                code = self._proc.wait(timeout=10) if self._proc else None
                self._stop()
                return LeanRun(source=source, exit_code=code if code not in (None, 0) else 3,
                               duration_s=duration, stderr="\n".join(self._stderr_tail),
                               lean_version=self.lean_version())
            stdout, exit_code, stderr = _render(response)
            return LeanRun(source=source, exit_code=exit_code, duration_s=duration,
                           stdout=stdout, stderr=stderr, lean_version=self.lean_version())

    def lean_version(self) -> str | None:
        if self.fallback is not None:
            return self.fallback.lean_version()
        if self._version is None and self._version_command:
            try:
                done = subprocess.run(list(self._version_command), capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=120,
                                      **_process_group_options())
                if done.returncode == 0 and done.stdout.strip():
                    self._version = done.stdout.strip().splitlines()[0]
            except (OSError, subprocess.TimeoutExpired):
                pass
        return self._version

    def close(self) -> None:
        with self._lock:
            self._stop()

    # --------------------------------------------------------------- internals

    def _start(self, timeout: float) -> None:
        self._stop()
        self.starts += 1
        self._responses = queue.Queue()
        self._stderr_tail = []
        try:
            self._proc = subprocess.Popen(
                list(self.command),
                cwd=self.project_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_child_environment(Path(self.command[0]).parent),
                **_process_group_options(),
            )
        except OSError as exc:
            raise LeanUnavailableError(f"could not start the Lean REPL ({type(exc).__name__})") from exc
        self._readers = [
            threading.Thread(target=self._read_stdout, args=(self._proc, self._responses), daemon=True),
            threading.Thread(target=self._read_stderr, args=(self._proc,), daemon=True),
        ]
        for thread in self._readers:
            thread.start()

        header = "\n".join(f"import {module}" for module in self.imports)
        started = time.monotonic()
        response = self._send({"cmd": header}, timeout)
        if not isinstance(response, dict) or "env" not in response:
            self._stop()
            raise LeanUnavailableError("the Lean REPL did not load Mathlib (timed out or crashed)")
        errors = [m["data"] for m in response.get("messages", []) if m.get("severity") == "error"]
        if errors:
            self._stop()
            raise LeanUnavailableError(
                f"the Lean REPL could not load {', '.join(self.imports)}: {errors[0].splitlines()[0]}; "
                "run `lake build` in the lean/ folder"
            )
        self._base_env = response["env"]
        self._checks = 0
        logger.info("Lean REPL #%d ready in %.0f s", self.starts, time.monotonic() - started)

    def _send(self, request: dict, timeout: float):
        """The parsed response, None on timeout (process killed), or _EOF."""
        assert self._proc is not None and self._proc.stdin is not None
        try:
            self._proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n\n")
            self._proc.stdin.flush()
        except OSError:
            return _EOF
        try:
            return self._responses.get(timeout=timeout)
        except queue.Empty:
            logger.warning("Lean REPL check exceeded %.0f s; restarting the REPL", timeout)
            self._stop()
            return None

    def _stop(self) -> None:
        proc, self._proc = self._proc, None
        self._base_env = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        _kill_process_tree(proc)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        for thread in self._readers:
            thread.join(timeout=5)
        for pipe in (proc.stdout, proc.stderr):
            try:
                if pipe:
                    pipe.close()
            except OSError:
                pass
        if self._on_stop is not None:
            try:
                self._on_stop()
            except Exception:  # noqa: BLE001 — cleanup must never break a check
                logger.warning("Lean REPL cleanup failed", exc_info=True)

    @staticmethod
    def _read_stdout(proc: subprocess.Popen, responses: queue.Queue) -> None:
        block: list[str] = []
        try:
            for line in proc.stdout:
                if line.strip():
                    block.append(line)
                    continue
                if block:
                    try:
                        responses.put(json.loads("".join(block)))
                    except json.JSONDecodeError:
                        responses.put({"message": "the Lean REPL sent malformed output"})
                    block = []
        except (OSError, ValueError):  # the pipe was closed under us
            pass
        responses.put(_EOF)

    def _read_stderr(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stderr:
                self._stderr_tail = (self._stderr_tail + [line.rstrip()])[-20:]
        except (OSError, ValueError):
            pass


def _split_imports(source: str) -> tuple[tuple[str, ...], str]:
    """Leading ``import`` lines, and the source with those lines blanked (line
    numbers are kept, so Lean's positions are the file's own)."""
    lines = source.split("\n")
    imports = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import "):
            imports.append(stripped.removeprefix("import ").strip())
            lines[index] = ""
        elif stripped:
            break
    return tuple(imports), "\n".join(lines)


def _render(response: dict) -> tuple[str, int, str]:
    """REPL JSON → (Lean command-line style output, exit code, stderr)."""
    if "message" in response and "env" not in response:  # the REPL rejected the command itself
        return "", 2, str(response["message"])
    rendered = []
    has_error = False
    for message in response.get("messages", []):
        severity = message.get("severity", "error")
        data = message.get("data", "")
        has_error |= severity == "error"
        if severity == "info" and _AXIOM_REPORT_RE.match(data):
            rendered.append(data)  # the command line prints `#print axioms` as a bare line
            continue
        pos = message.get("pos") or {"line": 1, "column": 0}
        rendered.append(f"{CHECK_FILE_NAME}:{pos['line']}:{pos['column']}: {severity}: {data}")
    return "\n".join(rendered) + ("\n" if rendered else ""), int(has_error), ""
