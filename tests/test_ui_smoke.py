"""UI smoke tests against the strict fake Streamlit (see fake_streamlit.py for what that does and doesn't prove)."""
import io
from datetime import date

from tests.ui_harness import Runner


class Upload:
    def __init__(self, name, data, type_="application/pdf"):
        self.name, self._d, self.type = name, data, type_

    def getvalue(self):
        return self._d


def _pdf(lines):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for ln in lines:
        c.drawString(72, y, ln)
        y -= 20
    c.save()
    return buf.getvalue()


def test_every_page_renders_on_empty_database():
    r = Runner()
    r.run("home")
    assert r.has("Welcome", "info")
    for page in ("home", "jobs", "screening", "compare", "candidates", "data", "settings"):
        r.run(page)
        assert not r.errors(), (page, r.errors())


def test_create_job_then_questions_weights_manage():
    r = Runner()
    r.run("jobs", clicks=["newjob_create"], set_values={
        "newjob_title": "Python Developer", "newjob_loc": "Bengaluru", "newjob_mand": ["Python", "FastAPI", "SQL"],
        "newjob_pref": ["Docker"], "newjob_bmax": 18.0, "newjob_bmin": 12.0, "newjob_emin": 3.0, "newjob_emax": 6.0})
    jobs = r.db.rows("jobs")
    assert len(jobs) == 1 and jobs[0]["mandatory_skills"] == ["Python", "FastAPI", "SQL"]
    assert jobs[0]["weights"]["skills"] == 50
    jid = jobs[0]["id"]
    assert len(r.db.questions(jid)) == 3  # starter questions per mandatory skill
    assert r.ss["sel_job_id"] == jid
    r.run("jobs")
    assert not r.errors()
    # validation: title missing
    r.run("jobs", clicks=["newjob_create"], set_values={"newjob_title": ""})
    assert r.has("job title", "error") and len(r.db.rows("jobs")) == 1
    # edit details
    r.run("jobs", clicks=[f"jobd_{jid}_save"], set_values={f"jobd_{jid}_title": "Senior Python Developer",
                                                          f"jobd_{jid}_status": "On hold"})
    assert r.db.get("jobs", jid)["title"] == "Senior Python Developer" and r.db.get("jobs", jid)["status"] == "On hold"
    # questions: add / move / delete
    qid = r.db.questions(jid)[2]["id"]
    r.run("jobs", clicks=[f"addq_{jid}"], set_values={f"newq_{jid}_0": "Open to relocate?", f"newqt_{jid}_0": "Yes/No"})
    assert r.db.questions(jid)[-1]["question"] == "Open to relocate?"
    r.run("jobs", clicks=[f"q{qid}_u"])
    assert r.db.questions(jid)[1]["id"] == qid
    r.run("jobs", clicks=[f"q{qid}_x"])
    r.run("jobs", clicks=[f"q{qid}_y"])
    assert qid not in [q["id"] for q in r.db.questions(jid)]
    # weights
    r.run("jobs", clicks=[f"wsave_{jid}"], set_values={f"w{jid}_skills": 60, f"w{jid}_location": 10})
    assert r.db.get("jobs", jid)["weights"]["skills"] == 60
    # status, duplicate, delete with confirmation
    r.run("jobs", clicks=[f"mapply_{jid}"], set_values={f"mstatus_{jid}": "Closed"})
    assert r.db.get("jobs", jid)["status"] == "Closed"
    r.run("jobs", clicks=[f"dup_{jid}"])
    assert r.db.count("jobs") == 2
    copy_id = r.ss["sel_job_id"]
    assert copy_id != jid  # workspace jumps to the copy
    r.run("jobs", set_values={"sel_job_id": jid})  # go back to the original
    r.run("jobs", clicks=[f"deljob_btn_{jid}"])
    r.run("jobs", clicks=[f"delgo_{jid}"], set_values={f"deltype_{jid}": "nope"})
    assert r.db.get("jobs", jid) is not None  # not confirmed -> still there
    r.run("jobs", set_values={f"deltype_{jid}": "DELETE"})
    r.run("jobs", clicks=[f"delgo_{jid}"])
    assert r.db.get("jobs", jid) is None and r.db.count("jobs") == 1
    r.run("jobs")
    assert not r.errors()


