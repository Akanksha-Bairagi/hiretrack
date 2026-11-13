"""Reusable Streamlit widgets and panels."""
from __future__ import annotations

import inspect
from datetime import date

import streamlit as st

from . import db as dbm
from . import nav
from .options import DEFAULT_OPTIONS, YES_NO_UNKNOWN

UNSET = "— not set —"
OTHER = "Other…"
ss = st.session_state


# ---------------------------------------------------------------- dropdown options
def option_list(category: str) -> list:
    """Built-in defaults + values the recruiter typed earlier ("Other...")."""
    if ss.get("_opt_cache") is None:
        ss["_opt_cache"] = dbm.get_db().custom_options()
    base = list(DEFAULT_OPTIONS.get(category, []))
    for v in ss["_opt_cache"].get(category, []):
        if v not in base:
            base.append(v)
    return base


def invalidate_options() -> None:
    ss["_opt_cache"] = None


def flush_custom_options() -> None:
    """Remember any custom ("Other") values used in the form that was just saved."""
    pending = ss.pop("_custom_opts", set())
    d = dbm.get_db()
    for cat, val in pending:
        if val not in DEFAULT_OPTIONS.get(cat, []):
            d.add_option(cat, val)
    if pending:
        invalidate_options()


def choice(label, key, category, current=None, help=None, allow_other=True):
    """Searchable dropdown with 'Other...' that reveals a text box. Returns str or None."""
    opts = option_list(category)
    cur = (current or "").strip() or None
    if cur and cur not in opts:
        opts = opts + [cur]
    items = [UNSET] + opts + ([OTHER] if allow_other else [])
    idx = items.index(cur) if cur in items else 0
    sel = st.selectbox(label, items, index=idx, key=key, help=help)
    if sel == UNSET:
        return None
    if sel == OTHER:
        txt = st.text_input(f"{label}: type your own", key=f"{key}__other", placeholder="Type a custom value")
        val = (txt or "").strip() or None
        if val:
            ss.setdefault("_custom_opts", set()).add((category, val))
        return val
    return sel


def yes_no(label, key, current=None, help=None):
    cur = current if current in YES_NO_UNKNOWN else "Unknown"
    return st.radio(label, YES_NO_UNKNOWN, index=YES_NO_UNKNOWN.index(cur), key=key, horizontal=True, help=help)


def num(label, key, current=None, step=0.5, help=None, max_value=None):
    return st.number_input(label, min_value=0.0, max_value=max_value, value=None if current is None else float(current),
                           step=step, key=key, help=help)


def date_in(label, key, current=None, help=None):
    return st.date_input(label, value=current, key=key, help=help, format="DD/MM/YYYY")


def skills_input(label, key, current, suggestions, help=None):
    """Type to search or add new skills. Falls back to comma-separated text on old Streamlit."""
    current = list(current or [])
    if "accept_new_options" in inspect.signature(st.multiselect).parameters:
        opts = sorted(set(suggestions) | set(current) | set(ss.get(key) or []), key=str.lower)
        kwargs = {} if key in ss else {"default": current}
        return st.multiselect(label, opts, key=key, accept_new_options=True, help=help or "Type a skill and press Enter",
                              placeholder="Type to search or add a skill", **kwargs)
    txt = st.text_input(label + " (separate with commas)", value=", ".join(current), key=key, help=help)
    return [s.strip() for s in txt.split(",") if s.strip()]


# ---------------------------------------------------------------- duplicates
def open_candidate_cb(cid: int) -> None:
    nav.go("candidates", cand=cid)


def dup_guard(email, phone, prefix, exclude_id=None) -> bool:
    """Shows possible duplicates. Returns True when saving should be BLOCKED."""
    hits = dbm.get_db().find_duplicates(email, phone, exclude_id)
    if not hits:
        return False
    st.warning(f"⚠️ This looks like someone already in HireTrack ({len(hits)} possible match"
               f"{'es' if len(hits) > 1 else ''}). Reuse the existing profile instead of creating a duplicate.")
    for h in hits:
        bits = [h.get("current_company"), h.get("email"), h.get("phone")]
        st.markdown(f"**{h['full_name']}** · matched on {h['match_on']} · " + " · ".join(b for b in bits if b))
        st.button("Open this profile", key=f"{prefix}_open_{h['id']}", on_click=open_candidate_cb, args=(h["id"],))
    ok = st.checkbox("This is a different person, create a new profile anyway", key=f"{prefix}_dupok")
    return not ok


