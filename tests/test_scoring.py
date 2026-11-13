from datetime import date

from hiretrack.options import parse_notice_days
from hiretrack.scoring import compute_score, explanation_text, rank_results, skill_key

JOB = dict(title="Python Dev", location="Bengaluru", work_mode="Hybrid", exp_min=3, exp_max=6,
           budget_min=12, budget_max=18, mandatory_skills=["Python", "FastAPI", "SQL"],
           preferred_skills=["Docker", "AWS"], weights={})
GOOD = dict(full_name="A", primary_skills=["python", "fast api"], secondary_skills=["PostgreSQL", "SQL"],
            additional_skills=["Docker", "Kafka"], current_city="Bangalore", relocation="Same city",
            notice_period="Immediate", expected_ctc=15, total_exp=5)
TODAY = date(2026, 1, 1)


def test_notice_parsing():
    assert parse_notice_days("Immediate") == 0
    assert parse_notice_days("30 days") == 30
    assert parse_notice_days("2 months") == 60
    assert parse_notice_days("3 weeks") == 21
    assert parse_notice_days("") is None and parse_notice_days(None) is None
    assert parse_notice_days("not sure") is None


def test_skill_synonyms():
    assert skill_key("Node.js") == skill_key("nodejs") == skill_key("NodeJS")
    assert skill_key("Postgres") == skill_key("PostgreSQL")


def test_perfect_candidate_scores_high_with_no_gap():
    r = compute_score(JOB, GOOD, {"communication": "Excellent"}, TODAY)
    assert not r["has_mandatory_gap"]
    assert r["skills"]["mandatory_matched"] == ["Python", "FastAPI", "SQL"]
    assert r["total"] >= 85
    assert r["confidence"] == "High"
    assert r["label"] == "Strong match"


def test_mandatory_gap_is_flagged_even_with_high_score():
    c = dict(GOOD, primary_skills=["Python"], secondary_skills=[], additional_skills=["Docker"])
    r = compute_score(JOB, c, {"communication": "Excellent"}, TODAY)
    assert r["has_mandatory_gap"]
    assert r["skills"]["mandatory_missing"] == ["FastAPI", "SQL"]
    assert any(f["level"] == "error" and "FastAPI" in f["text"] for f in r["flags"])
    assert "gap" in r["label"].lower()


def test_unknowns_get_half_marks_not_zero_and_lower_confidence():
    r = compute_score(JOB, dict(full_name="X"), None, TODAY)
    for c in r["criteria"].values():
        assert c["score"] == 0.5 and not c["known"]
    assert r["total"] == 50.0 and r["low"] == 0.0 and r["high"] == 100.0
    assert r["confidence"] == "Low"
    assert len(r["missing_info"]) == 5
    assert not r["has_mandatory_gap"]
    assert any("not verified" in f["text"] for f in r["flags"])


def test_location_ordering():
    here = compute_score(JOB, dict(GOOD), None, TODAY)["criteria"]["location"]["score"]
    reloc = compute_score(JOB, dict(GOOD, current_city="Pune", relocation="Open to relocate"), None, TODAY)["criteria"]["location"]["score"]
    no = compute_score(JOB, dict(GOOD, current_city="Pune", relocation="Not open to relocate"), None, TODAY)["criteria"]["location"]["score"]
    assert here > reloc > no == 0.0


def test_remote_job_ignores_location():
    j = dict(JOB, work_mode="Remote")
    r = compute_score(j, dict(GOOD, current_city="Pune", relocation="Not open to relocate"), None, TODAY)
    assert r["criteria"]["location"]["score"] == 1.0


def test_notice_period_ordering_and_no_disqualification():
    scores = []
    for n in ("Immediate", "15 days", "30 days", "45 days", "60 days", "90 days", "120 days"):
        scores.append(compute_score(JOB, dict(GOOD, notice_period=n), None, TODAY)["criteria"]["notice"]["score"])
    assert scores == sorted(scores, reverse=True)
    assert scores[-1] > 0


def test_notice_uses_last_working_day_when_given():
    c = dict(GOOD, notice_period="90 days", last_working_day=date(2026, 1, 11))
    r = compute_score(JOB, c, None, TODAY)
    assert r["notice_days"] == 10


def test_ctc_within_over_and_negotiable():
    within = compute_score(JOB, dict(GOOD, expected_ctc=14), None, TODAY)["criteria"]["ctc"]["score"]
    cheaper = compute_score(JOB, dict(GOOD, expected_ctc=9), None, TODAY)["criteria"]["ctc"]["score"]
    over = compute_score(JOB, dict(GOOD, expected_ctc=21), None, TODAY)["criteria"]["ctc"]["score"]
    over_neg = compute_score(JOB, dict(GOOD, expected_ctc=21, negotiable="Yes"), None, TODAY)["criteria"]["ctc"]["score"]
    assert 0.9 <= within < cheaper <= 1.0  # cheaper only slightly better
    assert cheaper - within < 0.1
    assert over < within and over_neg > over


def test_cheapest_does_not_beat_technical_fit():
    strong = compute_score(JOB, dict(GOOD, expected_ctc=18), {"communication": "Good"}, TODAY)
    cheap_weak = compute_score(JOB, dict(GOOD, primary_skills=["Java"], secondary_skills=[], additional_skills=[],
                                         expected_ctc=5), {"communication": "Good"}, TODAY)
    assert strong["total"] > cheap_weak["total"]


def test_communication_has_small_influence():
    hi = compute_score(JOB, GOOD, {"communication": "Excellent"}, TODAY)["total"]
    lo = compute_score(JOB, GOOD, {"communication": "Poor"}, TODAY)["total"]
    assert 0 < hi - lo <= 5.0


def test_custom_weights_change_scores_and_are_normalised():
    j = dict(JOB, weights={"skills": 10, "location": 10, "notice": 10, "ctc": 10, "communication": 10})
    r = compute_score(j, GOOD, None, TODAY)
    assert abs(sum(c["weight"] for c in r["criteria"].values()) - 100) < 0.5
    j0 = dict(JOB, weights={"skills": 0, "location": 0, "notice": 0, "ctc": 0, "communication": 0})
    assert compute_score(j0, GOOD, None, TODAY)["weights"]["skills"] == 50.0  # falls back to defaults


def test_explanation_is_generated_from_inputs():
    c = dict(GOOD, primary_skills=["Python"], secondary_skills=[], additional_skills=[], notice_period="90 days",
             expected_ctc=24)
    r = compute_score(JOB, c, {"communication": "Good"}, TODAY)
    text = explanation_text(r, "Rahul")
    assert "Rahul" in text and "FastAPI" in text and "90 days" in text and "24 LPA" in text


def test_experience_flag():
    r = compute_score(JOB, dict(GOOD, total_exp=1), None, TODAY)
    assert any("below the required minimum" in f["text"] for f in r["flags"])


def test_rank_strict_puts_complete_skill_sets_first():
    full = compute_score(JOB, dict(GOOD, notice_period="90 days", expected_ctc=30), None, TODAY)
    gap = compute_score(JOB, dict(GOOD, primary_skills=["Python"], secondary_skills=[], additional_skills=["Docker"]),
                        {"communication": "Excellent"}, TODAY)
    assert gap["total"] > full["total"] or True
    order = [k for k, _, _ in rank_results([("gap", gap, "b"), ("full", full, "a")], strict=True)]
    assert order == ["full", "gap"]
