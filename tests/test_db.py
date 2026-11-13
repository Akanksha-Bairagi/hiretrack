import io
import sqlite3
import zipfile
from datetime import date

from hiretrack import db as dbm
from hiretrack import exports, service
from tests.helpers import fresh_db, make_cand, make_job


def test_job_crud_and_json_roundtrip():
    d = fresh_db()
    jid = make_job(d)
    j = d.get("jobs", jid)
    assert j["mandatory_skills"] == ["Python", "FastAPI", "SQL"] and j["status"] == "Active"
    assert j["strict_mandatory"] is True and j["created_at"] is not None
    d.update("jobs", jid, {"title": "Senior Python Dev", "status": "On hold", "budget_max": None})
    j = d.get("jobs", jid)
    assert j["title"] == "Senior Python Dev" and j["status"] == "On hold" and j["budget_max"] is None
    d.delete("jobs", jid)
    assert d.get("jobs", jid) is None


def test_candidate_can_be_saved_incomplete_and_blank_becomes_null():
    d = fresh_db()
    cid = d.insert("candidates", {"full_name": "Only Name", "email": "  ", "current_ctc": None})
    c = d.get("candidates", cid)
    assert c["email"] is None and c["primary_skills"] == [] and c["archived"] is False
    d.update("candidates", cid, {"last_working_day": date(2026, 3, 1), "notice_period": "60 days"})
    assert d.get("candidates", cid)["last_working_day"] == date(2026, 3, 1)


def test_one_candidate_many_jobs_and_unique_application():
    d = fresh_db()
    j1, j2 = make_job(d), make_job(d, title="Data Engineer")
    c = make_cand(d)
    a1, a2 = d.add_application(j1, c), d.add_application(j2, c)
    assert a1 != a2
    assert d.add_application(j1, c) == a1  # no duplicate application
    assert len(d.candidate_apps(c)) == 2
    assert d.count("candidates") == 1


def test_screening_answers_belong_to_application():
    d = fresh_db()
    j1, j2 = make_job(d), make_job(d, title="Other")
    c = make_cand(d)
    a1, a2 = d.add_application(j1, c), d.add_application(j2, c)
    q1 = d.add_question(j1, "Years of Python?", "Number")
    q2 = d.add_question(j1, "Why switch?")
    d.save_responses(a1, {q1: "5", q2: "Growth"})
    assert d.responses(a1) == {q1: "5", q2: "Growth"} and d.responses(a2) == {}
    d.save_responses(a1, {q1: "6", q2: ""})  # update + clear
    assert d.responses(a1) == {q1: "6"}


def test_question_ordering():
    d = fresh_db()
    j = make_job(d)
    ids = [d.add_question(j, f"Q{i}") for i in range(3)]
    d.move_question(j, ids[2], -1)
    assert [q["id"] for q in d.questions(j)] == [ids[0], ids[2], ids[1]]
    d.move_question(j, ids[0], -1)  # already first: no change
    assert [q["id"] for q in d.questions(j)][0] == ids[0]


def test_duplicate_detection_email_and_phone():
    d = fresh_db()
    c = make_cand(d, email="Priya@Example.com", phone="+91 98765-43210")
    assert [x["id"] for x in d.find_duplicates(email="priya@example.COM")] == [c]
    assert d.find_duplicates(phone="098765 43210")[0]["match_on"] == "phone"
    assert d.find_duplicates(email="other@example.com", phone="1234") == []
    assert d.find_duplicates(email="priya@example.com", exclude_id=c) == []
    make_cand(d, full_name="Dup", email="priya@example.com", phone=None)
    assert len(d.duplicate_groups()) == 1


def test_cascade_delete_and_impact():
    d = fresh_db()
    j, c = make_job(d), make_cand(d)
    a = d.add_application(j, c)
    q = d.add_question(j, "Q")
    d.save_responses(a, {q: "x"})
    d.save_screening_note(a, c, "good call")
    d.save_file("resume", "cv.pdf", "application/pdf", b"%PDF-1.4 test", candidate_id=c)
    assert d.job_impact(j) == {"applications": 1, "responses": 1, "notes": 1, "questions": 1}
    assert d.candidate_impact(c) == {"applications": 1, "responses": 1, "notes": 1, "files": 1}
    d.insert("notes", {"candidate_id": c, "body": "general note about the person"})
    d.delete("jobs", j)
    assert d.count("applications") == d.count("screening_responses") == d.count("screening_questions") == 0
    # application-level screening note goes with the job; candidate + general note survive
    assert d.count("notes") == 1 and d.count("candidates") == 1 and d.count("files") == 1
    d.delete("candidates", c)
    assert d.count("notes") == 0 and d.count("files") == 0


