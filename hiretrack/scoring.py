"""Deterministic, transparent candidate scoring.

Pure functions only (no database, no Streamlit) so it is easy to test. Every
sentence in the explanation is produced from the actual inputs.

Unknown information is never scored as zero: it counts as HALF marks for that
criterion, is clearly labelled "estimated", and lowers the ranking confidence.
The score range shown to the recruiter is what the candidate would score if
every unknown turned out worst-case (0) or best-case (full marks).
"""
from __future__ import annotations

import re
from datetime import date

from .options import parse_notice_days

DEFAULT_WEIGHTS = {"skills": 50, "location": 20, "notice": 15, "ctc": 10, "communication": 5}
LABELS = {"skills": "Technical skills", "location": "Location", "notice": "Notice period",
          "ctc": "Expected CTC", "communication": "Communication"}
NEUTRAL = 0.5

COMM_SCORES = {"excellent": 1.0, "good": 0.8, "satisfactory": 0.6, "needs improvement": 0.3, "poor": 0.1}

_SKILL_SYNONYMS = {
    "js": "javascript", "ecmascript": "javascript", "ts": "typescript", "postgres": "postgresql",
    "postgre": "postgresql", "psql": "postgresql", "reactjs": "react", "nodejs": "node", "node": "node",
    "expressjs": "express", "vuejs": "vue", "k8s": "kubernetes", "py": "python", "python3": "python",
    "mongo": "mongodb", "golang": "go", "amazonwebservices": "aws", "scikitlearn": "sklearn",
    "sklearn": "sklearn", "ml": "machinelearning", "dl": "deeplearning", "gha": "githubactions",
    "springboot": "springboot", "sqlserver": "sqlserver", "mssql": "sqlserver", "microsoftsqlserver": "sqlserver",
    "powerbi": "powerbi", "msexcel": "excel", "microsoftexcel": "excel", "dotnet": "net", "csharp": "c#",
}
_CITY_ALIASES = {
    "bengaluru": "bangalore", "bengalooru": "bangalore", "gurgaon": "gurugram", "bombay": "mumbai",
    "madras": "chennai", "calcutta": "kolkata", "poona": "pune", "new delhi": "delhi", "delhi ncr": "delhi",
    "ncr": "delhi", "hyd": "hyderabad", "blr": "bangalore",
}


def skill_key(s) -> str:
    k = re.sub(r"[\s\.\-_/]+", "", str(s).strip().lower())
    return _SKILL_SYNONYMS.get(k, k)


def city_key(s) -> str:
    k = re.sub(r"\s+", " ", str(s or "").strip().lower())
    return _CITY_ALIASES.get(k, k)


def split_locations(text) -> set:
    return {city_key(p) for p in re.split(r"[,/;|]", str(text or "")) if p.strip()}


def _uniq(items):
    seen, out = set(), []
    for i in items or []:
        k = skill_key(i)
        if k and k not in seen:
            seen.add(k)
            out.append(str(i).strip())
    return out


def norm_weights(w) -> dict:
    out = {}
    for k, d in DEFAULT_WEIGHTS.items():
        try:
            v = float((w or {}).get(k, d))
        except (TypeError, ValueError):
            v = float(d)
        out[k] = max(v, 0.0)
    if sum(out.values()) <= 0:
        out = {k: float(v) for k, v in DEFAULT_WEIGHTS.items()}
    return out


def _crit(known, score, assessment, pos=None, neg=None):
    return {"known": known, "score": score, "assessment": assessment,
            "positives": pos or [], "deductions": neg or []}