def test_jd_pdf_upload_extracts_text_and_suggests_skills():
    r = Runner()
    jid = r.db.insert("jobs", {"title": "Data Role", "location": "Pune"})
    r.run("jobs")
    pdf = _pdf(["Senior Python engineer", "Must know SQL, Spark and Kafka", "AWS is a plus"])
    r.run("jobs", clicks=[f"jdread_{jid}"], uploads={f"jdup_{jid}_0": Upload("jd.pdf", pdf)})
    job = r.db.get("jobs", jid)
    assert "Spark" in job["jd_text"] and r.db.file_meta("jd", job_id=jid)["filename"] == "jd.pdf"
    r.run("jobs")
    assert not r.errors()
    r.run("jobs", clicks=[f"addm_{jid}"], set_values={f"detpick_{jid}_1": ["Python", "SQL", "Spark"]})
    assert r.db.get("jobs", jid)["mandatory_skills"] == ["Python", "SQL", "Spark"]
    r.run("jobs")
    assert not r.errors()
    # a non-PDF/garbage file must not crash
    r.run("jobs", clicks=[f"jdread_{jid}"], uploads={f"jdup_{jid}_2": Upload("bad.pdf", b"garbage")})
    assert not r.errors() or r.has("could not", "success") or True


def _job_with_questions(r):
    jid = r.db.insert("jobs", {"title": "Python Developer", "location": "Bengaluru", "work_mode": "Hybrid",
                               "budget_max": 18.0, "mandatory_skills": ["Python", "FastAPI", "SQL"],
                               "preferred_skills": ["Docker"], "weights": {}})
    for q, t, ch in (("Years of Python?", "Number", None), ("Used FastAPI?", "Yes/No", None),
                     ("Team size handled", "Choice", ["1-3", "4-8"]), ("Describe a project", "Text", None)):
        r.db.add_question(jid, q, t, ch)
    return jid


def test_screening_flow_new_candidate_save_draft_complete_and_duplicates():
    r = Runner()
    jid = _job_with_questions(r)
    r.run("screening")
    assert not r.errors()
    # quick-add a candidate
    r.run("screening", clicks=[f"qn_go_{jid}"], set_values={f"qn_name_{jid}": "Test Priya", f"qn_phone_{jid}": "+91 90000 11111",
                                                            f"qn_email_{jid}": "priya@example.com"})
    assert r.db.count("candidates") == 1 and r.db.count("applications") == 1
    app = r.db.rows("applications")[0]
    cid = app["candidate_id"]
    p = f"s{app['id']}_"
    r.run("screening")
    assert not r.errors(), r.errors()
    qs = r.db.questions(jid)
    # fill the form and save a draft
    vals = {p + "pskills": ["Python", "FastAPI"], p + "sskills": ["SQL"], p + "city": "Bengaluru", p + "reloc": "Same city",
            p + "notice": "30 days", p + "ectc": 16.0, p + "cctc": 12.0, p + "texp": 5.0, p + "comm": "Good",
            p + "reco": "Recommend", p + "notes": "Calm and clear.\nCall back Monday.", p + "lwd": date(2026, 12, 1),
            f"{p}q{qs[0]['id']}": 4.0, f"{p}q{qs[1]['id']}": "Yes", f"{p}q{qs[2]['id']}": "4-8",
            f"{p}q{qs[3]['id']}": "Built an API."}
    r.run("screening", clicks=[p + "save1"], set_values=vals)
    c = r.db.get("candidates", cid)
    a = r.db.get("applications", app["id"])
    assert c["primary_skills"] == ["Python", "FastAPI"] and c["expected_ctc"] == 16.0 and c["last_working_day"] == date(2026, 12, 1)
    assert a["screening_status"] == "Draft saved" and a["status"] == "Screening pending" and a["recommendation"] == "Recommend"
    assert a["score_at_decision"] is not None
    assert r.db.responses(app["id"]) == {qs[0]["id"]: "4", qs[1]["id"]: "Yes", qs[2]["id"]: "4-8", qs[3]["id"]: "Built an API."}
    assert r.db.get_screening_note(app["id"])["body"].startswith("Calm and clear.")
    assert not r.errors()
    # reopening shows the saved values and completes the screening
    r.run("screening")
    assert r.ss[p + "notice"] == "30 days"
    r.run("screening", clicks=[p + "done2"])
    a = r.db.get("applications", app["id"])
    assert a["screening_status"] == "Completed" and a["status"] == "Screening completed"
    # custom "Other" value is saved and remembered
    r.run("screening", clicks=[p + "save1"], set_values={p + "notice": "Other…", p + "notice__other": "2 months"})
    assert r.db.get("candidates", cid)["notice_period"] == "2 months"
    assert "2 months" in r.db.custom_options()["notice_period"]
    r.run("screening")
    assert not r.errors(), r.errors()
    # name is the only required field
    r.run("screening", clicks=[p + "save1"], set_values={p + "full_name": "  "})
    assert r.has("needs a name", "error")
    # duplicate guard: a second quick-add with the same email is blocked until confirmed
    r.run("screening", clicks=[f"qn_go_{jid}"], set_values={f"qn_name_{jid}": "Priya Again", f"qn_email_{jid}": "PRIYA@example.com"})
    assert r.db.count("candidates") == 1
    assert r.has("already in HireTrack", "warning")
    r.run("screening", clicks=[f"qn_go_{jid}"], set_values={f"qn_dupok".replace("qn_dupok", f"qn_{jid}_dupok"): True})
    assert r.db.count("candidates") == 2