def test_screening_note_upsert_and_clear():
    d = fresh_db()
    j, c = make_job(d), make_cand(d)
    a = d.add_application(j, c)
    d.save_screening_note(a, c, "first")
    d.save_screening_note(a, c, "second")
    assert d.count("notes") == 1 and d.get_screening_note(a)["body"] == "second"
    d.save_screening_note(a, c, "")
    assert d.get_screening_note(a) is None


def test_files_replace_and_meta():
    d = fresh_db()
    j = make_job(d)
    d.save_file("jd", "a.pdf", "application/pdf", b"one", job_id=j)
    d.save_file("jd", "b.pdf", "application/pdf", b"twotwo", job_id=j)
    m = d.file_meta("jd", job_id=j)
    assert m["filename"] == "b.pdf" and m["size_bytes"] == 6 and d.count("files") == 1
    assert d.file_data(m["id"])["data"] == b"twotwo"


def test_options_and_settings():
    d = fresh_db()
    d.add_option("notice_period", "2 months")
    d.add_option("notice_period", "2 months")
    d.add_option("notice_period", "   ")
    assert d.custom_options() == {"notice_period": ["2 months"]}
    d.delete_option("notice_period", "2 months")
    assert d.custom_options() == {}
    d.set_setting("x", "1")
    d.set_setting("x", "2")
    assert d.get_setting("x") == "2" and d.get_setting("nope", "dflt") == "dflt"
    assert "SQLite" in d.selftest()


def test_job_stats_and_clone():
    d = fresh_db()
    j, c1, c2 = make_job(d), make_cand(d), make_cand(d, full_name="Two", email="two@example.com")
    a1, a2 = d.add_application(j, c1), d.add_application(j, c2)
    d.update("applications", a1, {"screening_status": "Completed", "status": "Recommended"})
    d.update("applications", a2, {"archived": True})
    assert d.job_stats()[j] == {"n_apps": 1, "n_done": 1, "n_reco": 1}
    d.add_question(j, "Q1")
    j2 = d.clone_job(j)
    assert d.get("jobs", j2)["title"].endswith("(copy)") and len(d.questions(j2)) == 1
    assert d.count("applications") == 2  # clone does not copy candidates


def test_additive_migration_adds_missing_column():
    d = fresh_db()
    con = sqlite3.connect(d.path)
    con.execute("ALTER TABLE jobs RENAME TO jobs_old")
    con.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)")
    con.execute("INSERT INTO jobs (title) VALUES ('Old')")
    con.commit(); con.close()
    d2 = dbm.Database(path=d.path)
    d2._migrate()
    assert d2.rows("jobs")[0]["title"] == "Old" and d2.rows("jobs")[0]["mandatory_skills"] == []


def test_postgres_ddl_looks_sane():
    pg = dbm.Database(url="postgresql://u:p@h:5432/db")
    ddl = pg.ddl_preview()
    assert "SERIAL PRIMARY KEY" in ddl and "BYTEA" in ddl and "TIMESTAMP" in ddl and "DOUBLE PRECISION" in ddl
    assert "AUTOINCREMENT" not in ddl and "ON DELETE CASCADE" in ddl
    assert pg._enc("date", date(2026, 1, 2)) == date(2026, 1, 2)  # native types stay native on Postgres


def _populated():
    d = fresh_db()
    j = make_job(d)
    c1, c2 = make_cand(d), make_cand(d, full_name="Test Candidate Two", email="two@example.com",
                                     primary_skills=["Java"], last_working_day=date(2026, 5, 5))
    a1, a2 = d.add_application(j, c1), d.add_application(j, c2)
    q = d.add_question(j, "Years of Python?", "Number")
    d.save_responses(a1, {q: "5"})
    d.update("applications", a1, {"communication": "Good", "recommendation": "Recommend", "observations": "Calm, clear."})
    d.save_screening_note(a1, c1, "Long free-text note\nwith lines")
    d.save_file("jd", "jd.pdf", "application/pdf", b"%PDF fake bytes", job_id=j)
    d.save_file("resume", "cv.pdf", "application/pdf", b"resume-bytes\x00\xff", candidate_id=c1)
    d.add_option("city", "Jabalpur")
    return d, j, c1, c2