# --------------------------------------------------------------------------
# Individual criteria
# --------------------------------------------------------------------------
def _eval_skills(job, cand):
    mand = _uniq(job.get("mandatory_skills"))
    pref = _uniq(job.get("preferred_skills"))
    have_list = _uniq((cand.get("primary_skills") or []) + (cand.get("secondary_skills") or [])
                      + (cand.get("additional_skills") or []))
    have = {skill_key(s) for s in have_list}
    detail = {"mandatory_matched": [], "mandatory_missing": [], "mandatory_unverified": [],
              "preferred_matched": [], "preferred_missing": [], "additional": [], "recorded": bool(have)}
    if not mand and not pref:
        return _crit(False, NEUTRAL, "This job has no skills defined, so skills could not be scored."), detail
    if not have:
        detail["mandatory_unverified"] = mand
        return _crit(False, NEUTRAL,
                     "No skills recorded for this candidate yet, so they cannot be checked against the job. "
                     "Counted as half marks until skills are entered."), detail
    detail["mandatory_matched"] = [s for s in mand if skill_key(s) in have]
    detail["mandatory_missing"] = [s for s in mand if skill_key(s) not in have]
    detail["preferred_matched"] = [s for s in pref if skill_key(s) in have]
    detail["preferred_missing"] = [s for s in pref if skill_key(s) not in have]
    wanted = {skill_key(s) for s in mand + pref}
    detail["additional"] = [s for s in have_list if skill_key(s) not in wanted]

    m = len(detail["mandatory_matched"]) / len(mand) if mand else None
    p = len(detail["preferred_matched"]) / len(pref) if pref else None
    if m is not None and p is not None:
        score = 0.8 * m + 0.2 * p
    else:
        score = m if m is not None else p
    pos, neg = [], []
    if mand:
        if not detail["mandatory_missing"]:
            pos.append(f"All {len(mand)} mandatory skills matched.")
        else:
            neg.append(f"Missing {len(detail['mandatory_missing'])} of {len(mand)} mandatory skills: "
                       f"{', '.join(detail['mandatory_missing'])}.")
            if detail["mandatory_matched"]:
                pos.append(f"Matched {len(detail['mandatory_matched'])} of {len(mand)} mandatory skills: "
                           f"{', '.join(detail['mandatory_matched'])}.")
    if pref:
        if detail["preferred_matched"]:
            pos.append(f"Matched {len(detail['preferred_matched'])} of {len(pref)} preferred skills: "
                       f"{', '.join(detail['preferred_matched'])}.")
        else:
            neg.append("None of the preferred skills were matched.")
    msg = (f"{len(detail['mandatory_matched'])}/{len(mand)} mandatory"
           + (f", {len(detail['preferred_matched'])}/{len(pref)} preferred" if pref else "") + " skills matched.")
    return _crit(True, score, msg, pos, neg), detail


def _eval_location(job, cand):
    mode = (job.get("work_mode") or "").strip().lower()
    job_locs = split_locations(job.get("location"))
    city = city_key(cand.get("current_city"))
    reloc = (cand.get("relocation") or "").strip().lower()
    pref = city_key(cand.get("preferred_location"))
    jl = (job.get("location") or "the job location").strip()

    if mode == "remote":
        return _crit(True, 1.0, "Job is remote, so location does not matter.",
                     ["Job is remote, so location is not a constraint."])
    if not job_locs:
        return _crit(False, NEUTRAL, "The job has no location set, so location could not be scored.")
    if (city and city in job_locs) or reloc == "same city":
        where = cand.get("current_city") or "the job city"
        return _crit(True, 1.0, f"Already based in {where}.", [f"Already based in {where} (job location: {jl})."])
    if reloc == "remote only":
        return _crit(True, 0.1, f"Wants remote work only; this job is {mode or 'office-based'}.", None,
                     [f"Wants remote only but this job is {mode or 'office-based'} in {jl}."])
    if reloc == "open to relocate":
        if pref and pref in job_locs:
            return _crit(True, 0.8, f"Open to relocating and prefers {jl}.",
                         [f"Open to relocating, and {jl} is a preferred location."])
        base = f"Currently in {cand.get('current_city')}, " if cand.get("current_city") else ""
        return _crit(True, 0.6, f"{base}open to relocating to {jl}.",
                     [f"Open to relocating to {jl}."],
                     [f"Not currently in {jl}; relocation needed."])
    if reloc == "not open to relocate":
        if city:
            return _crit(True, 0.0, f"Based in {cand.get('current_city')} and not open to relocating to {jl}.", None,
                         [f"Based in {cand.get('current_city')}, not open to relocate; job is in {jl}."])
        return _crit(False, NEUTRAL, "Not open to relocating, but current city is not recorded, so it is unclear "
                                     "whether they already live in the job city.")
    if city:
        return _crit(False, NEUTRAL, f"Based in {cand.get('current_city')} (job is in {jl}) and relocation "
                                     "preference is not recorded. Counted as half marks.")
    return _crit(False, NEUTRAL, "Current city and relocation preference are not recorded. Counted as half marks.")


