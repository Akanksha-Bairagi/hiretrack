import pandas as pd
import streamlit as st

from hiretrack import db as dbm
from hiretrack import exports, nav, service, ui
from hiretrack.options import JOB_STATUSES, QUESTION_TYPES
from hiretrack.pdf_utils import detect_skills, extract_pdf_text
from hiretrack.scoring import LABELS, skill_key

ss = st.session_state


def _flash():
    msg = ss.pop("_flash", None)
    if msg:
        st.success(msg)


# ------------------------------------------------------------------ details form
def details_form(job, prefix, suggestions):
    j = job or {}
    v = {}
    a, b = st.columns(2)
    v["title"] = a.text_input("Job title *", value=j.get("title") or "", key=f"{prefix}title")
    with b:
        v["department"] = ui.choice("Department", f"{prefix}dept", "department", j.get("department"))
    v["location"] = a.text_input("Job location", value=j.get("location") or "", key=f"{prefix}loc",
                                 help="City name. For several cities, separate them with commas.")
    with b:
        v["work_mode"] = ui.choice("Work mode", f"{prefix}wm", "work_mode", j.get("work_mode"))
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        v["exp_min"] = ui.num("Min experience (yrs)", f"{prefix}emin", j.get("exp_min"))
    with c2:
        v["exp_max"] = ui.num("Max experience (yrs)", f"{prefix}emax", j.get("exp_max"))
    with c3:
        v["budget_min"] = ui.num("Budget from (LPA)", f"{prefix}bmin", j.get("budget_min"))
    with c4:
        v["budget_max"] = ui.num("Budget up to (LPA)", f"{prefix}bmax", j.get("budget_max"))
    v["mandatory_skills"] = ui.skills_input("Mandatory skills", f"{prefix}mand", j.get("mandatory_skills"), suggestions,
                                            help="Candidates should have ALL of these. Missing ones are always flagged.")
    v["preferred_skills"] = ui.skills_input("Preferred skills (nice to have)", f"{prefix}pref",
                                            j.get("preferred_skills"), suggestions)
    v["strict_mandatory"] = st.checkbox("Rank candidates who have all mandatory skills above those who don't",
                                        value=bool(j.get("strict_mandatory", True)), key=f"{prefix}strict")
    return v


def validate(v):
    errs = []
    if not (v["title"] or "").strip():
        errs.append("Please enter a job title.")
    if v["exp_min"] is not None and v["exp_max"] is not None and v["exp_min"] > v["exp_max"]:
        errs.append("Minimum experience is higher than maximum experience.")
    if v["budget_min"] is not None and v["budget_max"] is not None and v["budget_min"] > v["budget_max"]:
        errs.append("Budget 'from' is higher than budget 'up to'.")
    both = {skill_key(s) for s in v["mandatory_skills"]} & {skill_key(s) for s in v["preferred_skills"]}
    if both:
        errs.append("A skill is listed as both mandatory and preferred. Keep it in one list only.")
    return errs


# ------------------------------------------------------------------ new job
def new_job_tab(suggestions):
    d = dbm.get_db()
    st.write("Fill in what you know now. You can change everything later.")
    v = details_form(None, "newjob_", suggestions)
    starter = st.checkbox("Add one screening question per mandatory skill (\"How many years of experience in …?\")",
                          value=True, key="newjob_starter")
    if st.button("Create job", type="primary", key="newjob_create"):
        errs = validate(v)
        if errs:
            for e in errs:
                st.error(e)
            return
        jid = d.insert("jobs", {**v, "status": "Active", "weights": service.default_weights()})
        if starter:
            service.starter_questions(jid, v["mandatory_skills"])
        ui.flush_custom_options()
        for k in [k for k in ss.keys() if str(k).startswith("newjob_")]:
            del ss[k]
        nav.select_job(jid)
        ss["_flash"] = "Job created. Next: upload the JD and review the screening questions below."
        st.rerun()


# ------------------------------------------------------------------ workspace tabs
def tab_details(job, suggestions):
    d = dbm.get_db()
    p = f"jobd_{job['id']}_"
    v = details_form(job, p, suggestions)
    cur = JOB_STATUSES.index(job["status"]) if job["status"] in JOB_STATUSES else 0
    v["status"] = st.selectbox("Status", JOB_STATUSES, index=cur, key=f"{p}status")
    if st.button("💾 Save job details", type="primary", key=f"{p}save"):
        errs = validate(v)
        if errs:
            for e in errs:
                st.error(e)
        else:
            d.update("jobs", job["id"], v)
            ui.flush_custom_options()
            ss["_flash"] = "Job details saved."
            st.rerun()


