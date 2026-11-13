import streamlit as st

from hiretrack import db as dbm
from hiretrack import exports, nav, service, ui
from hiretrack.options import APP_STATUSES, SCREENING_STATUSES

ss = st.session_state

SORTS = {
    "Rank (best first)": ("Rank", True),
    "Ranking score (high to low)": ("Score", False),
    "Experience (high to low)": ("Total exp (yrs)", False),
    "Notice period (shortest first)": ("Notice (days)", True),
    "Expected CTC (lowest first)": ("Expected CTC (LPA)", True),
    "Technical skill match (high to low)": ("Skill match %", False),
}


def _flash():
    msg = ss.pop("_flash", None)
    if msg:
        st.success(msg)


def _filters(df):
    """Filter widgets. Returns a boolean mask."""
    mask = df["Rank"].notna()
    with st.expander("🔎 Search & filter", expanded=False):
        a, b, c = st.columns(3)
        q = a.text_input("Name contains", key="cmp_q")
        skills_all = sorted({s.strip() for v in df["Missing mandatory skills"] for s in str(v).split(",") if s.strip()},
                            key=str.lower)
        skill_missing = b.multiselect("Is missing skill", skills_all, key="cmp_skill")
        cities = sorted({x for x in df["Current city"].dropna()})
        city = c.multiselect("Current city", cities, key="cmp_city")
        a, b, c = st.columns(3)
        reloc = a.multiselect("Relocation", sorted({x for x in df["Relocation"].dropna()}), key="cmp_reloc")
        max_notice = b.number_input("Max notice (days)", min_value=0, value=None, step=15, key="cmp_notice")
        reco = c.multiselect("Recommendation", sorted({x for x in df["Recruiter recommendation"].dropna()}), key="cmp_reco")
        a, b, c = st.columns(3)
        scr = a.multiselect("Screening status", SCREENING_STATUSES, key="cmp_scr")
        ctc_hi = b.number_input("Expected CTC up to (LPA)", min_value=0.0, value=None, step=1.0, key="cmp_ctc")
        min_score = c.number_input("Minimum score", min_value=0, max_value=100, value=None, step=5, key="cmp_min")
        only_complete = st.checkbox("Only candidates with no missing mandatory skills", key="cmp_nogap")
    if q:
        mask &= df["Candidate"].fillna("").str.contains(q, case=False, regex=False)
    for s in skill_missing:
        mask &= df["Missing mandatory skills"].fillna("").str.contains(s, case=False, regex=False)
    if city:
        mask &= df["Current city"].isin(city)
    if reloc:
        mask &= df["Relocation"].isin(reloc)
    if max_notice is not None:
        mask &= df["Notice (days)"].notna() & (df["Notice (days)"] <= max_notice)
    if reco:
        mask &= df["Recruiter recommendation"].isin(reco)
    if scr:
        mask &= df["Screening status"].isin(scr)
    if ctc_hi is not None:
        mask &= df["Expected CTC (LPA)"].notna() & (df["Expected CTC (LPA)"] <= ctc_hi)
    if min_score is not None:
        mask &= df["Score"] >= min_score
    if only_complete:
        mask &= df["Missing mandatory skills"].fillna("") == ""
    return mask


