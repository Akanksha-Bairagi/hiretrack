"""Runs app.py repeatedly against the fake Streamlit, emulating reruns and widget-state cleanup."""
import os
import runpy
import sys

from tests import fake_streamlit as fk
from tests.helpers import fresh_db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Runner:
    def __init__(self):
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        os.environ.pop("APP_PASSWORD", None)
        os.environ.pop("DATABASE_URL", None)
        self.db = fresh_db()
        self.st = fk.install()
        self.H = self.st.harness
        self.ss = self.st.session_state
        self.widget_keys = set()

    # -- one script execution
    def _once(self):
        H, ss = self.H, self.ss
        H["seen"] = set()
        H["log"] = []
        ss.drawn = set()
        try:
            runpy.run_path(os.path.join(ROOT, "app.py"), run_name="__main__")
        except fk.Rerun:
            return "rerun"
        except fk.Stop:
            return "stop"
        finally:
            used = {k for k in H["seen"] if isinstance(k, str)}
            self.widget_keys |= used
            for k in list(self.widget_keys - used):  # widgets not drawn this run lose their state
                dict.pop(ss, k, None)
                self.widget_keys.discard(k)
        return "done"

    def run(self, page=None, clicks=(), set_values=None, uploads=None, selected=None):
        H, ss = self.H, self.ss
        if page:
            H["page"] = page
        for k, v in (set_values or {}).items():
            dict.__setitem__(ss, k, v)
        H["uploads"] = uploads or {}
        H["selected"] = selected or {}
        H["clicks"] = set(clicks)
        for i in range(8):
            r = self._once()
            H["clicks"] = set()  # a click only lasts for one run
            if r != "rerun":
                return self
        raise AssertionError("too many reruns (possible rerun loop)")

    # -- helpers for assertions
    def texts(self, kind=None):
        return [t for k, t in self.H["log"] if kind is None or k == kind]

    def has(self, needle, kind=None):
        return any(needle in t for t in self.texts(kind))

    def errors(self):
        return self.texts("error")