def _add_detected(jid, field, widget_suffix, skills, pick_key):
    d = dbm.get_db()
    job = d.get("jobs", jid)
    cur = list(job[field] or [])
    have = {skill_key(s) for s in cur}
    other = job["preferred_skills" if field == "mandatory_skills" else "mandatory_skills"] or []
    other_keys = {skill_key(s) for s in other}
    new = [s for s in skills if skill_key(s) not in have and skill_key(s) not in other_keys]
    if new:
        d.update("jobs", jid, {field: cur + new})
        ss[f"jobd_{jid}_{widget_suffix}"] = cur + new
    ss[pick_key] = []  # the picked skills leave the list, so clear the selection


def tab_jd(job, suggestions):
    d = dbm.get_db()
    jid = job["id"]
    nonce = ss.get(f"_jdn_{jid}", 0)
    meta = d.file_meta("jd", job_id=jid)
    st.write("Upload the job description PDF. The text is read automatically and can be edited.")
    up = st.file_uploader("Job description (PDF)", type=["pdf"], key=f"jdup_{jid}_{nonce}")
    if up is not None and st.button("📄 Read this PDF and attach it", key=f"jdread_{jid}"):
        data = up.getvalue()
        if len(data) > 10 * 1024 * 1024:
            st.error("That PDF is larger than 10 MB.")
        else:
            text, pages, warn = extract_pdf_text(data)
            d.save_file("jd", up.name, "application/pdf", data, job_id=jid)
            if text:
                d.update("jobs", jid, {"jd_text": text})
            ss[f"_jdn_{jid}"] = nonce + 1
            ss["_flash"] = (f"PDF attached ({pages} page{'s' if pages != 1 else ''}) and text extracted."
                            if text else f"PDF attached, but: {warn}")
            st.rerun()
    if meta:
        st.caption(f"Attached: **{meta['filename']}** ({meta['size_bytes'] // 1024} KB)")
        blob = d.file_data(meta["id"])
        if blob:
            st.download_button("⬇️ Download the original PDF", blob["data"], file_name=meta["filename"],
                               mime="application/pdf", key=f"jddl_{jid}")
    text = st.text_area("Job description text (you can type or edit it here)", value=job.get("jd_text") or "",
                        height=300, key=f"jdtext_{jid}_{nonce}")
    if st.button("💾 Save job description text", key=f"jdsave_{jid}"):
        d.update("jobs", jid, {"jd_text": text})
        ss["_flash"] = "Job description saved."
        st.rerun()

    found = detect_skills(text, extra_vocab=suggestions) if text else []
    already = {skill_key(s) for s in (job["mandatory_skills"] or []) + (job["preferred_skills"] or [])}
    new = [s for s in found if skill_key(s) not in already]
    if new:
        st.markdown("**Skills found in this description**")
        pick = st.multiselect("Tick the ones you want to add", new, key=f"detpick_{jid}_{nonce}")
        a, b = st.columns(2)
        a.button("Add as MANDATORY", key=f"addm_{jid}", disabled=not pick, on_click=_add_detected,
                 args=(jid, "mandatory_skills", "mand", pick, f"detpick_{jid}_{nonce}"))
        b.button("Add as PREFERRED", key=f"addp_{jid}", disabled=not pick, on_click=_add_detected,
                 args=(jid, "preferred_skills", "pref", pick, f"detpick_{jid}_{nonce}"))
        st.caption("This is simple keyword matching, so always double-check the lists on the Details tab.")


