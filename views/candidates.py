import pandas as pd
import streamlit as st

from hiretrack import db as dbm
from hiretrack import exports, nav, service, ui
from hiretrack.options import APP_STATUSES

ss = st.session_state


def _flash():
    msg = ss.pop("_flash", None)
    if msg:
        st.success(msg)


def add_tab(suggestions):
    d = dbm.get_db()
    nonce = ss.get("_newc_n", 0)
    p = f"newc{nonce}_"
    st.write("Only the name is required. Save what you know and complete the rest later.")
    vals = ui.candidate_form(None, p, suggestions=suggestions)
    blocked = ui.dup_guard(vals["email"], vals["phone"], p)
    if st.button("Save candidate", type="primary", key=p + "save", disabled=blocked):
        clean = ui.clean_candidate_values(vals)
        if not (clean["full_name"] or "").strip():
            st.error("Please enter the candidate's name.")
            return
        cid = d.insert("candidates", clean)
        err = ui.save_resume(cid, vals.get("_resume"))
        ui.flush_custom_options()
        ss["_newc_n"] = nonce + 1
        ss["_flash"] = f"Saved {clean['full_name']}." + (f" {err}" if err else "")
        ss["cand_sel"] = cid
        st.rerun()


def _delete_flow(c):
    d = dbm.get_db()
    cid = c["id"]
    if not ss.get(f"delc_{cid}"):
        st.button("🗑️ Delete this candidate permanently…", key=f"delc_btn_{cid}",
                  on_click=lambda: ss.__setitem__(f"delc_{cid}", True))
        return
    imp = d.candidate_impact(cid)
    st.error(f"**Permanent delete of {c['full_name']}.** This also deletes {imp['applications']} job application(s), "
             f"{imp['responses']} screening answer(s), {imp['notes']} note(s) and {imp['files']} attached file(s). "
             "This cannot be undone.")
    st.write("💡 **Archive** instead to hide the person but keep everything.")
    typed = st.text_input("Type DELETE to confirm", key=f"delctype_{cid}")
    a, b = st.columns(2)
    if a.button("Delete permanently", key=f"delcgo_{cid}", disabled=typed.strip() != "DELETE"):
        d.delete("candidates", cid)
        ss.pop(f"delc_{cid}", None)
        ss.pop("cand_sel", None)
        ss["_flash"] = "Candidate deleted."
        st.rerun()
    if b.button("Cancel", key=f"delccancel_{cid}"):
        ss.pop(f"delc_{cid}", None)
        st.rerun()


def _profile_tab(c, suggestions):
    d = dbm.get_db()
    p = f"c{c['id']}_"
    vals = ui.candidate_form(c, p, suggestions=suggestions)
    a, b = st.columns([1, 1])
    if a.button("💾 Save changes", type="primary", key=p + "save"):
        clean = ui.clean_candidate_values(vals)
        if not (clean["full_name"] or "").strip():
            st.error("The name cannot be empty.")
        else:
            dups = d.find_duplicates(clean.get("email"), clean.get("phone"), exclude_id=c["id"])
            d.update("candidates", c["id"], clean)
            err = ui.save_resume(c["id"], vals.get("_resume"))
            ui.flush_custom_options()
            ss["_flash"] = "Saved." + (" Note: another profile shares this email/phone: "
                                       + ", ".join(x["full_name"] for x in dups) if dups else "") + (f" {err}" if err else "")
            st.rerun()
    label = "🗄️ Restore from archive" if c["archived"] else "🗄️ Archive (hide, keep data)"
    if b.button(label, key=p + "arch"):
        d.update("candidates", c["id"], {"archived": not c["archived"]})
        ss["_flash"] = "Candidate restored." if c["archived"] else "Candidate archived."
        st.rerun()
    meta = d.file_meta("resume", candidate_id=c["id"])
    if meta:
        blob = d.file_data(meta["id"])
        if blob:
            st.download_button("⬇️ Download resume", blob["data"], file_name=meta["filename"], key=p + "dlcv")
    st.divider()
    _delete_flow(c)


