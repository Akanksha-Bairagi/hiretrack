from datetime import datetime

import pandas as pd
import streamlit as st

from hiretrack import db as dbm
from hiretrack import exports, ui
from hiretrack.options import OPTION_TITLES  # noqa: F401

ss = st.session_state
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _mark_backup():
    dbm.get_db().set_setting("last_backup", dbm.utcnow().isoformat())


def _backup_section(d):
    st.subheader("1 · Full backup (recommended weekly)")
    st.write("One file with **everything**: jobs, candidates, applications, answers, notes, resumes and JD PDFs. "
             "Keep it somewhere safe (your computer, Google Drive, email to yourself). "
             "You can restore it here at any time.")
    last = d.get_setting("last_backup")
    st.caption(f"Last backup downloaded: {last.replace('T', ' ')} (UTC)" if last else "No backup downloaded yet.")
    if st.button("📦 Prepare backup file", key="prep_backup", type="primary"):
        with st.spinner("Collecting everything…"):
            ss["_backup_bytes"] = exports.backup_zip()
            ss["_backup_name"] = f"hiretrack_backup_{datetime.now().strftime('%Y-%m-%d_%H%M')}.zip"
    if ss.get("_backup_bytes"):
        st.download_button(f"⬇️ Download {ss['_backup_name']} ({len(ss['_backup_bytes']) // 1024} KB)",
                           ss["_backup_bytes"], file_name=ss["_backup_name"], mime="application/zip",
                           key="dl_backup", on_click=_mark_backup)
        st.caption("Click the download button, then check the file saved to your computer.")


def _export_section(d):
    st.subheader("2 · Excel / CSV / JSON exports")
    a, b, c = st.columns(3)
    a.download_button("⬇️ Everything (Excel)", exports.all_xlsx(), file_name="hiretrack_all_data.xlsx", mime=XLSX, key="dl_all_x")
    b.download_button("⬇️ Everything (CSV files, zipped)", exports.all_csv_zip(), file_name="hiretrack_all_csv.zip",
                      mime="application/zip", key="dl_all_c")
    c.download_button("⬇️ Everything (JSON)", exports.all_json(), file_name="hiretrack_all_data.json",
                      mime="application/json", key="dl_all_j")
    st.caption("Exports are for reading and sharing. To be able to restore your data, use the full backup above.")
    jobs = d.rows("jobs", order="title")
    if jobs:
        lookup = {j["id"]: j["title"] for j in jobs}
        jid = st.selectbox("Export one job (with candidates, comparison, screening answers)", list(lookup), index=None,
                           format_func=lookup.get, key="exp_job", placeholder="Pick a job…")
        if jid:
            x, y = st.columns(2)
            x.download_button("⬇️ Excel", exports.job_xlsx(jid), file_name=f"job_{exports.safe_name(lookup[jid])}.xlsx",
                              mime=XLSX, key="dl_job_x")
            y.download_button("⬇️ CSV", exports.job_csv(jid), file_name=f"job_{exports.safe_name(lookup[jid])}.csv",
                              mime="text/csv", key="dl_job_c")
    cands = d.rows("candidates", order="full_name")
    if cands:
        lookup = {c["id"]: c["full_name"] for c in cands}
        cid = st.selectbox("Export one candidate (profile, answers, notes)", list(lookup), index=None,
                           format_func=lookup.get, key="exp_cand", placeholder="Pick a candidate…")
        if cid:
            x, y = st.columns(2)
            x.download_button("⬇️ Excel", exports.candidate_xlsx(cid), file_name=f"candidate_{exports.safe_name(lookup[cid])}.xlsx",
                              mime=XLSX, key="dl_cand_x")
            y.download_button("⬇️ JSON", exports.candidate_json(cid), file_name=f"candidate_{exports.safe_name(lookup[cid])}.json",
                              mime="application/json", key="dl_cand_j")


def _restore_section(d):
    st.subheader("3 · Restore from a backup")
    up = st.file_uploader("Choose a HireTrack backup (.zip)", type=["zip"], key="restore_up")
    if up is None:
        return
    data, blobs, errors, warnings, summary = exports.validate_backup(up.getvalue())
    for e in errors:
        st.error(e)
    for w in warnings:
        st.warning(w)
    if data is None:
        st.error("This file cannot be restored, so nothing was changed.")
        return
    st.success(f"Backup looks valid. Created {str(summary['created_at']).replace('T', ' ')} (UTC).")
    now_counts, new_counts = d.table_counts(), summary["counts"]
    st.dataframe(pd.DataFrame([{"Item": k.replace("_", " ").title(), "In this backup": new_counts[k],
                                "Currently in the app": now_counts[k]} for k in dbm.ORDER if k != "app_settings"]),
                 hide_index=True)
    st.error("⚠️ Restoring REPLACES everything currently in HireTrack with the contents of this backup. "
             "Anything added after the backup was made will be lost.")
    ok = st.checkbox("I understand. I already downloaded a backup of the current data, or I do not need it.",
                     key="restore_ok")
    typed = st.text_input("Type RESTORE to continue", key="restore_type")
    if st.button("Restore this backup now", key="restore_go", disabled=not (ok and typed.strip() == "RESTORE")):
        try:
            exports.restore_backup(data, blobs)
        except Exception as exc:  # the database transaction rolls back automatically
            st.error(f"Restore failed and nothing was changed: {exc}")
            return
        ui.invalidate_options()
        for k in [k for k in ss.keys() if not str(k).startswith("_authed")]:
            del ss[k]
        ss["_flash"] = "Backup restored."
        st.rerun()


def _duplicates_section(d):
    st.subheader("4 · Possible duplicate candidates")
    groups = d.duplicate_groups()
    if not groups:
        st.success("No candidates share an email or phone number.")
        return
    st.warning(f"{len(groups)} group(s) of candidates share the same email or phone. Open them on the Candidates page "
               "and archive or delete the extra profile.")
    for label, key, members in groups:
        st.write(f"**Same {label}** ({key}): " + ", ".join(f"{m['full_name']} (id {m['id']})" for m in members))


def _health_section(d):
    st.subheader("5 · System check")
    if st.button("Run check", key="syscheck"):
        try:
            where = d.selftest()
            st.success(f"Database is working. Connected to: {where}. Test write and read succeeded.")
        except Exception as exc:
            st.error(f"Database problem: {exc}")
    st.caption("Counts: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in d.table_counts().items() if k != "app_settings"))


def render():
    d = dbm.get_db()
    st.title("💾 Data & Backup")
    msg = ss.pop("_flash", None)
    if msg:
        st.success(msg)
    if d.sqlite:
        st.warning("Running in local mode: data is stored in a file on this computer. For a hosted app, connect the "
                   "cloud database (see the README).")
    _backup_section(d)
    st.divider()
    _export_section(d)
    st.divider()
    _restore_section(d)
    st.divider()
    _duplicates_section(d)
    st.divider()
    _health_section(d)