# ---------------------------------------------------------------- candidate form
CAND_TEXT = ["full_name", "email", "phone", "current_company", "current_designation"]


def candidate_form(cand: dict | None, prefix: str, containers: dict | None = None, suggestions=()):
    """Renders every candidate field. All optional except name (checked on save). Returns values dict."""
    c = cand or {}
    v: dict = {}

    def where(section, title, expanded=True):
        if containers and section in containers:
            return containers[section]
        return st.expander(title, expanded=expanded)

    with where("basic", "Basic information"):
        a, b = st.columns(2)
        v["full_name"] = a.text_input("Full name *", value=c.get("full_name") or "", key=f"{prefix}full_name")
        v["current_company"] = b.text_input("Current company", value=c.get("current_company") or "", key=f"{prefix}company")
        v["email"] = a.text_input("Email", value=c.get("email") or "", key=f"{prefix}email")
        v["phone"] = b.text_input("Phone", value=c.get("phone") or "", key=f"{prefix}phone")
        v["current_designation"] = a.text_input("Current designation", value=c.get("current_designation") or "",
                                                key=f"{prefix}desig")
        e1, e2 = b.columns(2)
        with e1:
            v["total_exp"] = num("Total experience (yrs)", f"{prefix}texp", c.get("total_exp"))
        with e2:
            v["relevant_exp"] = num("Relevant experience (yrs)", f"{prefix}rexp", c.get("relevant_exp"))
        v["_resume"] = st.file_uploader("Resume (optional, PDF/Word)", type=["pdf", "doc", "docx"], key=f"{prefix}resume")
        meta = dbm.get_db().file_meta("resume", candidate_id=c["id"]) if c.get("id") else None
        if meta:
            st.caption(f"Resume on file: {meta['filename']} ({meta['size_bytes'] // 1024} KB). "
                       "Upload a new one to replace it.")

    with where("skills", "Technical information"):
        v["primary_skills"] = skills_input("Primary skills", f"{prefix}pskills", c.get("primary_skills"), suggestions,
                                           help="The skills used day-to-day. These are matched against the job.")
        v["secondary_skills"] = skills_input("Secondary skills", f"{prefix}sskills", c.get("secondary_skills"), suggestions)
        v["additional_skills"] = skills_input("Additional skills", f"{prefix}askills", c.get("additional_skills"), suggestions)
        v["project_experience"] = st.text_area("Relevant project experience", value=c.get("project_experience") or "",
                                               key=f"{prefix}proj", height=120)

    with where("comp", "Compensation"):
        a, b, cc = st.columns(3)
        with a:
            v["current_ctc"] = num("Current CTC (LPA)", f"{prefix}cctc", c.get("current_ctc"))
        with b:
            v["expected_ctc"] = num("Expected CTC (LPA)", f"{prefix}ectc", c.get("expected_ctc"))
        with cc:
            v["negotiable"] = yes_no("Negotiable?", f"{prefix}neg", c.get("negotiable"))

    with where("prefs", "Job preferences"):
        a, b = st.columns(2)
        with a:
            v["current_city"] = choice("Current city", f"{prefix}city", "city", c.get("current_city"))
            v["relocation"] = choice("Relocation", f"{prefix}reloc", "relocation", c.get("relocation"))
        with b:
            v["preferred_location"] = choice("Preferred job location", f"{prefix}pref", "city", c.get("preferred_location"))
            v["work_mode_pref"] = choice("Work mode preference", f"{prefix}wm", "work_mode", c.get("work_mode_pref"))
        v["reason_for_switch"] = st.text_area("Reason for switching", value=c.get("reason_for_switch") or "",
                                              key=f"{prefix}why", height=90)

    with where("avail", "Availability"):
        a, b = st.columns(2)
        with a:
            v["employment_status"] = choice("Employment status", f"{prefix}emp", "employment_status",
                                            c.get("employment_status"))
            v["notice_period"] = choice("Notice period", f"{prefix}notice", "notice_period", c.get("notice_period"))
            v["immediate_joiner"] = yes_no("Immediate joiner?", f"{prefix}imm", c.get("immediate_joiner"))
        with b:
            v["last_working_day"] = date_in("Last working day (optional)", f"{prefix}lwd", c.get("last_working_day"),
                                            help="If filled, the notice period is worked out from this date.")
            v["earliest_joining"] = date_in("Earliest joining date (optional)", f"{prefix}ejd", c.get("earliest_joining"))
    return v


