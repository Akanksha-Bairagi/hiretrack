from datetime import datetime

import streamlit as st

from hiretrack import db as dbm
from hiretrack import nav, service, ui
from hiretrack.options import APP_STATUSES
from hiretrack.scoring import compute_score

ss = st.session_state
ICON = {"Completed": "✅", "Draft saved": "📝", "Not started": "⏳"}


def _add_candidate_panel(job_id, has_apps):
    d = dbm.get_db()
    with st.expander("➕ Add a candidate to this job", expanded=not has_apps):
        t_exist, t_new = st.tabs(["Existing candidate", "New candidate"])
        with t_exist:
            in_job = {a["candidate_id"] for a, _ in d.job_pairs(job_id, include_archived=True)}
            options = [c for c in d.rows("candidates", "archived = ?", (False,), order="full_name") if c["id"] not in in_job]
            if not options:
                st.caption("Everyone in your database is already on this job (or you have no candidates yet).")
            else:
                ids = [c["id"] for c in options]
                lookup = {c["id"]: c for c in options}
                cid = st.selectbox(
                    "Search by name", ids, index=None, key=f"scr_exist_{job_id}", placeholder="Start typing a name…",
                    format_func=lambda i: " · ".join(x for x in (lookup[i]["full_name"], lookup[i]["current_company"],
                                                                 lookup[i]["current_city"]) if x))
                if cid and st.button("Add to this job", key=f"scr_addexist_{job_id}", type="primary"):
                    app_id = d.add_application(job_id, cid)
                    ss[f"_pending_scr_app_{job_id}"] = app_id
                    st.rerun()
        with t_new:
            st.caption("Just the basics now. Everything else is filled in during the call.")
            a, b = st.columns(2)
            name = a.text_input("Full name *", key=f"qn_name_{job_id}")
            phone = b.text_input("Phone", key=f"qn_phone_{job_id}")
            email = a.text_input("Email", key=f"qn_email_{job_id}")
            company = b.text_input("Current company", key=f"qn_co_{job_id}")
            blocked = ui.dup_guard(email, phone, f"qn_{job_id}")
            if st.button("Create and start screening", key=f"qn_go_{job_id}", type="primary", disabled=blocked):
                if not name.strip():
                    st.error("Please enter the candidate's name.")
                else:
                    cid = d.insert("candidates", {"full_name": name.strip(), "phone": phone, "email": email,
                                                  "current_company": company})
                    app_id = d.add_application(job_id, cid)
                    ss[f"_pending_scr_app_{job_id}"] = app_id
                    for k in [k for k in ss.keys() if str(k).startswith(f"qn_") and str(k).endswith(f"_{job_id}")]:
                        del ss[k]
                    st.rerun()


def _question_widget(q, key, current):
    t = q["answer_type"]
    if t == "Yes/No":
        opts = ["Not answered", "Yes", "No"]
        idx = opts.index(current) if current in opts else 0
        v = st.radio(q["question"], opts, index=idx, key=key, horizontal=True)
        return None if v == "Not answered" else v
    if t == "Number":
        try:
            cur = float(current) if current not in (None, "") else None
        except ValueError:
            cur = None
        v = st.number_input(q["question"], value=cur, step=0.5, key=key)
        return None if v is None else f"{v:g}"
    if t == "Choice":
        items = ["— not answered —"] + list(q["choices"] or []) + ["Other…"]
        if current and current not in items:
            items.insert(1, current)
        v = st.selectbox(q["question"], items, index=items.index(current) if current in items else 0, key=key)
        if v == "— not answered —":
            return None
        if v == "Other…":
            return st.text_input("Type the answer", key=key + "__o") or None
        return v
    return st.text_area(q["question"], value=current or "", key=key, height=80) or None