def tab_questions(job):
    d = dbm.get_db()
    jid = job["id"]
    st.write("These are the questions you ask on the call. Candidate details such as CTC, notice period and "
             "relocation are already in the screening form, so you do not need to add them here.")
    qs = d.questions(jid)
    for i, q in enumerate(qs):
        with st.container(border=True):
            k = f"q{q['id']}_"
            c1, c2 = st.columns([4, 1])
            text = c1.text_input("Question", value=q["question"], key=k + "t", label_visibility="collapsed")
            t_idx = QUESTION_TYPES.index(q["answer_type"]) if q["answer_type"] in QUESTION_TYPES else 0
            atype = c2.selectbox("Answer type", QUESTION_TYPES, index=t_idx, key=k + "a", label_visibility="collapsed")
            choices = None
            if atype == "Choice":
                raw = st.text_input("Choices (separate with commas)", value=", ".join(q["choices"] or []), key=k + "c")
                choices = [x.strip() for x in raw.split(",") if x.strip()]
            b = st.columns([1, 1, 1, 1, 4])
            if b[0].button("💾", key=k + "s", help="Save this question"):
                if not text.strip():
                    st.error("A question cannot be empty.")
                else:
                    d.update("screening_questions", q["id"], {"question": text, "answer_type": atype,
                                                              "choices": choices or []})
                    ss["_flash"] = "Question saved."
                    st.rerun()
            if b[1].button("⬆️", key=k + "u", disabled=i == 0, help="Move up"):
                d.move_question(jid, q["id"], -1)
                st.rerun()
            if b[2].button("⬇️", key=k + "d", disabled=i == len(qs) - 1, help="Move down"):
                d.move_question(jid, q["id"], +1)
                st.rerun()
            if b[3].button("🗑️", key=k + "x", help="Delete"):
                ss[f"delq_{q['id']}"] = True
            if ss.get(f"delq_{q['id']}"):
                n = d.count("screening_responses", "question_id = ?", (q["id"],))
                st.warning(f"Delete this question? {n} answer(s) already recorded for it will be deleted too.")
                y, n_ = st.columns(2)
                if y.button("Yes, delete it", key=k + "y"):
                    d.delete("screening_questions", q["id"])
                    ss.pop(f"delq_{q['id']}", None)
                    st.rerun()
                if n_.button("Keep it", key=k + "n"):
                    ss.pop(f"delq_{q['id']}", None)
                    st.rerun()
    if not qs:
        st.info("No questions yet.")

    st.markdown("**Add a question**")
    nonce = ss.get(f"_qn_{jid}", 0)
    a, b = st.columns([4, 1])
    new_text = a.text_input("New question", key=f"newq_{jid}_{nonce}", placeholder="e.g. Have you worked with FastAPI or Flask?")
    new_type = b.selectbox("Answer type", QUESTION_TYPES, key=f"newqt_{jid}_{nonce}")
    new_choices = ""
    if new_type == "Choice":
        new_choices = st.text_input("Choices (separate with commas)", key=f"newqc_{jid}_{nonce}")
    c1, c2 = st.columns(2)
    if c1.button("➕ Add question", key=f"addq_{jid}"):
        if new_text.strip():
            d.add_question(jid, new_text.strip(), new_type, [x.strip() for x in new_choices.split(",") if x.strip()])
            ss[f"_qn_{jid}"] = nonce + 1
            st.rerun()
        else:
            st.error("Type the question first.")
    if job["mandatory_skills"] and c2.button("⚡ Add a question for each mandatory skill", key=f"addstart_{jid}"):
        n = service.starter_questions(jid, job["mandatory_skills"])
        ss["_flash"] = f"Added {n} question(s)." if n else "Those questions already exist."
        st.rerun()


def tab_weights(job):
    d = dbm.get_db()
    jid = job["id"]
    st.write("How much each factor counts towards the 0-100 score. The numbers are shares, so they do not have "
             "to add up to 100: HireTrack scales them for you.")
    cur = service.default_weights() if not job["weights"] else {**service.default_weights(), **job["weights"]}
    vals = {}
    cols = st.columns(5)
    for col, (k, label) in zip(cols, LABELS.items()):
        with col:
            vals[k] = st.number_input(label, min_value=0, max_value=100, value=int(round(cur.get(k, 0))), step=5,
                                      key=f"w{jid}_{k}")
    total = sum(vals.values())
    st.caption(f"Total: {total}" + ("" if total == 100 else " (will be scaled to 100)"))
    if total <= 0:
        st.error("At least one weight must be above zero.")
    a, b = st.columns(2)
    if a.button("💾 Save weights", key=f"wsave_{jid}", disabled=total <= 0):
        d.update("jobs", jid, {"weights": vals})
        ss["_flash"] = "Scoring weights saved. Rankings are recalculated automatically."
        st.rerun()
    if b.button("Reset to my default weights", key=f"wreset_{jid}"):
        d.update("jobs", jid, {"weights": service.default_weights()})
        for k in LABELS:
            ss.pop(f"w{jid}_{k}", None)
        st.rerun()
    st.info("Skills are always the main factor. Missing mandatory skills are flagged separately, "
            "no matter what the total score is.")


def delete_job_flow(job):
    d = dbm.get_db()
    jid = job["id"]
    if not ss.get(f"deljob_{jid}"):
        st.button("🗑️ Delete this job permanently…", key=f"deljob_btn_{jid}",
                  on_click=lambda: ss.__setitem__(f"deljob_{jid}", True))
        return
    imp = d.job_impact(jid)
    st.error(
        f"**Permanent delete of “{job['title']}”.** This will also delete {imp['applications']} application(s), "
        f"{imp['responses']} recorded screening answer(s), {imp['notes']} call note(s) and {imp['questions']} "
        "screening question(s). The candidates' own profiles are **not** deleted, but this job's assessments for "
        "them are lost. This cannot be undone.")
    st.write("💡 **Archiving** hides the job but keeps everything, and you can restore it anytime.")
    typed = st.text_input("Type DELETE to confirm", key=f"deltype_{jid}")
    a, b = st.columns(2)
    if a.button("Delete permanently", key=f"delgo_{jid}", disabled=typed.strip() != "DELETE"):
        d.delete("jobs", jid)
        ss.pop(f"deljob_{jid}", None)
        ss["_flash"] = "Job deleted."
        st.rerun()
    if b.button("Cancel", key=f"delcancel_{jid}"):
        ss.pop(f"deljob_{jid}", None)
        st.rerun()


