"""Tests for ra_checker.lean.warmup (no real Lean)."""

import threading

from ra_checker.lean.runner import LeanUnavailableError
from ra_checker.lean.warmup import WarmingLeanRunner
from ra_checker.models import LeanRun


class SlowInner:
    """Fake runner: the warm-up blocks until released; records every call."""

    def __init__(self, warm_up_result="ok"):
        self.release = threading.Event()
        self.calls: list[tuple[str, float | None]] = []
        self.warm_up_result = warm_up_result
        self.project_dir = "lean"

    def run(self, source, timeout_s=None):
        self.calls.append((source, timeout_s))
        if timeout_s is not None:  # the warm-up call
            assert self.release.wait(5)
            if self.warm_up_result == "unavailable":
                raise LeanUnavailableError("lake not found")
            timed_out = self.warm_up_result == "timeout"
            return LeanRun(source=source, exit_code=None if timed_out else 0, timed_out=timed_out, duration_s=1)
        return LeanRun(source=source, exit_code=0, duration_s=1)


def test_warm_up_runs_once_with_the_long_timeout_and_real_runs_wait():
    inner = SlowInner()
    runner = WarmingLeanRunner(inner, warm_up_timeout_s=900)
    assert runner.status.state == "running"

    results = []
    worker = threading.Thread(target=lambda: results.append(runner.run("real check")))
    worker.start()
    worker.join(0.3)
    assert worker.is_alive() and results == []  # waiting for the warm-up
    inner.release.set()
    worker.join(5)
    assert results and results[0].source == "real check"
    assert runner.status.state == "ready"
    assert [timeout for _, timeout in inner.calls] == [900, None]
    assert "sorry" in inner.calls[0][0]  # the warm-up is a statement check


def test_failed_warm_up_does_not_block_real_checks():
    for outcome, message in (("timeout", "did not finish"), ("unavailable", "lake not found")):
        inner = SlowInner(outcome)
        inner.release.set()
        runner = WarmingLeanRunner(inner)
        status = runner.wait()
        assert status.state == "failed" and message in status.message
        assert runner.run("real check").exit_code == 0


def test_not_started_means_ready_and_attributes_pass_through():
    inner = SlowInner()
    runner = WarmingLeanRunner(inner, start=False)
    assert runner.status.state == "ready"
    assert runner.run("x").exit_code == 0
    assert inner.calls == [("x", None)]
    assert runner.project_dir == "lean"