def test_exports_open_in_openpyxl_and_have_content():
    import openpyxl
    d, j, c1, c2 = _populated()
    wb = openpyxl.load_workbook(io.BytesIO(exports.job_xlsx(j)))
    assert set(wb.sheetnames) == {"Comparison", "Screening answers", "Ranking explanation", "Job details"}
    ws = wb["Comparison"]
    headers = [c.value for c in ws[1]]
    assert "Score" in headers and "Missing mandatory skills" in headers and not any(str(h).startswith("_") for h in headers)
    assert ws.max_row == 3
    wb = openpyxl.load_workbook(io.BytesIO(exports.candidate_xlsx(c1)))
    assert "Profile" in wb.sheetnames and wb["Screening answers"].max_row == 2
    wb = openpyxl.load_workbook(io.BytesIO(exports.all_xlsx()))
    assert wb["Candidates"].max_row == 3 and wb["Notes"].max_row == 2
    z = zipfile.ZipFile(io.BytesIO(exports.all_csv_zip()))
    assert "Candidates.csv" in z.namelist()
    assert b"Test Candidate One" in z.read("Candidates.csv")
    assert b"Test Candidate One" in exports.candidate_json(c1)
    assert b"Python" in exports.job_csv(j)


def test_backup_roundtrip_restores_everything():
    d, j, c1, c2 = _populated()
    raw = exports.backup_zip()
    before = d.table_counts()
    # wreck the database, then restore
    d.delete("jobs", j); d.delete("candidates", c1); d.delete("candidates", c2)
    assert d.count("candidates") == 0
    data, blobs, errors, warnings, summary = exports.validate_backup(raw)
    assert errors == [] and data is not None and summary["counts"]["candidates"] == 2
    exports.restore_backup(data, blobs)
    assert d.table_counts() == before
    cand = d.get("candidates", c2)
    assert cand["last_working_day"] == date(2026, 5, 5) and cand["primary_skills"] == ["Java"]
    assert d.file_data(d.file_meta("resume", candidate_id=c1)["id"])["data"] == b"resume-bytes\x00\xff"
    a1 = d.find_application(j, c1)
    assert d.responses(a1["id"]) and d.get_screening_note(a1["id"])["body"].startswith("Long free-text")
    assert a1["recommendation"] == "Recommend"
    # new rows after restore must not collide with restored ids
    new_id = d.insert("candidates", {"full_name": "After restore"})
    assert new_id not in (c1, c2)


def test_restore_replaces_existing_data_atomically():
    d, j, c1, c2 = _populated()
    raw = exports.backup_zip()
    extra = d.insert("candidates", {"full_name": "Added after backup"})
    data, blobs, errors, _, _ = exports.validate_backup(raw)
    exports.restore_backup(data, blobs)
    assert d.get("candidates", extra) is None  # replaced, as the warning says
    # a broken restore must roll back and leave data untouched
    bad = {n: list(rows) for n, rows in data.items()}
    bad["applications"] = bad["applications"] + [{"id": 999, "job_id": 12345, "candidate_id": c1}]
    before = d.table_counts()
    try:
        exports.restore_backup(bad, blobs)
        raised = False
    except Exception:
        raised = True
    assert raised and d.table_counts() == before


def test_backup_validation_catches_bad_files():
    d, *_ = _populated()
    assert exports.validate_backup(b"not a zip")[2]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "x")
    assert "backup.json is missing" in exports.validate_backup(buf.getvalue())[2][0]
    good = exports.backup_zip()
    zin = zipfile.ZipFile(io.BytesIO(good))
    import json
    meta = json.loads(zin.read("backup.json"))
    meta["tables"]["applications"][0]["job_id"] = 424242
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("backup.json", json.dumps(meta))
        for n in zin.namelist():
            if n.startswith("files/"):
                z.writestr(n, zin.read(n))
    data, _, errors, _, _ = exports.validate_backup(buf.getvalue())
    assert data is None and any("missing job" in e for e in errors)
    meta["app"] = "SomethingElse"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("backup.json", json.dumps(meta))
    assert any("not created by HireTrack" in e for e in exports.validate_backup(buf.getvalue())[2])


def test_comparison_ranking_and_frame():
    d, j, c1, c2 = _populated()
    job, rows = service.build_comparison(j)
    assert [r["cand"]["id"] for r in rows] == [c1, c2]  # full skills first, gap candidate last
    assert rows[1]["score"]["has_mandatory_gap"]
    df = service.comparison_frame(rows)
    assert list(df["Rank"]) == [1, 2] and df.loc[1, "Missing mandatory skills"] == "Python, FastAPI"
    assert "_app_id" in df.columns