def tab_manage(job):
    d = dbm.get_db()
    jid = job["id"]
    st.markdown("**Status**")
    a, b = st.columns([2, 1])
    new_status = a.selectbox("Change status to", JOB_STATUSES, index=JOB_STATUSES.index(job["status"])
                             if job["status"] in JOB_STATUSES else 0, key=f"mstatus_{jid}")
    if b.button("Apply", key=f"mapply_{jid}") and new_status != job["status"]:
        d.update("jobs", jid, {"status": new_status})
        ss["_flash"] = f"Status changed to {new_status}."
        st.rerun()
    st.caption("Closed and On hold jobs stay visible. Archived jobs move to the 'Archived jobs' list.")
    st.markdown("**Copy this job**")
    if st.button("📑 Duplicate (same skills and questions, no candidates)", key=f"dup_{jid}"):
        new_id = d.clone_job(jid)
        nav.select_job(new_id)
        ss["_flash"] = "Job duplicated."
        st.rerun()
    st.markdown("**Download**")
    x1, x2 = st.columns(2)
    x1.download_button("⬇️ Job + candidates (Excel)", exports.job_xlsx(jid),
                       file_name=f"job_{exports.safe_name(job['title'])}.xlsx", key=f"jx_{jid}",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    x2.download_button("⬇️ Comparison (CSV)", exports.job_csv(jid), file_name=f"job_{exports.safe_name(job['title'])}.csv",
                       mime="text/csv", key=f"jc_{jid}")
    st.markdown("**Danger zone**")
    delete_job_flow(job)


# ------------------------------------------------------------------ page
def render():
    d = dbm.get_db()
    st.title("💼 Jobs")
    _flash()
    suggestions = service.all_skill_suggestions()
    t_list, t_new = st.tabs(["My jobs", "➕ New job"])
    with t_new:
        new_job_tab(suggestions)
    with t_list:
        jobs = d.rows("jobs", order="created_at DESC")
        visible = [j for j in jobs if j["status"] != "Archived"]
        stats = d.job_stats()
        if not jobs:
            st.info("No jobs yet. Open the “New job” tab to create your first one.")
        if visible:
            st.dataframe(pd.DataFrame([{
                "Job": j["title"], "Status": j["status"], "Location": j["location"], "Work mode": j["work_mode"],
                "Mandatory skills": service.join_list(j["mandatory_skills"]),
                "Candidates": stats.get(j["id"], {}).get("n_apps", 0),
            } for j in visible]), hide_index=True)
            st.caption("The job you are working on is chosen in the left sidebar.")

        archived = [j for j in jobs if j["status"] == "Archived"]
        if archived:
            with st.expander(f"🗄️ Archived jobs ({len(archived)})"):
                for j in archived:
                    a, b = st.columns([4, 1])
                    a.write(f"**{j['title']}** · {j['location'] or 'no location'}")
                    if b.button("Restore", key=f"restore_{j['id']}"):
                        d.update("jobs", j["id"], {"status": "Active"})
                        nav.select_job(j["id"])
                        st.rerun()

        job_id = ss.get("sel_job_id")
        job = d.get("jobs", job_id) if job_id else None
        if job:
            st.divider()
            h1, h2, h3 = st.columns([3, 1, 1])
            h1.subheader(f"{job['title']}  ·  {job['status']}")
            h2.button("🎙️ Screen candidates", key="jobs_to_screen", on_click=nav.go, args=("screening",))
            h3.button("📊 Compare", key="jobs_to_compare", on_click=nav.go, args=("compare",))
            n = d.job_impact(job["id"])["applications"]
            st.caption(f"{n} candidate(s) linked to this job.")
            tabs = st.tabs(["Details", "Job description", "Screening questions", "Scoring weights", "Manage"])
            with tabs[0]:
                tab_details(job, suggestions)
            with tabs[1]:
                tab_jd(job, suggestions)
            with tabs[2]:
                tab_questions(job)
            with tabs[3]:
                tab_weights(job)
            with tabs[4]:
                tab_manage(job)