def save_resume(candidate_id: int, upload) -> str | None:
    """Stores an uploaded resume. Returns an error message or None."""
    if upload is None:
        return None
    data = upload.getvalue()
    if len(data) > 8 * 1024 * 1024:
        return "Resume is larger than 8 MB, so it was not attached."
    meta = dbm.get_db().file_meta("resume", candidate_id=candidate_id)
    if meta and meta["filename"] == upload.name and meta["size_bytes"] == len(data):
        return None  # same file already stored
    dbm.get_db().save_file("resume", upload.name, upload.type or "application/octet-stream", data,
                           candidate_id=candidate_id)
    return None


def clean_candidate_values(v: dict) -> dict:
    return {k: val for k, val in v.items() if not k.startswith("_")}


# ---------------------------------------------------------------- tables
def table_picker(df, ids, key, label_fn, select_label="Open details for", column_config=None):
    """DataFrame you can click a row in, plus a dropdown fallback. Returns the chosen id or None."""
    ev = st.dataframe(df, hide_index=True, on_select="rerun", selection_mode="single-row",
                      key=f"{key}_tbl", column_config=column_config)
    try:
        rows = list(ev.selection.rows)
    except Exception:
        rows = list((ev or {}).get("selection", {}).get("rows", []))
    sel_key = f"{key}_sel"
    if rows and rows[0] < len(ids):
        sig = (rows[0], ids[rows[0]])
        if ss.get(f"{key}_sig") != sig:
            ss[f"{key}_sig"] = sig
            ss[sel_key] = ids[rows[0]]
    if ss.get(sel_key) not in ids:
        ss.pop(sel_key, None)
    return st.selectbox(select_label, ids, format_func=label_fn, index=None, key=sel_key,
                        placeholder="Click a row above, or pick here")


# ---------------------------------------------------------------- explanation
def render_explanation(res: dict, name: str = "") -> None:
    a, b, c = st.columns(3)
    a.metric("Score", f"{res['total']:.0f} / 100")
    b.metric("Confidence", res["confidence"])
    c.metric("Possible range", f"{res['low']:.0f} – {res['high']:.0f}",
             help="What the score could be once missing information is filled in (worst case to best case).")
    st.caption(f"Automatic assessment: **{res['label']}**. This is calculated from the saved data and is separate "
               "from your own recommendation.")
    for f in res["flags"]:
        {"error": st.error, "warning": st.warning}.get(f["level"], st.info)(f["text"])
    st.markdown("**How the score was built**")
    for c_ in res["criteria"].values():
        est = " · ⚠️ estimated (information missing)" if not c_["known"] else ""
        st.markdown(f"**{c_['label']}**: {c_['points']:.1f} of {c_['weight']:.0f} points{est}")
        st.progress(float(min(max(c_["score"], 0.0), 1.0)))
        st.caption(c_["assessment"])
    s = res["skills"]
    if s["mandatory_matched"] or s["mandatory_missing"] or s["preferred_matched"] or s["additional"]:
        st.markdown("**Skills**")
        st.write("✅ Mandatory matched: " + (", ".join(s["mandatory_matched"]) or "none"))
        if s["mandatory_missing"]:
            st.write("❌ **Mandatory missing: " + ", ".join(s["mandatory_missing"]) + "**")
        st.write("➕ Preferred matched: " + (", ".join(s["preferred_matched"]) or "none"))
        if s["additional"]:
            st.write("Other skills: " + ", ".join(s["additional"]))
    if res["positives"]:
        st.markdown("**Reasons for a positive ranking**")
        for t in res["positives"]:
            st.write("• " + t)
    if res["deductions"]:
        st.markdown("**Reasons for deductions**")
        for t in res["deductions"]:
            st.write("• " + t)
    if res["missing_info"]:
        st.markdown("**Missing information** (counted as half marks, lowers confidence)")
        for t in res["missing_info"]:
            st.write("• " + t)


def fmt_date(d) -> str:
    return d.strftime("%d %b %Y") if isinstance(d, date) else ""
