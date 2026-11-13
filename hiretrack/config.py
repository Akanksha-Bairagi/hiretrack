"""Reads settings from environment variables first, then Streamlit secrets."""
from __future__ import annotations

import os


def get_setting(name: str, default=None):
    value = os.environ.get(name)
    if value:
        return value
    try:  # Streamlit secrets are optional (absent when running tests/CLI)
        import streamlit as st

        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return default