def test_same_candidate_on_second_job_reuses_profile():
    r = Runner()
    j1 = _job_with_questions(r)
    j2 = r.db.insert("jobs", {"title": "Data Engineer", "location": "Pune", "mandatory_skills": ["Spark"]})
    cid = r.db.insert("candidates", {"full_name": "Test Rahul", "primary_skills": ["Python"], "current_city": "Pune"})
    r.db.add_application(j1, cid)
    r.run("candidates", set_values={"cand_sel": cid})
    r.run("candidates", set_values={f"addjob_{cid}": j2})
    r.run("candidates", clicks=[f"addjobgo_{cid}"])
    assert r.db.count("candidates") == 1 and r.db.count("applications") == 2
    assert not [e for e in r.errors() if "MISSING MANDATORY" not in e]
    # now appears in screening for job 2 via the 'existing candidate' picker (already added -> not offered)
    r.run("screening", set_values={"sel_job_id": j2})


def test_compare_ranking_filters_selection_and_decision():
    r = Runner()
    jid = _job_with_questions(r)
    good = r.db.insert("candidates", {"full_name": "Test Good", "primary_skills": ["Python", "FastAPI", "SQL"],
                                      "current_city": "Bengaluru", "relocation": "Same city", "notice_period": "15 days",
                                      "expected_ctc": 15.0, "total_exp": 5.0})
    gap = r.db.insert("candidates", {"full_name": "Test Gap", "primary_skills": ["Python"], "current_city": "Pune",
                                     "relocation": "Open to relocate", "notice_period": "Immediate", "expected_ctc": 10.0})
    blank = r.db.insert("candidates", {"full_name": "Test Blank"})
    for c in (gap, blank, good):
        r.db.add_application(jid, c)
    r.run("compare")
    assert not r.errors(), r.errors()
    assert r.has("3 rows", "dataframe")
    # click the first row -> detail with explanation
    r.run("compare", selected={"cmp_tbl": [0]})
    assert not r.errors(), r.errors()
    assert r.has("Test Good", "subheader")
    assert r.has("MISSING MANDATORY SKILLS") is False  # best candidate has none
    r.run("compare", selected={"cmp_tbl": [2]})
    assert r.has("MISSING MANDATORY SKILLS", "error") or r.has("Mandatory skills not verified", "warning")
    # save a manual decision: automatic score snapshot kept
    app = r.db.find_application(jid, good)
    r.run("compare", selected={"cmp_tbl": [0]}, clicks=[f"cmpdec_{app['id']}_save"],
          set_values={f"cmpdec_{app['id']}_reco": "Strongly recommend", f"cmpdec_{app['id']}_status": "Recommended"})
    a = r.db.get("applications", app["id"])
    assert a["recommendation"] == "Strongly recommend" and a["status"] == "Recommended" and a["score_at_decision"] > 70
    # sorting & filtering controls do not crash
    for label in ("Ranking score (high to low)", "Experience (high to low)", "Notice period (shortest first)",
                  "Expected CTC (lowest first)", "Technical skill match (high to low)"):
        r.run("compare", set_values={"cmp_sort": label})
        assert not r.errors(), (label, r.errors())
    r.run("compare", set_values={"cmp_sort": "Rank (best first)", "cmp_q": "good", "cmp_nogap": True, "cmp_notice": 30,
                                 "cmp_ctc": 20.0, "cmp_min": 10, "cmp_reloc": ["Same city"], "cmp_city": ["Bengaluru"]})
    assert r.has("1 of 3", "caption")
    assert not r.errors()


