"""Single-password gate. The password lives in secrets / environment, never in code."""
from __future__ import annotations

import hmac
import time
from collections import deque

import streamlit as st

from .config import get_setting

_FAILS: deque = deque(maxlen=50)  # timestamps of recent failed attempts (shared by all sessions)
MAX_FAILS, WINDOW = 8, 600


def _locked() -> int:
    now = time.time()
    recent = [t for t in _FAILS if now - t < WINDOW]
    return int(WINDOW - (now - recent[0])) if len(recent) >= MAX_FAILS else 0


def password_required() -> bool:
    return bool(get_setting("APP_PASSWORD"))


def require_login(remote_db: bool) -> None:
    """Stops the script unless the visitor is signed in."""
    pw = get_setting("APP_PASSWORD")
    if not pw:
        if remote_db:
            st.error("This deployment has a cloud database but no APP_PASSWORD is set, so it is locked for "
                     "your safety. Add APP_PASSWORD in the app's Secrets and reboot the app.")
            st.stop()
        return  # local single-user mode
    if st.session_state.get("_authed"):
        return
    st.title("🧭 HireTrack")
    st.write("Please sign in to continue.")
    with st.form("login"):
        entered = st.text_input("Password", type="password")
        go = st.form_submit_button("Sign in")
    if go:
        wait = _locked()
        if wait:
            st.error(f"Too many wrong attempts. Please wait about {wait // 60 + 1} minute(s) and try again.")
        elif hmac.compare_digest(entered.encode(), str(pw).encode()):
            st.session_state["_authed"] = True
            st.rerun()
        else:
            _FAILS.append(time.time())
            st.error("Wrong password.")
    st.stop()


def logout_button() -> None:
    if password_required() and st.session_state.get("_authed"):
        if st.sidebar.button("Sign out"):
            st.session_state.clear()
            st.rerun()
