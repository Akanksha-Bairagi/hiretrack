import os
import tempfile

from hiretrack import db as dbm


def fresh_db():
    """A brand-new SQLite database in a temp dir, installed as the app database."""
    path = os.path.join(tempfile.mkdtemp(prefix="hiretrack_test_"), "t.db")
    d = dbm.Database(path=path)
    dbm.set_db(d)
    d.init()
    return d


def make_job(d, **kw):
    base = dict(title="Python Developer", department="Engineering", location="Bengaluru", work_mode="Hybrid",
                exp_min=3, exp_max=6, budget_min=12, budget_max=18,
                mandatory_skills=["Python", "FastAPI", "SQL"], preferred_skills=["Docker", "AWS"])
    base.update(kw)
    return d.insert("jobs", base)


def make_cand(d, **kw):
    base = dict(full_name="Test Candidate One", email="one@example.com", phone="+91 90000 00001",
                primary_skills=["Python", "FastAPI"], secondary_skills=["SQL"], additional_skills=["Docker"],
                current_city="Bengaluru", relocation="Same city", notice_period="30 days",
                current_ctc=12, expected_ctc=16, total_exp=5, relevant_exp=4)
    base.update(kw)
    return d.insert("candidates", base)
