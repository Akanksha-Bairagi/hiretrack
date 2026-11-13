"""A deliberately STRICT stand-in for Streamlit, used to smoke-test the UI code in an environment
where Streamlit cannot be installed. It is not Streamlit: it cannot prove the pages look right. It
does catch the classic mistakes: typos, wrong variables, duplicate widget keys, writing widget state
after the widget was drawn, selectbox values missing from options, number limits."""
from __future__ import annotations

import sys
import types


class StreamlitAPIException(Exception):
    pass


class Rerun(Exception):
    pass


class Stop(Exception):
    pass


class State(dict):
    """session_state with attribute access and write-after-widget protection."""

    def __init__(self):
        super().__init__()
        self.drawn = set()
        self.in_callback = False

    def __setitem__(self, k, v):
        if k in self.drawn and not self.in_callback:
            raise StreamlitAPIException(f"`st.session_state.{k}` cannot be modified after the widget with key `{k}` is instantiated.")
        super().__setitem__(k, v)

    def setdefault(self, k, v=None):
        if k not in self:
            self[k] = v
        return self[k]

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e


class Ctx:
    def __init__(self, mod):
        self._mod = mod

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, name):
        return getattr(self._mod, name)


class Selection:
    def __init__(self, rows):
        self.rows = rows


class Event:
    def __init__(self, rows):
        self.selection = Selection(rows)


class Page:
    def __init__(self, fn, title=None, icon=None, url_path=None, default=False):
        self.fn, self.title, self.url_path, self.default = fn, title, url_path, default


class Nav:
    def __init__(self, mod, pages):
        self.mod, self.pages = mod, pages

    def run(self):
        target = self.mod.harness["page"]
        for p in self.pages:
            if p.url_path == target or (target is None and p.default):
                return p.fn()
        raise StreamlitAPIException("no such page " + str(target))


