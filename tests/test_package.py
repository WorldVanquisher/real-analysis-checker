"""Smoke test for the B0 scaffold: the package installs and imports."""

import re

import ra_checker


def test_package_exposes_semantic_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", ra_checker.__version__)