def _detail(job, row, d):
    app, cand, res = row["app"], row["cand"], row["score"]
    st.divider()
    h1, h2, h3 = st.columns([3, 1, 1])
    h1.subheader(f"#{row['rank']} {cand['full_name']}")
    h2.button("🎙️ Open screening form", key=f"cmp_scr_{app['id']}", on_click=nav.go, args=("screening",),
              help="Opens this job's screening page; pick the candidate there.")
    h3.button("👤 Open profile", key=f"cmp_prof_{app['id']}", on_click=nav.go, args=("candidates",))

    ui_cols = st.columns([3, 2])
    with ui_cols[0]:
        with st.expander("ℹ️ Why this score?", expanded=True):
            ui.render_explanation(res, cand["full_name"])
    with ui_cols[1]:
        st.markdown("**Your decision**")
        if app["score_at_decision"] is not None and app["recommendation"]:
            st.caption(f"Automatic score when you set your recommendation: {app['score_at_decision']:.0f}/100. "
                       f"Now: {res['total']:.0f}/100.")
        k = f"cmpdec_{app['id']}_"
        reco = ui.choice("Recommendation", k + "reco", "recommendation", app["recommendation"])
        sidx = APP_STATUSES.index(app["status"]) if app["status"] in APP_STATUSES else 0
        status = st.selectbox("Pipeline status", APP_STATUSES, index=sidx, key=k + "status")
        if st.button("💾 Save decision", key=k + "save", type="primary"):
            vals = {"recommendation": reco, "status": status}
            if (reco or None) != (app["recommendation"] or None):
                vals["score_at_decision"] = res["total"]
            d.update("applications", app["id"], vals)
            ui.flush_custom_options()
            ss["_flash"] = "Decision saved."
            st.rerun()
        st.markdown("**Candidate snapshot**")
        snap = [("Company", cand["current_company"]), ("Designation", cand["current_designation"]),
                ("Experience", f"{cand['total_exp']:g} yrs total" if cand["total_exp"] is not None else None),
                ("Current → expected CTC", f"{cand['current_ctc']:g} → {cand['expected_ctc']:g} LPA"
                 if cand["current_ctc"] is not None and cand["expected_ctc"] is not None else None),
                ("Notice", cand["notice_period"]), ("City", cand["current_city"]), ("Relocation", cand["relocation"]),
                ("Communication", app["communication"]), ("Impression", app["impression"])]
        for k_, v_ in snap:
            if v_:
                st.write(f"**{k_}:** {v_}")
        if app["observations"]:
            st.write(f"**Observations:** {app['observations']}")
    qs = d.questions(job["id"])
    resp = d.responses(app["id"])
    if qs:
        st.markdown("**Screening answers**")
        for q in qs:
            st.write(f"• {q['question']}  →  **{resp.get(q['id']) or '—'}**")
    note = d.get_screening_note(app["id"])
    if note and note["body"]:
        st.markdown("**Recruiter notes**")
        st.write(note["body"])


def render():
    d = dbm.get_db()
    st.title("📊 Compare candidates")
    _flash()
    job_id = ss.get("sel_job_id")
    if not job_id:
        st.info("Choose a job in the left sidebar first.")
        return
    job, rows = service.build_comparison(job_id, include_archived=False)
    if not job:
        st.info("That job no longer exists.")
        return
    st.caption(f"Job: **{job['title']}** · {job['location'] or 'location not set'} · "
               f"mandatory: {service.join_list(job['mandatory_skills']) or 'none set'}")
    if not rows:
        st.info("No candidates on this job yet. Add some on the Screening page.")
        st.button("Go to Screening", on_click=nav.go, args=("screening",))
        return

    df = service.comparison_frame(rows)
    mask = _filters(df)
    sort_label = st.selectbox("Sort by", list(SORTS), key="cmp_sort")
    col, asc = SORTS[sort_label]
    shown = df[mask].sort_values(col, ascending=asc, na_position="last", kind="stable")
    st.caption(f"Showing {len(shown)} of {len(df)} candidates. Click any column heading to sort. "
               "Candidates missing a mandatory skill are marked ⚠️.")

    view = shown.copy()
    view.insert(1, "⚠️", view["Missing mandatory skills"].map(lambda s: "⚠️" if s else ""))
    cols = ["Rank", "⚠️", "Candidate", "Total exp (yrs)", "Skill match", "Missing mandatory skills",
            "Current CTC (LPA)", "Expected CTC (LPA)", "Current city", "Relocation", "Notice period",
            "Communication", "Score", "Confidence", "Recruiter recommendation", "Screening status"]
    cfg = {"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
           "Rank": st.column_config.NumberColumn("Rank", format="%d")}
    ids = [int(x) for x in shown["_app_id"]]
    by_app = {r["app"]["id"]: r for r in rows}
    chosen = ui.table_picker(view[cols], ids, "cmp", lambda i: f"#{by_app[i]['rank']} {by_app[i]['cand']['full_name']}",
                             select_label="Open candidate (click a row or pick here)", column_config=cfg)

    st.markdown("**Download**")
    a, b, c = st.columns(3)
    a.download_button("⬇️ This job's comparison (Excel)", exports.job_xlsx(job_id),
                      file_name=f"comparison_{exports.safe_name(job['title'])}.xlsx", key="cmp_xlsx",
                      mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    b.download_button("⬇️ Comparison as shown (CSV)", exports.to_csv(shown), key="cmp_csv", mime="text/csv",
                      file_name=f"comparison_{exports.safe_name(job['title'])}.csv")
    c.caption("The Excel file also contains screening answers and the full ranking explanations.")

    if chosen:
        _detail(job, by_app[chosen], d)