def _jobs_tab(c):
    d = dbm.get_db()
    pairs = d.candidate_apps(c["id"])
    if not pairs:
        st.info("This candidate is not linked to any job yet.")
    for a, j in pairs:
        with st.container(border=True):
            h1, h2 = st.columns([3, 1])
            h1.markdown(f"**{j['title']}** · {j['location'] or ''}")
            res = service.compute_score(j, c, a)
            h2.metric("Auto score", f"{res['total']:.0f}")
            st.caption(f"Screening: {a['screening_status']} · Recommendation: {a['recommendation'] or '—'}")
            for f in res["flags"][:1]:
                (st.error if f["level"] == "error" else st.warning)(f["text"])
            k = f"ap{a['id']}_"
            s_idx = APP_STATUSES.index(a["status"]) if a["status"] in APP_STATUSES else 0
            x1, x2, x3 = st.columns([2, 1, 1])
            new_status = x1.selectbox("Status", APP_STATUSES, index=s_idx, key=k + "st")
            if x2.button("Update status", key=k + "upd") and new_status != a["status"]:
                d.update("applications", a["id"], {"status": new_status})
                st.rerun()
            x3.button("🎙️ Screen", key=k + "scr", on_click=nav.go, args=("screening",), kwargs={"job": j["id"], "scr_app_" + str(j["id"]): a["id"]})
            y1, y2 = st.columns(2)
            if y1.button("Archive this application", key=k + "arc"):
                d.update("applications", a["id"], {"archived": True})
                st.rerun()
            if y2.button("Remove from this job…", key=k + "rm"):
                ss[k + "confirm"] = True
            if ss.get(k + "confirm"):
                st.warning(f"Remove {c['full_name']} from “{j['title']}”? Their screening answers and notes for this "
                           "job will be deleted. The candidate profile stays.")
                z1, z2 = st.columns(2)
                if z1.button("Yes, remove", key=k + "yes"):
                    d.delete("applications", a["id"])
                    ss.pop(k + "confirm", None)
                    st.rerun()
                if z2.button("Cancel", key=k + "no"):
                    ss.pop(k + "confirm", None)
                    st.rerun()
    linked = {a["job_id"] for a, _ in pairs}
    free = [j for j in d.rows("jobs", "status != 'Archived'", order="title") if j["id"] not in linked]
    if free:
        lookup = {j["id"]: j for j in free}
        jid = st.selectbox("Consider this candidate for another job", [j["id"] for j in free], index=None,
                           format_func=lambda i: lookup[i]["title"], key=f"addjob_{c['id']}", placeholder="Pick a job…")
        if jid and st.button("Add to this job", key=f"addjobgo_{c['id']}"):
            d.add_application(jid, c["id"])
            ss["_flash"] = "Added to the job. Their profile details are reused, so nothing needs re-typing."
            st.rerun()


def _notes_tab(c):
    d = dbm.get_db()
    cid = c["id"]
    notes = d.rows("notes", "candidate_id = ?", (cid,), order="created_at DESC")
    jobs = {j["id"]: j["title"] for j in d.rows("jobs")}
    apps = {a["id"]: a for a in d.rows("applications", "candidate_id = ?", (cid,))}
    for n in notes:
        job = jobs.get(apps[n["application_id"]]["job_id"]) if n["application_id"] in apps else None
        with st.container(border=True):
            st.caption(("Screening note · " + job if n["kind"] == "screening" and job else "General note") +
                       f" · updated {ui.fmt_date(n['updated_at'])}")
            txt = st.text_area("Note", value=n["body"] or "", key=f"note{n['id']}", height=140, label_visibility="collapsed")
            a, b = st.columns(2)
            if a.button("💾 Save", key=f"notesave{n['id']}"):
                if txt.strip():
                    d.update("notes", n["id"], {"body": txt})
                else:
                    d.delete("notes", n["id"])
                st.rerun()
            if b.button("🗑️ Delete note", key=f"notedel{n['id']}"):
                d.delete("notes", n["id"])
                st.rerun()
    nonce = ss.get(f"_nn_{cid}", 0)
    new = st.text_area("Add a note", key=f"newnote_{cid}_{nonce}", height=120,
                       placeholder="Opinions, follow-ups, email summaries, anything…")
    if st.button("➕ Add note", key=f"addnote_{cid}") and new.strip():
        d.insert("notes", {"candidate_id": cid, "kind": "general", "body": new})
        ss[f"_nn_{cid}"] = nonce + 1
        st.rerun()


