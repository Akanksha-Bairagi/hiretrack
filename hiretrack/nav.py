"""Tiny navigation helpers. Pages are registered by app.py; other pages ask to go somewhere by
setting session flags that app.py applies at the start of the next run (safe inside callbacks)."""
from __future__ import annotations

import streamlit as st

PAGES: dict = {}


def go(page_key: str, **state) -> None:
    """Request navigation to a page (optionally selecting a job/candidate/application first)."""
    ss = st.session_state
    ss["_goto"] = page_key
    for k, v in state.items():
        ss[f"_pending_{k}"] = v


def select_job(job_id: int) -> None:
    st.session_state["_pending_job"] = job_id


def apply_pending() -> None:
    """Called by app.py before widgets are drawn."""
    ss = st.session_state
    if "_pending_job" in ss:
        ss["sel_job_id"] = ss.pop("_pending_job")
    target = ss.pop("_goto", None)
    if target and target in PAGES:
        st.switch_page(PAGES[target])
