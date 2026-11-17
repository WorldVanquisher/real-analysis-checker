"""The app's access to the Checker.

Tests (and only tests) inject a Checker built from fakes through
``st.session_state["checker"]``; otherwise the real one is built once per
server process (``ra_checker.setup``).
"""

from __future__ import annotations

import streamlit as st

from ra_checker.pipeline import Checker
from ra_checker.setup import build_checker

INJECTED_CHECKER_KEY = "checker"


def get_checker() -> tuple[Checker | None, list[str]]:
    injected = st.session_state.get(INJECTED_CHECKER_KEY)
    if injected is not None:
        return injected, []
    return _build_checker()


@st.cache_resource(show_spinner=False)
def _build_checker() -> tuple[Checker | None, list[str]]:
    return build_checker()