def render():
    d = dbm.get_db()
    st.title("👥 Candidates")
    _flash()
    suggestions = service.all_skill_suggestions()
    pending = ss.pop("_pending_cand", None)
    if pending:
        ss["cand_sel"] = pending

    t_all, t_new = st.tabs(["All candidates", "➕ Add candidate"])
    with t_new:
        add_tab(suggestions)
    with t_all:
        a, b, c_ = st.columns([2, 2, 1])
        q = a.text_input("Search name, email, phone, company or skill", key="cand_q")
        show_arch = c_.checkbox("Show archived", key="cand_arch")
        cands = d.rows("candidates", order="full_name") if show_arch else d.rows("candidates", "archived = ?", (False,), order="full_name")
        counts = {}
        for ap in d.rows("applications"):
            counts[ap["candidate_id"]] = counts.get(ap["candidate_id"], 0) + 1
        if q:
            ql = q.lower().strip()
            def hit(c):
                blob = " ".join(str(x) for x in (c["full_name"], c["email"], c["phone"], c["current_company"],
                                                 service.join_list(c["primary_skills"]), service.join_list(c["secondary_skills"]),
                                                 service.join_list(c["additional_skills"]), c["current_city"]) if x)
                return ql in blob.lower()
            cands = [c for c in cands if hit(c)]
        if not cands:
            st.info("No candidates found." if (q or show_arch) else "No candidates yet. Use the “Add candidate” tab, "
                    "or add one from the Screening page.")
        else:
            df = pd.DataFrame([{
                "Name": c["full_name"], "Company": c["current_company"], "Designation": c["current_designation"],
                "Exp (yrs)": c["total_exp"], "Skills": service.join_list(c["primary_skills"]), "City": c["current_city"],
                "Notice": c["notice_period"], "Expected CTC": c["expected_ctc"], "Jobs": counts.get(c["id"], 0),
                "Archived": "yes" if c["archived"] else "",
            } for c in cands])
            lookup = {c["id"]: c for c in cands}
            chosen = ui.table_picker(df, [c["id"] for c in cands], "cand", lambda i: lookup[i]["full_name"],
                                     select_label="Open candidate (click a row or pick here)")
            st.caption(f"{len(cands)} candidate(s).")
            if chosen:
                c = d.get("candidates", chosen)
                if c:
                    st.divider()
                    st.subheader(c["full_name"] + ("  (archived)" if c["archived"] else ""))
                    tp, tj, tn, tx = st.tabs(["Profile", "Jobs & screening", "Notes", "Download"])
                    with tp:
                        _profile_tab(c, suggestions)
                    with tj:
                        _jobs_tab(c)
                    with tn:
                        _notes_tab(c)
                    with tx:
                        n = exports.safe_name(c["full_name"])
                        x1, x2 = st.columns(2)
                        x1.download_button("⬇️ Complete profile (Excel)", exports.candidate_xlsx(c["id"]),
                                           file_name=f"candidate_{n}.xlsx", key=f"cx_{c['id']}",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        x2.download_button("⬇️ Complete profile (JSON)", exports.candidate_json(c["id"]),
                                           file_name=f"candidate_{n}.json", key=f"cj_{c['id']}", mime="application/json")
                        st.caption("Includes profile, screening answers, notes and the ranking explanation for every job.")
        st.divider()
        st.download_button("⬇️ All candidates (Excel)", exports.to_xlsx({"Candidates": service.candidate_frame(d.rows("candidates"))}),
                           file_name="all_candidates.xlsx", key="all_c_xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
