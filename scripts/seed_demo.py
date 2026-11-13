"""Fill a LOCAL database with dummy data so you can look around:  python scripts/seed_demo.py
(Never run this against the real recruiter database.)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hiretrack import db as dbm, service  # noqa: E402

d = dbm.get_db()
if d.count("jobs"):
    sys.exit("Database is not empty; refusing to add demo data.")
jid = d.insert("jobs", {"title": "Python Developer (DEMO)", "department": "Engineering", "location": "Bengaluru",
                        "work_mode": "Hybrid", "exp_min": 3, "exp_max": 6, "budget_min": 12, "budget_max": 18,
                        "mandatory_skills": ["Python", "FastAPI", "SQL"], "preferred_skills": ["Docker", "AWS"],
                        "weights": service.default_weights()})
service.starter_questions(jid, ["Python", "FastAPI", "SQL"])
people = [
    ("Demo Asha Rao", ["Python", "FastAPI"], ["SQL", "Docker"], "Bengaluru", "Same city", "30 days", 15, "Good"),
    ("Demo Ravi Kumar", ["Python"], ["Django"], "Pune", "Open to relocate", "Immediate", 11, "Excellent"),
    ("Demo Meera Iyer", ["Python", "FastAPI", "SQL"], ["AWS"], "Chennai", "Not open to relocate", "60 days", 22, "Satisfactory"),
    ("Demo Karan Shah", [], [], None, None, None, None, None),
]
for name, p, s, city, reloc, notice, ectc, comm in people:
    cid = d.insert("candidates", {"full_name": name, "email": name.lower().replace(" ", ".") + "@example.com",
                                  "primary_skills": p, "secondary_skills": s, "current_city": city, "relocation": reloc,
                                  "notice_period": notice, "expected_ctc": ectc, "total_exp": 4})
    aid = d.add_application(jid, cid)
    if comm:
        d.update("applications", aid, {"communication": comm, "screening_status": "Completed",
                                       "status": "Screening completed"})
print("Demo data added.")
