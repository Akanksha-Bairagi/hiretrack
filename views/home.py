from datetime import datetime

import pandas as pd
import streamlit as st

from hiretrack import db as dbm
from hiretrack import nav


def _days_since(iso):
    try:
        return (dbm.utcnow() - datetime.fromisoformat(iso)).days
    except Exception:
        return None


def render():
    d = dbm.get_db()
    st.title("🧭 HireTrack")
    st.caption("Keep every opening, candidate and screening call in one place.")

    jobs = d.rows("jobs", order="created_at DESC")
    stats = d.job_stats()
    active = [j for j in jobs if j["status"] == "Active"]
    pending = d.count("applications", "archived = ? AND screening_status != 'Completed'", (False,))
    reco = sum(s["n_reco"] for s in stats.values())
    m = st.columns(4)
    m[0].metric("Active jobs", len(active))
    m[1].metric("Candidates", d.count("candidates", "archived = ?", (False,)))
    m[2].metric("Screenings to do", pending)
    m[3].metric("Recommended", reco)

    last = d.get_setting("last_backup")
    days = _days_since(last) if last else None
    if d.count("candidates") > 0:
        if last is None:
            st.warning("💾 You have not downloaded a backup yet. Go to **Data & Backup** and download one. "
                       "It takes ten seconds and protects all your work.")
        elif days is not None and days >= 7:
            st.warning(f"💾 Your last backup was {days} days ago. A fresh one only takes ten seconds "
                       "(Data & Backup page).")

    if not jobs:
        st.info("👋 **Welcome!** Start by creating your first job opening.")
        st.button("➕ Create a job", on_click=nav.go, args=("jobs",), type="primary")
    else:
        st.subheader("Your jobs")
        df = pd.DataFrame([{
            "Job": j["title"], "Status": j["status"], "Location": j["location"],
            "Candidates": stats.get(j["id"], {}).get("n_apps", 0),
            "Screened": stats.get(j["id"], {}).get("n_done", 0),
            "Recommended": stats.get(j["id"], {}).get("n_reco", 0),
        } for j in jobs if j["status"] != "Archived"])
        st.dataframe(df, hide_index=True)
        a, b, c, e = st.columns(4)
        a.button("🎙️ Screen a candidate", on_click=nav.go, args=("screening",))
        b.button("📊 Compare candidates", on_click=nav.go, args=("compare",))
        c.button("👥 All candidates", on_click=nav.go, args=("candidates",))
        e.button("💼 Manage jobs", on_click=nav.go, args=("jobs",))

    with st.expander("❓ How to use HireTrack (5 steps)", expanded=not jobs):
        st.markdown(
            """
1. **Jobs** → create an opening. Upload the JD PDF, list the *mandatory* and *preferred* skills, set the city and budget.
2. **Jobs → Screening questions** → add the questions you ask on calls (you can re-order them).
3. **Screening** → pick the job, add or choose a candidate and fill the form while you talk.
   Press **Save draft** any time, **Save & mark completed** when done.
4. **Compare** → see every candidate for the job ranked. Click a row, then **ℹ️ Why this score?** to see the reasoning.
5. **Data & Backup** → download a backup now and then, and Excel sheets to share.

Nothing is mandatory except a candidate's name, so you can save half-finished profiles and complete them later.
"""
        )