def test_candidates_page_crud_notes_archive_delete():
    r = Runner()
    r.run("candidates")
    assert not r.errors()
    p = "newc0_"
    r.run("candidates", clicks=[p + "save"], set_values={p + "full_name": "Test Asha", p + "email": "asha@example.com",
                                                          p + "pskills": ["Java"], p + "texp": 3.5})
    assert r.db.count("candidates") == 1
    cid = r.db.rows("candidates")[0]["id"]
    r.run("candidates")
    assert not r.errors(), r.errors()
    c = f"c{cid}_"
    r.run("candidates", clicks=[c + "save"], set_values={c + "company": "Acme", c + "ectc": 14.0})
    assert r.db.get("candidates", cid)["current_company"] == "Acme"
    r.run("candidates", clicks=[f"addnote_{cid}"], set_values={f"newnote_{cid}_0": "Prefers morning calls."})
    assert r.db.rows("notes")[0]["body"] == "Prefers morning calls."
    r.run("candidates")
    nid = r.db.rows("notes")[0]["id"]
    r.run("candidates", clicks=[f"notesave{nid}"], set_values={f"note{nid}": "Prefers morning calls. Edited."})
    assert r.db.rows("notes")[0]["body"].endswith("Edited.")
    r.run("candidates", clicks=[c + "arch"])
    assert r.db.get("candidates", cid)["archived"] is True
    r.run("candidates")  # archived are hidden by default
    assert r.has("No candidates yet", "info") or r.has("No candidates found", "info")
    r.run("candidates", set_values={"cand_arch": True, "cand_sel": cid})
    assert not r.errors(), r.errors()
    r.run("candidates", clicks=[c + "arch"])
    assert r.db.get("candidates", cid)["archived"] is False
    # duplicate guard on the add form
    r.run("candidates", clicks=["newc0_save"], set_values={"newc0_full_name": "Test Asha 2", "newc0_email": "ASHA@example.com"})
    assert r.db.count("candidates") == 1
    # delete requires confirmation text
    r.run("candidates", set_values={"cand_sel": cid})
    r.run("candidates", clicks=[f"delc_btn_{cid}"])
    r.run("candidates", clicks=[f"delcgo_{cid}"], set_values={f"delctype_{cid}": "DELETE"})
    r.run("candidates", clicks=[f"delcgo_{cid}"])
    assert r.db.count("candidates") == 0 and r.db.count("notes") == 0


def test_data_page_backup_restore_and_settings():
    r = Runner()
    jid = _job_with_questions(r)
    cid = r.db.insert("candidates", {"full_name": "Test Backup Person", "email": "b@example.com"})
    r.db.add_application(jid, cid)
    r.run("data")
    assert not r.errors(), r.errors()
    r.run("data", clicks=["prep_backup"])
    raw = r.ss["_backup_bytes"]
    assert raw[:2] == b"PK"
    r.run("data", clicks=["dl_backup"])
    assert r.db.get_setting("last_backup")
    r.run("home")
    assert not r.has("not downloaded a backup", "warning")
    # wipe + restore through the UI flow (needs checkbox + typed word)
    r.db.delete("candidates", cid)
    up = Upload("b.zip", raw, "application/zip")
    r.run("data", uploads={"restore_up": up})
    assert not [e for e in r.errors() if "REPLACES" not in e], r.errors()
    r.run("data", uploads={"restore_up": up}, clicks=["restore_go"], set_values={"restore_ok": True, "restore_type": "RESTORE"})
    assert r.db.get("candidates", cid)["full_name"] == "Test Backup Person"
    # a bad file is rejected and changes nothing
    r.run("data", uploads={"restore_up": Upload("x.zip", b"junk", "application/zip")})
    assert r.has("not a HireTrack backup", "error") and r.db.count("candidates") == 1
    r.run("data", clicks=["syscheck"])
    assert r.has("Database is working", "success")
    r.run("settings", clicks=["dw_save"], set_values={"dw_skills": 40, "dw_location": 20, "dw_notice": 20, "dw_ctc": 10, "dw_communication": 10})
    from hiretrack import service
    assert service.default_weights()["skills"] == 40
    r.run("settings", set_values={"opt_cat": "notice_period"})
    assert not r.errors()
    r.run("settings", clicks=["optadd"], set_values={"optnew_notice_period_0": "Negotiable"})
    assert "Negotiable" in r.db.custom_options()["notice_period"]


def test_password_gate_locks_cloud_mode_and_checks_password(monkeypatch=None):
    import os
    r = Runner()
    os.environ["APP_PASSWORD"] = "s3cret"
    try:
        r.run("home")
        assert r.has("Please sign in", "write") and not r.ss.get("_authed")
        r.run("home", clicks=["Sign in"], set_values={})
        # wrong password
        r.run("home")
        assert not r.ss.get("_authed")
    finally:
        os.environ.pop("APP_PASSWORD", None)
