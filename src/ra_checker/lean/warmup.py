"""Warm Lean up before the first real check.

The first Lean run after the computer restarts reads thousands of Mathlib
files from disk. On the development machine that took about 7 minutes (427 s)
against 24–27 s for the next runs, so with the normal time limit the first
check after a reboot always timed out. :class:`WarmingLeanRunner` starts one
throwaway check in the background with a long time limit as soon as it is
created; real checks wait for it to finish instead of racing it.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from ra_checker.lean.assemble import assemble_statement_check
from ra_checker.lean.runner import LeanRunner, LeanUnavailableError
from ra_checker.models import LeanRun

logger = logging.getLogger(__name__)

WARM_UP_TIMEOUT_S = 900.0
_WARM_UP_STATEMENT = "(x : ℝ) : x = x"


@dataclass(frozen=True)
class WarmUpStatus:
    state: str  # "running", "ready" or "failed"
    seconds: float
    message: str = ""


class WarmingLeanRunner:
    """Wraps a runner whose ``run`` accepts a ``timeout_s`` override."""

    def __init__(self, inner: LeanRunner, *, warm_up_timeout_s: float = WARM_UP_TIMEOUT_S,
                 start: bool = True) -> None:
        self.inner = inner
        self._timeout = warm_up_timeout_s
        self._done = threading.Event()
        self._started = time.monotonic()
        self._finished: float | None = None
        self._failure = ""
        self._thread = threading.Thread(target=self._warm_up, name="lean-warm-up", daemon=True)
        if start:
            self._thread.start()
        else:
            self._done.set()
            self._finished = self._started

    def _warm_up(self) -> None:
        try:
            run = self.inner.run(assemble_statement_check(_WARM_UP_STATEMENT).source, timeout_s=self._timeout)
            if run.timed_out:
                self._failure = f"Lean did not finish loading Mathlib within {self._timeout:.0f} s"
        except LeanUnavailableError as exc:
            self._failure = str(exc)
        except Exception as exc:  # noqa: BLE001 — never let a warm-up crash the app
            self._failure = f"{type(exc).__name__}: {exc}"
        finally:
            self._finished = time.monotonic()
            logger.info("Lean warm-up finished in %.0f s%s", self._finished - self._started,
                        f" ({self._failure})" if self._failure else "")
            self._done.set()

    @property
    def status(self) -> WarmUpStatus:
        if not self._done.is_set():
            return WarmUpStatus("running", time.monotonic() - self._started)
        seconds = (self._finished or self._started) - self._started
        return WarmUpStatus("failed" if self._failure else "ready", seconds, self._failure)

    def wait(self) -> WarmUpStatus:
        self._done.wait(self._timeout + 60)
        return self.status

    def run(self, source: str) -> LeanRun:
        self.wait()  # a failed warm-up does not block: the real run reports its own error
        return self.inner.run(source)

    def __getattr__(self, name):  # e.g. lean_version, project_dir
        return getattr(self.inner, name)