def build():
    m = types.ModuleType("streamlit")
    m.StreamlitAPIException = StreamlitAPIException
    m.session_state = State()
    m.harness = {"page": "home", "clicks": set(), "uploads": {}, "selected": {}, "seen": set(), "log": [],
                 "switches": [], "run_no": 0}
    H = m.harness
    ss = m.session_state

    def log(kind, text):
        H["log"].append((kind, str(text)))

    def ident(kind, label, key):
        k = key if key is not None else (kind, label)
        if k in H["seen"]:
            raise StreamlitAPIException(f"DuplicateWidgetID: {kind} {label!r} key={key!r}")
        H["seen"].add(k)
        if key is not None:
            ss.drawn.add(key)
        return k

    def init(key, value):
        if key is not None and key not in ss:
            dict.__setitem__(ss, key, value)
        return dict.get(ss, key, value) if key is not None else value

    # ---- text-ish
    def text_input(label, value="", key=None, **kw):
        ident("text_input", label, key)
        return init(key, value)

    text_area = text_input

    def number_input(label, min_value=None, max_value=None, value=None, step=None, key=None, **kw):
        ident("number_input", label, key)
        v = init(key, value)
        if v is not None and min_value is not None and v < min_value:
            raise StreamlitAPIException(f"number_input {label!r}: value {v} < min {min_value}")
        if v is not None and max_value is not None and v > max_value:
            raise StreamlitAPIException(f"number_input {label!r}: value {v} > max {max_value}")
        return v

    def date_input(label, value=None, key=None, **kw):
        ident("date_input", label, key)
        return init(key, value)

    def checkbox(label, value=False, key=None, **kw):
        ident("checkbox", label, key)
        return init(key, value)

    def _choose(kind, label, options, index, key, multi=False):
        options = list(options)
        ident(kind, label, key)
        if key is not None and key not in ss:
            dict.__setitem__(ss, key, (options[index] if (index is not None and options) else None))
        v = dict.get(ss, key) if key is not None else (options[index] if index is not None and options else None)
        if v is not None and v not in options:
            raise StreamlitAPIException(f"{kind} {label!r}: value {v!r} not in options {options[:6]}")
        return v

    def selectbox(label, options, index=0, key=None, format_func=None, **kw):
        opts = list(options)
        if format_func:
            [format_func(o) for o in opts]  # make sure formatting never crashes
        return _choose("selectbox", label, opts, index, key)

    def radio(label, options, index=0, key=None, **kw):
        return _choose("radio", label, options, index, key)

    def multiselect(label, options=(), default=None, key=None, accept_new_options=False, **kw):
        ident("multiselect", label, key)
        opts = list(options)
        v = init(key, list(default or []))
        if not accept_new_options:
            for x in v:
                if x not in opts:
                    raise StreamlitAPIException(f"multiselect {label!r}: {x!r} not in options")
        return list(v)

    def file_uploader(label, type=None, key=None, **kw):
        ident("file_uploader", label, key)
        return H["uploads"].get(key)

    # ---- buttons
    def _button(kind, label, key=None, on_click=None, args=(), kwargs=None, disabled=False, **kw):
        ident(kind, label, key)
        if disabled:
            return False
        if (key and key in H["clicks"]) or label in H["clicks"]:
            if on_click:
                ss.in_callback = True
                try:
                    on_click(*args, **(kwargs or {}))
                finally:
                    ss.in_callback = False
            return True
        return False

    def button(label, key=None, **kw):
        return _button("button", label, key, **kw)

    def form_submit_button(label, **kw):
        return _button("form_submit_button", label, None, **kw)

    def download_button(label, data=None, file_name=None, mime=None, key=None, on_click=None, **kw):
        ident("download_button", label, key)
        if data is None or (hasattr(data, "__len__") and len(data) == 0):
            raise StreamlitAPIException("download_button without data")
        if (key and key in H["clicks"]) and on_click:
            on_click()
        return False

    # ---- display
    for name in ("title", "header", "subheader", "markdown", "write", "caption", "code", "divider", "progress",
                 "success", "info", "warning", "error", "toast", "metric", "json", "text"):
        def _mk(n):
            def f(*a, **k):
                log(n, a[0] if a else "")
                if n == "progress":
                    v = a[0] if a else k.get("value")
                    if not (0.0 <= float(v) <= 1.0):
                        raise StreamlitAPIException("progress out of range")
            return f
        setattr(m, name, _mk(name))

    def dataframe(df, hide_index=None, on_select=None, selection_mode=None, key=None, column_config=None, **kw):
        if key:
            ident("dataframe", key, key + "__df")
        log("dataframe", f"{len(df)} rows x {len(df.columns)} cols")
        for col in (column_config or {}):
            if col not in df.columns:
                raise StreamlitAPIException(f"column_config for missing column {col}")
        return Event(list(H["selected"].get(key, [])))

    def columns(spec, **kw):
        n = spec if isinstance(spec, int) else len(spec)
        return [Ctx(m) for _ in range(n)]

    def tabs(labels):
        return [Ctx(m) for _ in labels]

    def expander(label, expanded=False, **kw):
        return Ctx(m)

    def container(**kw):
        return Ctx(m)

    def popover(label, **kw):
        return Ctx(m)

    def spinner(*a, **k):
        return Ctx(m)

    def form(key, **kw):
        return Ctx(m)

    def empty():
        return Ctx(m)

    def rerun():
        raise Rerun()

    def stop():
        raise Stop()

    def switch_page(page):
        H["switches"].append(page.url_path)
        H["page"] = page.url_path
        raise Rerun()

    def set_page_config(**kw):
        pass

    def navigation(pages, **kw):
        return Nav(m, list(pages))

    for k, v in dict(text_input=text_input, text_area=text_area, number_input=number_input, date_input=date_input,
                     checkbox=checkbox, selectbox=selectbox, radio=radio, multiselect=multiselect,
                     file_uploader=file_uploader, button=button, form_submit_button=form_submit_button,
                     download_button=download_button, dataframe=dataframe, columns=columns, tabs=tabs,
                     expander=expander, container=container, popover=popover, spinner=spinner, form=form,
                     empty=empty, rerun=rerun, stop=stop, switch_page=switch_page, set_page_config=set_page_config,
                     navigation=navigation, Page=Page).items():
        setattr(m, k, v)
    m.sidebar = Ctx(m)
    m.secrets = {}
    m.column_config = types.SimpleNamespace(
        ProgressColumn=lambda *a, **k: ("progress", a, k), NumberColumn=lambda *a, **k: ("number", a, k))
    return m


def install():
    """Install a fresh fake and purge app modules so they bind to it."""
    for name in [n for n in sys.modules if n == "views" or n.startswith("views.") or n == "hiretrack.ui"
                 or n == "hiretrack.nav" or n == "hiretrack.auth"]:
        del sys.modules[name]
    pkg = sys.modules.get("hiretrack")
    for attr in ("ui", "nav", "auth"):
        if pkg is not None and hasattr(pkg, attr):
            delattr(pkg, attr)  # otherwise `from hiretrack import ui` returns the stale module
    m = build()
    sys.modules["streamlit"] = m
    return m
