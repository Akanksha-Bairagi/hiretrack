"""Glue between the database and the scoring engine (no Streamlit here)."""
from __future__ import annotations

import pandas as pd

from . import db as dbm
from .scoring import compute_score, rank_results


def join_list(v) -> str:
    return ", ".join(v) if isinstance(v, (list, tuple)) else ("" if v is None else str(v))


def build_comparison(job_id: int, include_archived: bool = False):
    """Returns (job, rows) with rows ranked. Each row: app, cand, score, rank."""
    d = dbm.get_db()
    job = d.get("jobs", job_id)
    if not job:
        return None, []
    items = []
    for app, cand in d.job_pairs(job_id, include_archived):
        items.append(((app, cand), compute_score(job, cand, app), cand["full_name"] or ""))
    ranked = rank_results([(k, r, n) for k, r, n in items], strict=bool(job.get("strict_mandatory", True)))
    rows = []
    for i, ((app, cand), res, _) in enumerate(ranked, start=1):
        rows.append({"rank": i, "app": app, "cand": cand, "score": res})
    return job, rows


def _skill_match_text(res):
    s = res["skills"]
    if not s["recorded"]:
        return "Not recorded"
    m, miss = len(s["mandatory_matched"]), len(s["mandatory_missing"])
    total = m + miss
    return f"{m}/{total} mandatory" if total else "n/a"


def _skill_pct(res):
    s = res["skills"]
    if not s["recorded"]:
        return None
    total = len(s["mandatory_matched"]) + len(s["mandatory_missing"])
    return round(100 * len(s["mandatory_matched"]) / total) if total else None


def comparison_frame(rows) -> pd.DataFrame:
    recs = []
    for r in rows:
        a, c, s = r["app"], r["cand"], r["score"]
        recs.append({
            "Rank": r["rank"], "Candidate": c["full_name"], "Total exp (yrs)": c["total_exp"],
            "Relevant exp (yrs)": c["relevant_exp"], "Skill match": _skill_match_text(s),
            "Skill match %": _skill_pct(s), "Missing mandatory skills": join_list(s["skills"]["mandatory_missing"]),
            "Current CTC (LPA)": c["current_ctc"], "Expected CTC (LPA)": c["expected_ctc"],
            "Current city": c["current_city"], "Preferred location": c["preferred_location"],
            "Relocation": c["relocation"], "Notice period": c["notice_period"],
            "Notice (days)": s["notice_days"], "Communication": a["communication"],
            "Score": s["total"], "Score range": f"{s['low']:.0f}-{s['high']:.0f}", "Confidence": s["confidence"],
            "Auto assessment": s["label"], "Recruiter recommendation": a["recommendation"],
            "Screening status": a["screening_status"], "Pipeline status": a["status"],
            "Flags": " | ".join(f["text"] for f in s["flags"]),
            "_app_id": a["id"], "_cand_id": c["id"],
        })
    return pd.DataFrame(recs)


def screening_matrix(job_id: int, rows) -> pd.DataFrame:
    d = dbm.get_db()
    qs = d.questions(job_id)
    recs = []
    for r in rows:
        resp = d.responses(r["app"]["id"])
        rec = {"Candidate": r["cand"]["full_name"]}
        for q in qs:
            rec[q["question"]] = resp.get(q["id"])
        recs.append(rec)
    return pd.DataFrame(recs)


def candidate_frame(cands) -> pd.DataFrame:
    recs = []
    for c in cands:
        rec = {k: (join_list(v) if isinstance(v, list) else v) for k, v in c.items()}
        recs.append(rec)
    return pd.DataFrame(recs)


def all_skill_suggestions() -> list:
    """Every skill already used on a job or candidate, for the autocomplete lists."""
    from .pdf_utils import SKILL_VOCAB

    d = dbm.get_db()
    seen = {s.lower(): s for s in SKILL_VOCAB}
    for j in d.rows("jobs"):
        for s in (j["mandatory_skills"] or []) + (j["preferred_skills"] or []):
            seen.setdefault(s.lower(), s)
    for c in d.rows("candidates"):
        for s in (c["primary_skills"] or []) + (c["secondary_skills"] or []) + (c["additional_skills"] or []):
            seen.setdefault(s.lower(), s)
    return sorted(seen.values(), key=str.lower)


def default_weights() -> dict:
    """The recruiter's saved default scoring weights (falls back to 50/20/15/10/5)."""
    import json

    from .scoring import DEFAULT_WEIGHTS, norm_weights

    raw = dbm.get_db().get_setting("default_weights")
    try:
        return {k: round(v) for k, v in norm_weights(json.loads(raw) if raw else DEFAULT_WEIGHTS).items()}
    except ValueError:
        return dict(DEFAULT_WEIGHTS)


def save_default_weights(w: dict) -> None:
    import json

    dbm.get_db().set_setting("default_weights", json.dumps(w))


def starter_questions(job_id: int, skills) -> int:
    """One 'years of experience' question per skill. Returns how many were added."""
    d = dbm.get_db()
    have = {q["question"].lower() for q in d.questions(job_id)}
    n = 0
    for s in skills:
        text = f"How many years of hands-on experience do you have in {s}?"
        if text.lower() not in have:
            d.add_question(job_id, text, "Number")
            n += 1
    return n