def notice_days_for(cand, today=None):
    """Best available estimate of days until the candidate can join, plus a source note."""
    today = today or date.today()
    if (cand.get("immediate_joiner") or "").lower() == "yes":
        return 0, "marked as an immediate joiner"
    if (cand.get("employment_status") or "").lower() == "not employed" and not cand.get("notice_period"):
        return 0, "not currently employed"
    for field, label in (("earliest_joining", "earliest joining date"), ("last_working_day", "last working day")):
        d = cand.get(field)
        if d:
            return max((d - today).days, 0), f"based on {label} ({d.isoformat()})"
    days = parse_notice_days(cand.get("notice_period"))
    if days is not None:
        return days, f"notice period recorded as '{cand.get('notice_period')}'"
    return None, ""


def _notice_score(days):
    for limit, s in ((0, 1.0), (15, 0.9), (30, 0.75), (45, 0.6), (60, 0.45), (90, 0.3)):
        if days <= limit:
            return s
    return 0.2


def _eval_notice(cand, today=None):
    days, why = notice_days_for(cand, today)
    if days is None:
        return _crit(False, NEUTRAL, "Notice period not recorded. Counted as half marks."), None
    s = _notice_score(days)
    if days == 0:
        return _crit(True, s, f"Can join immediately ({why}).", [f"Can join immediately ({why})."]), days
    if days <= 30:
        return _crit(True, s, f"About {days} days to join ({why}).", [f"Short notice: about {days} days ({why})."]), days
    return _crit(True, s, f"About {days} days to join ({why}).", None,
                 [f"Longer notice: about {days} days ({why}); preferred is 30 days or less."]), days


def _eval_ctc(job, cand):
    exp = cand.get("expected_ctc")
    bmax, bmin = job.get("budget_max"), job.get("budget_min")
    if exp is None:
        return _crit(False, NEUTRAL, "Expected CTC not recorded. Counted as half marks.")
    if not bmax:
        return _crit(False, NEUTRAL, f"Expected CTC is {exp:g} LPA but the job has no budget set, so it could "
                                     "not be scored.")
    if exp <= bmax:
        score = 0.9 + 0.1 * (1 - exp / bmax)
        txt = f"Expected {exp:g} LPA is within the budget (up to {bmax:g} LPA)."
        if bmin and exp < bmin:
            txt += f" It is below the lower end of the range ({bmin:g} LPA)."
        return _crit(True, min(score, 1.0), txt, [txt])
    over = (exp - bmax) / bmax
    negotiable = (cand.get("negotiable") or "").lower() == "yes"
    penalty = 2.5 * over * (0.5 if negotiable else 1.0)
    score = max(0.0, 0.8 - penalty)
    txt = f"Expected {exp:g} LPA is {over * 100:.0f}% above the budget of {bmax:g} LPA"
    txt += " (candidate says it is negotiable, so the penalty is halved)." if negotiable else "."
    return _crit(True, score, txt, None, [txt])


