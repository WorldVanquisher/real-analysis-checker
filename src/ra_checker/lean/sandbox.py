"""Run Lean inside a Docker container with no network (milestone A8).

The image (``docker/lean-sandbox.Dockerfile``) contains the same pinned Lean
toolchain, Mathlib, RaChecker library and Lean REPL as the local project. The
container runs the REPL with:

* ``--network none`` — generated code can never reach the network;
* ``--read-only`` with a small ``/tmp`` tmpfs — it cannot change the image;
* ``--cap-drop ALL`` and ``no-new-privileges`` — no Linux capabilities;
* memory, CPU and process-count limits.

It is the same :class:`ReplLeanRunner` as the local one, pointed at
``docker run -i`` instead of a local process, so verdicts come from exactly the
same code path. There is deliberately no fallback to local Lean: a source with
imports beyond the image's base environment is refused, so nothing escapes the
sandbox. Stopping the REPL (timeout, crash, restart) also removes the
container.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

from ra_checker.lean.repl import ReplLeanRunner
from ra_checker.lean.runner import LeanUnavailableError, _process_group_options

DOCKERFILE = "docker/lean-sandbox.Dockerfile"
REPL_IN_IMAGE = ".lake/packages/REPL/.lake/build/bin/repl"
SANDBOX_FLAGS: tuple[str, ...] = (
    "--network", "none",
    "--read-only", "--tmpfs", "/tmp:rw,size=256m",
    "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges",
    "--pids-limit", "512",
    "--memory", "8g",
    "--cpus", "4",
)  # fmt: skip


def find_docker() -> str | None:
    return shutil.which("docker")


def image_available(docker: str, image: str) -> bool:
    try:
        done = subprocess.run([docker, "image", "inspect", image], capture_output=True, timeout=60,
                              **_process_group_options())
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def sandbox_command(docker: str, image: str, name: str) -> tuple[str, ...]:
    return (docker, "run", "--rm", "-i", "--name", name, *SANDBOX_FLAGS, image, "lake", "env", REPL_IN_IMAGE)


def make_sandbox_runner(image: str, timeout_s: float, workdir: Path) -> ReplLeanRunner:
    """Raises LeanUnavailableError with instructions if Docker or the image is missing."""
    docker = find_docker()
    if docker is None:
        raise LeanUnavailableError("RA_LEAN_RUNNER=docker, but Docker is not installed or not on PATH.")
    if not image_available(docker, image):
        raise LeanUnavailableError(
            f"RA_LEAN_RUNNER=docker, but the image {image} is not available (or Docker is not "
            f"running). Build it with: docker build -f {DOCKERFILE} -t {image} ."
        )
    name = f"ra-checker-lean-{uuid.uuid4().hex[:12]}"

    def remove_container() -> None:
        subprocess.run([docker, "rm", "-f", name], capture_output=True, timeout=60, **_process_group_options())

    return ReplLeanRunner(
        Path(workdir),
        timeout_s,
        command=sandbox_command(docker, image, name),
        fallback=None,
        on_stop=remove_container,
        version_command=(docker, "run", "--rm", "--network", "none", image, "lean", "--version"),
    )