def render():
    d = dbm.get_db()
    st.title("🎙️ Screening")
    flash = ss.pop("_flash", None)
    if flash:
        st.success(flash)
    job_id = ss.get("sel_job_id")
    job = d.get("jobs", job_id) if job_id else None
    if not job:
        st.info("Choose a job in the left sidebar first (or create one).")
        st.button("Go to Jobs", on_click=nav.go, args=("jobs",))
        return
    st.caption(f"Job: **{job['title']}**  ·  {job['location'] or 'location not set'}  ·  {job['status']}")

    pairs = d.job_pairs(job_id)
    _add_candidate_panel(job_id, bool(pairs))
    if not pairs:
        return

    app_ids = [a["id"] for a, _ in pairs]
    by_app = {a["id"]: (a, c) for a, c in pairs}
    pick_key = f"scr_app_{job_id}"
    pending = ss.pop(f"_pending_scr_app_{job_id}", None)
    if pending:
        ss[pick_key] = pending
    if ss.get(pick_key) not in app_ids:
        ss.pop(pick_key, None)
    app_id = st.selectbox(
        "Candidate being screened", app_ids, key=pick_key,
        format_func=lambda i: f"{ICON.get(by_app[i][0]['screening_status'], '⏳')} {by_app[i][1]['full_name']}")
    if app_id is None:
        return
    app, cand = by_app[app_id]
    cid = cand["id"]
    questions = d.questions(job_id)
    responses = d.responses(app_id)
    note = d.get_screening_note(app_id)
    suggestions = service.all_skill_suggestions()
    p = f"s{app_id}_"

    st.markdown(f"### {cand['full_name']}")
    st.caption(f"Screening: **{app['screening_status']}**  ·  Pipeline: **{app['status']}**  ·  "
               "Nothing is saved until you press a Save button.")
    top = st.container()
    t = st.tabs(["1 · Candidate", "2 · Skills", "3 · Pay & preferences", "4 · Availability",
                 f"5 · Job questions ({len(questions)})", "6 · Assessment & notes"])
    vals = ui.candidate_form(cand, p, containers={"basic": t[0], "skills": t[1], "comp": t[2], "prefs": t[2],
                                                  "avail": t[3]}, suggestions=suggestions)

    answers = {}
    with t[4]:
        if not questions:
            st.info("This job has no screening questions yet. Add them under Jobs → Screening questions.")
        for q in questions:
            answers[q["id"]] = _question_widget(q, f"{p}q{q['id']}", responses.get(q["id"]))

    with t[5]:
        a, b, c = st.columns(3)
        with a:
            comm = ui.choice("Communication", f"{p}comm", "communication", app["communication"])
        with b:
            imp = ui.choice("Overall impression", f"{p}imp", "impression", app["impression"])
        with c:
            reco = ui.choice("My recommendation", f"{p}reco", "recommendation", app["recommendation"],
                             help="Your own judgement. It is stored separately from the automatic score.")
        obs = st.text_area("Additional observations", value=app["observations"] or "", key=f"{p}obs", height=90)
        status_idx = APP_STATUSES.index(app["status"]) if app["status"] in APP_STATUSES else 0
        status_sel = st.selectbox("Pipeline status", APP_STATUSES, index=status_idx, key=f"{p}status")
        notes = st.text_area("📝 Recruiter notes (anything you want to remember: opinions, follow-ups, email summaries)",
                             value=(note or {}).get("body") or "", key=f"{p}notes", height=260)

    # --- live score from what is currently typed (not yet saved)
    live_cand = {**cand, **ui.clean_candidate_values(vals)}
    live = compute_score(job, live_cand, {"communication": comm})
    with top:
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        c1.metric("Match score (live)", f"{live['total']:.0f}/100")
        c2.metric("Confidence", live["confidence"])
        save_draft = c3.button("💾 Save draft", key=f"{p}save1", type="secondary")
        save_done = c4.button("✅ Save & mark completed", key=f"{p}done1", type="primary")
        for f in live["flags"][:2]:
            (st.error if f["level"] == "error" else st.warning)(f["text"])
        with st.popover("ℹ️ Why this score?"):
            ui.render_explanation(live, cand["full_name"])
    b1, b2 = st.columns(2)
    save_draft2 = b1.button("💾 Save draft", key=f"{p}save2")
    save_done2 = b2.button("✅ Save & mark completed", key=f"{p}done2", type="primary")

    if save_draft or save_draft2 or save_done or save_done2:
        complete = save_done or save_done2
        clean = ui.clean_candidate_values(vals)
        if not (clean.get("full_name") or "").strip():
            st.error("The candidate needs a name before saving.")
            return
        if clean.get("email") or clean.get("phone"):
            dups = d.find_duplicates(clean.get("email"), clean.get("phone"), exclude_id=cid)
            if dups:
                st.warning("Note: another profile has the same email/phone: "
                           + ", ".join(x["full_name"] for x in dups) + ". Saved anyway; check the Data & Backup page "
                           "to review possible duplicates.")
        d.update("candidates", cid, clean)
        err = ui.save_resume(cid, vals.get("_resume"))
        if err:
            st.warning(err)
        new_status = status_sel
        if status_sel == app["status"]:  # recruiter did not choose manually: move along automatically
            if complete and app["status"] in ("Added", "Screening pending"):
                new_status = "Screening completed"
            elif not complete and app["status"] == "Added":
                new_status = "Screening pending"
        app_vals = {"communication": comm, "impression": imp, "recommendation": reco, "observations": obs,
                    "status": new_status,
                    "screening_status": "Completed" if complete else
                    ("Completed" if app["screening_status"] == "Completed" else "Draft saved")}
        if (reco or None) != (app["recommendation"] or None):
            app_vals["score_at_decision"] = live["total"]  # keep the automatic score at the time you decided
        d.update("applications", app_id, app_vals)
        d.save_responses(app_id, answers)
        d.save_screening_note(app_id, cid, notes)
        ui.flush_custom_options()
        ss.pop(f"{p}status", None)  # re-read the (possibly auto-advanced) status from the database
        ss["_flash"] = f"Saved at {datetime.now().strftime('%H:%M:%S')}" + (" · marked as completed." if complete else " as a draft.")
        st.rerun()
