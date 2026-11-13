"""HireTrack entry point.  Run locally with:  streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="HireTrack", page_icon="🧭", layout="wide")

from hiretrack import auth, db as dbm, nav  # noqa: E402
from views import candidates, compare, data, home, jobs, screening, settings  # noqa: E402

ss = st.session_state

# 1. database (friendly error instead of a stack trace)
try:
    DB = dbm.get_db()
except Exception as exc:
    st.error("HireTrack could not connect to its database.")
    st.write("Most often this is a typo in the `DATABASE_URL` secret, a password with special characters that "
             "is not URL-encoded, or the Supabase project being paused. See the README, section "
             "“If something goes wrong”.")
    st.code(f"{exc.__class__.__name__}: {exc}")
    st.stop()

# 2. sign-in
auth.require_login(remote_db=not DB.sqlite)

# 3. pages
PAGE_DEFS = [
    ("home", home.render, "Home", "🏠"),
    ("jobs", jobs.render, "Jobs", "💼"),
    ("screening", screening.render, "Screening", "🎙️"),
    ("compare", compare.render, "Compare", "📊"),
    ("candidates", candidates.render, "Candidates", "👥"),
    ("data", data.render, "Data & Backup", "💾"),
    ("settings", settings.render, "Settings", "⚙️"),
]
for key, fn, title, icon in PAGE_DEFS:
    nav.PAGES[key] = st.Page(fn, title=title, icon=icon, url_path=key, default=(key == "home"))
pg = st.navigation(list(nav.PAGES.values()))

# 4. pending jumps requested by buttons on other pages
nav.apply_pending()

# 5. sidebar: which job am I working on?
all_jobs = [j for j in DB.rows("jobs", order="created_at DESC") if j["status"] != "Archived"]
job_ids = [j["id"] for j in all_jobs]
titles = {j["id"]: f"{j['title']}" + ("" if j["status"] == "Active" else f" ({j['status']})") for j in all_jobs}
if ss.get("sel_job_id") not in job_ids:
    ss.pop("sel_job_id", None)
st.sidebar.markdown("### 🧭 HireTrack")
if job_ids:
    st.sidebar.selectbox("Working on job", job_ids, format_func=titles.get, key="sel_job_id")
else:
    st.sidebar.caption("No jobs yet. Create one on the Jobs page.")
if DB.sqlite:
    st.sidebar.caption("Local mode: data saved on this computer.")
auth.logout_button()

pg.run()
