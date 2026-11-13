"""Default dropdown options and small parsing helpers.

Defaults are only a starting point: the recruiter can type any custom value
("Other...") and it is remembered and offered next time (see Settings page).
"""
from __future__ import annotations

import re

DEFAULT_OPTIONS = {
    "notice_period": ["Immediate", "15 days", "30 days", "45 days", "60 days", "90 days"],
    "relocation": ["Same city", "Open to relocate", "Not open to relocate", "Remote only", "Unknown"],
    "employment_status": ["Currently employed", "Serving notice period", "Not employed", "Unknown"],
    "work_mode": ["On-site", "Hybrid", "Remote"],
    "communication": ["Excellent", "Good", "Satisfactory", "Needs improvement", "Poor"],
    "impression": ["Excellent", "Good", "Average", "Below average"],
    "recommendation": ["Strongly recommend", "Recommend", "Maybe", "Not recommended", "Not decided"],
    "department": ["Engineering", "Data", "Product", "Design", "QA", "DevOps", "HR", "Sales", "Finance", "Operations"],
    "city": ["Bengaluru", "Hyderabad", "Pune", "Chennai", "Mumbai", "Delhi NCR", "Gurugram", "Noida", "Kolkata", "Bhopal", "Indore", "Ahmedabad"],
}

OPTION_TITLES = {
    "notice_period": "Notice period",
    "relocation": "Relocation",
    "employment_status": "Employment status",
    "work_mode": "Work mode",
    "communication": "Communication",
    "impression": "Overall impression",
    "recommendation": "Recommendation",
    "department": "Department",
    "city": "Cities",
}

APP_STATUSES = [
    "Added", "Screening pending", "Screening completed", "Recommended",
    "On hold", "Rejected", "Shared with hiring manager", "Selected",
]
JOB_STATUSES = ["Active", "On hold", "Closed", "Archived"]
SCREENING_STATUSES = ["Not started", "Draft saved", "Completed"]
YES_NO_UNKNOWN = ["Yes", "No", "Unknown"]
QUESTION_TYPES = ["Text", "Yes/No", "Number", "Choice"]

_NUM = re.compile(r"(\d+(?:\.\d+)?)")


def parse_notice_days(text):
    """'30 days' -> 30, 'Immediate' -> 0, '2 months' -> 60, unknown -> None."""
    if text is None:
        return None
    t = str(text).strip().lower()
    if not t:
        return None
    if "immediate" in t or t in {"0", "nil", "none", "now"}:
        return 0
    m = _NUM.search(t)
    if not m:
        return None
    n = float(m.group(1))
    if "month" in t or re.search(r"\bm\b", t):
        n *= 30
    elif "week" in t:
        n *= 7
    return int(round(n))
