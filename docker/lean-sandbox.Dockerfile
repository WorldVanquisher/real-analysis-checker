# Lean 4 + Mathlib + the RaChecker library + the Lean REPL, for running checks
# in a container without network access (milestone A8).
#
# Build from the repository root (downloads several GB once):
#   docker build -f docker/lean-sandbox.Dockerfile -t ra-checker-lean:v4.36.0 .
# Then set RA_LEAN_RUNNER=docker. Rebuild after changing anything in lean/.
#
# The network is used only while building. At check time the app starts the
# container with --network none, a read-only filesystem and dropped
# capabilities (see src/ra_checker/lean/sandbox.py).

FROM ubuntu:24.04

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash lean
USER lean
WORKDIR /home/lean

RUN curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
    | sh -s -- -y --default-toolchain none
ENV PATH="/home/lean/.elan/bin:${PATH}"

WORKDIR /home/lean/project
COPY --chown=lean lean/lean-toolchain lean/lakefile.toml lean/lake-manifest.json ./
COPY --chown=lean lean/RaChecker.lean ./
COPY --chown=lean lean/RaChecker ./RaChecker

# Same pinned toolchain, Mathlib and REPL as the local project. In the same
# step (so the image really shrinks), drop what checking never reads: the
# downloaded cache archives, generated C sources and editor index files
# (about 1.2 GB). The .git folders stay: lake consults them, and without a
# network they could not be fetched again.
RUN lake exe cache get && lake build && lake build repl \
 && rm -rf /home/lean/.cache/mathlib \
 && find .lake -name '*.c' -delete \
 && find .lake -name '*.ilean' -delete

CMD ["lake", "env", ".lake/packages/REPL/.lake/build/bin/repl"]