def _eval_comm(app):
    c = ((app or {}).get("communication") or "").strip()
    if not c:
        return _crit(False, NEUTRAL, "Communication not assessed yet. Counted as half marks.")
    s = COMM_SCORES.get(c.lower())
    if s is None:
        return _crit(False, NEUTRAL, f"Communication recorded as '{c}', which is a custom value the scorer "
                                     "cannot rate. Counted as half marks.")
    if s >= 0.8:
        return _crit(True, s, f"Communication assessed as {c}.", [f"Communication assessed as {c}."])
    if s <= 0.3:
        return _crit(True, s, f"Communication assessed as {c}.", None, [f"Communication assessed as {c}."])
    return _crit(True, s, f"Communication assessed as {c}.")


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def compute_score(job: dict, cand: dict, app: dict | None = None, today: date | None = None) -> dict:
    weights = norm_weights(job.get("weights"))
    total_w = sum(weights.values())
    skills_c, skill_detail = _eval_skills(job, cand)
    notice_c, notice_days = _eval_notice(cand, today)
    crits = {
        "skills": skills_c,
        "location": _eval_location(job, cand),
        "notice": notice_c,
        "ctc": _eval_ctc(job, cand),
        "communication": _eval_comm(app),
    }
    total = low = high = 0.0
    positives, deductions, missing = [], [], []
    for key, c in crits.items():
        share = weights[key] / total_w * 100
        c["label"] = LABELS[key]
        c["weight"] = round(share, 1)
        c["points"] = round(share * c["score"], 1)
        total += share * c["score"]
        low += share * (c["score"] if c["known"] else 0.0)
        high += share * (c["score"] if c["known"] else 1.0)
        positives += c["positives"]
        deductions += c["deductions"]
        if not c["known"]:
            missing.append(f"{LABELS[key]}: {c['assessment']}")

    unknown_weight = sum(weights[k] for k, c in crits.items() if not c["known"]) / total_w
    confidence = "High" if unknown_weight <= 0.10 else "Medium" if unknown_weight <= 0.40 else "Low"

    flags = []
    if skill_detail["mandatory_missing"]:
        flags.append({"level": "error",
                      "text": "MISSING MANDATORY SKILLS: " + ", ".join(skill_detail["mandatory_missing"])})
    elif skill_detail["mandatory_unverified"]:
        flags.append({"level": "warning",
                      "text": "Mandatory skills not verified: no skills recorded for this candidate."})
    loc = crits["location"]
    if loc["known"] and loc["score"] <= 0.1:
        flags.append({"level": "warning", "text": "Location: " + loc["assessment"]})
    ctc = crits["ctc"]
    if ctc["known"] and ctc["score"] < 0.8:
        flags.append({"level": "warning", "text": "Over budget: " + ctc["assessment"]})
    exp = cand.get("relevant_exp") if cand.get("relevant_exp") is not None else cand.get("total_exp")
    if exp is not None:
        if job.get("exp_min") is not None and exp < job["exp_min"]:
            flags.append({"level": "warning",
                          "text": f"Experience {exp:g} yrs is below the required minimum of {job['exp_min']:g} yrs."})
        elif job.get("exp_max") is not None and exp > job["exp_max"]:
            flags.append({"level": "info",
                          "text": f"Experience {exp:g} yrs is above the stated range (max {job['exp_max']:g} yrs)."})

    gap = bool(skill_detail["mandatory_missing"])
    total = round(total, 1)
    if gap and total >= 60:
        label = "Review: mandatory skill gap"
    elif gap:
        label = "Weak: mandatory skill gap"
    elif total >= 75:
        label = "Strong match"
    elif total >= 60:
        label = "Good match"
    elif total >= 45:
        label = "Possible match"
    else:
        label = "Weak match"

    if confidence == "Low" and not gap:
        label = "Incomplete profile: needs more information"
    return {
        "total": total, "low": round(low, 1), "high": round(high, 1), "confidence": confidence,
        "criteria": crits, "skills": skill_detail, "flags": flags, "positives": positives,
        "deductions": deductions, "missing_info": missing, "has_mandatory_gap": gap,
        "label": label, "notice_days": notice_days, "weights": {k: round(v, 1) for k, v in weights.items()},
    }


def rank_results(items, strict=True):
    """items: list of (key, result, tiebreak_name). Candidates with all mandatory skills first when strict."""
    return sorted(items, key=lambda x: ((x[1]["has_mandatory_gap"] if strict else False), -x[1]["total"],
                                        str(x[2]).lower()))


def explanation_text(result: dict, name: str = "") -> str:
    """Plain-text explanation (used in exports)."""
    lines = [f"Candidate: {name}" if name else "Candidate",
             f"Score: {result['total']:.0f}/100 (range {result['low']:.0f}-{result['high']:.0f}, "
             f"confidence {result['confidence']}) - {result['label']}"]
    for f in result["flags"]:
        lines.append(f"[{f['level'].upper()}] {f['text']}")
    lines.append("Criteria:")
    for c in result["criteria"].values():
        est = "" if c["known"] else " (estimated: information missing)"
        lines.append(f"- {c['label']}: {c['points']:.1f}/{c['weight']:.1f}{est} - {c['assessment']}")
    if result["positives"]:
        lines.append("Positives: " + " ".join(result["positives"]))
    if result["deductions"]:
        lines.append("Deductions: " + " ".join(result["deductions"]))
    if result["missing_info"]:
        lines.append("Missing information: " + " | ".join(result["missing_info"]))
    return "\n".join(lines)
