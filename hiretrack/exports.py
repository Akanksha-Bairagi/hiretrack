"""Excel / CSV / JSON exports and full backup + restore."""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date, datetime

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import db as dbm
from . import service
from .scoring import explanation_text

BACKUP_FORMAT = 1
APP_MARK = "HireTrack"


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s or "file").strip("_") or "file"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in [c for c in df.columns if str(c).startswith("_")]:
        df = df.drop(columns=c)
    return df


def to_xlsx(sheets: dict) -> bytes:
    """dict of sheet name -> DataFrame -> formatted .xlsx bytes."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        used = set()
        for name, df in sheets.items():
            nm = re.sub(r"[\[\]\*\?/\\:]", "-", name)[:31] or "Sheet"
            while nm in used:
                nm = nm[:28] + "_2"
            used.add(nm)
            df = _clean(df) if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
            if df.empty and len(df.columns) == 0:
                df = pd.DataFrame({"(no data)": []})
            df.to_excel(xw, sheet_name=nm, index=False)
            ws = xw.sheets[nm]
            ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1F4E79")
                cell.alignment = Alignment(wrap_text=True, vertical="center")
            for i, col in enumerate(df.columns, start=1):
                longest = max([len(str(col))] + [len(str(v)) for v in df[col].head(300).tolist()])
                ws.column_dimensions[get_column_letter(i)].width = min(max(12, longest + 2), 60)
            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
    return buf.getvalue()


def to_csv(df: pd.DataFrame) -> bytes:
    return _clean(df).to_csv(index=False).encode("utf-8-sig")  # BOM so Excel opens UTF-8 correctly


# ---- flattened tables -------------------------------------------------------
def all_frames() -> dict:
    d = dbm.get_db()
    jobs = {j["id"]: j for j in d.rows("jobs")}
    cands = {c["id"]: c for c in d.rows("candidates")}
    apps = d.rows("applications")
    qs = {q["id"]: q for q in d.rows("screening_questions")}
    app_by_id = {a["id"]: a for a in apps}

    jobs_df = pd.DataFrame([{**{k: service.join_list(v) if isinstance(v, list) else v for k, v in j.items()
                                if k != "weights"}, "weights": json.dumps(j["weights"])} for j in jobs.values()])
    cands_df = service.candidate_frame(cands.values())
    apps_df = pd.DataFrame([{
        "application_id": a["id"], "job": jobs.get(a["job_id"], {}).get("title"),
        "candidate": cands.get(a["candidate_id"], {}).get("full_name"), "status": a["status"],
        "screening_status": a["screening_status"], "communication": a["communication"],
        "impression": a["impression"], "recommendation": a["recommendation"],
        "observations": a["observations"], "score_when_recommendation_set": a["score_at_decision"],
        "archived": a["archived"], "created_at": a["created_at"], "updated_at": a["updated_at"],
    } for a in apps])
    resp_df = pd.DataFrame([{
        "job": jobs.get(app_by_id[r["application_id"]]["job_id"], {}).get("title"),
        "candidate": cands.get(app_by_id[r["application_id"]]["candidate_id"], {}).get("full_name"),
        "question": qs.get(r["question_id"], {}).get("question"), "answer": r["answer"],
    } for r in d.rows("screening_responses") if r["application_id"] in app_by_id])
    notes_df = pd.DataFrame([{
        "candidate": cands.get(n["candidate_id"], {}).get("full_name"),
        "job": jobs.get(app_by_id[n["application_id"]]["job_id"], {}).get("title") if n["application_id"] in app_by_id else None,
        "type": n["kind"], "note": n["body"], "created_at": n["created_at"], "updated_at": n["updated_at"],
    } for n in d.rows("notes")])
    return {"Candidates": cands_df, "Jobs": jobs_df, "Applications": apps_df,
            "Screening answers": resp_df, "Notes": notes_df}


def all_xlsx() -> bytes:
    return to_xlsx(all_frames())


def all_csv_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in all_frames().items():
            z.writestr(f"{safe_name(name)}.csv", to_csv(df))
    return buf.getvalue()


# ---- single candidate ----------------------------------------------------------
def candidate_bundle(candidate_id: int) -> dict:
    d = dbm.get_db()
    c = d.get("candidates", candidate_id)
    if not c:
        raise ValueError("Candidate not found")
    apps = d.candidate_apps(candidate_id)
    app_rows, resp_rows, scores = [], [], []
    for a, j in apps:
        res = service.compute_score(j, c, a)
        app_rows.append({"job": j["title"], "status": a["status"], "screening_status": a["screening_status"],
                         "communication": a["communication"], "impression": a["impression"],
                         "recruiter_recommendation": a["recommendation"], "auto_score": res["total"],
                         "auto_assessment": res["label"], "observations": a["observations"]})
        qs = {q["id"]: q for q in d.questions(j["id"])}
        for qid, ans in d.responses(a["id"]).items():
            resp_rows.append({"job": j["title"], "question": qs.get(qid, {}).get("question"), "answer": ans})
        scores.append({"job": j["title"], "explanation": explanation_text(res, c["full_name"])})
    notes = [{"job": None, "type": n["kind"], "note": n["body"], "updated_at": n["updated_at"]}
             for n in d.rows("notes", "candidate_id = ?", (candidate_id,))]
    return {"candidate": c, "applications": app_rows, "responses": resp_rows, "notes": notes, "scores": scores}


def candidate_xlsx(candidate_id: int) -> bytes:
    b = candidate_bundle(candidate_id)
    prof = pd.DataFrame([(k.replace("_", " ").title(), service.join_list(v) if isinstance(v, list) else v)
                         for k, v in b["candidate"].items()], columns=["Field", "Value"])
    return to_xlsx({"Profile": prof, "Applications": pd.DataFrame(b["applications"]),
                    "Screening answers": pd.DataFrame(b["responses"]), "Notes": pd.DataFrame(b["notes"]),
                    "Ranking explanation": pd.DataFrame(b["scores"])})


def candidate_json(candidate_id: int) -> bytes:
    return json.dumps(candidate_bundle(candidate_id), indent=2, default=_json_default, ensure_ascii=False).encode()


# ---- single job --------------------------------------------------------------------
def job_xlsx(job_id: int) -> bytes:
    job, rows = service.build_comparison(job_id, include_archived=True)
    comp = service.comparison_frame(rows)
    expl = pd.DataFrame([{"Rank": r["rank"], "Candidate": r["cand"]["full_name"], "Score": r["score"]["total"],
                          "Explanation": explanation_text(r["score"], r["cand"]["full_name"])} for r in rows])
    info = pd.DataFrame([(k.replace("_", " ").title(), service.join_list(v) if isinstance(v, list) else str(v))
                         for k, v in job.items() if k != "jd_text"], columns=["Field", "Value"])
    sheets = {"Comparison": comp, "Screening answers": service.screening_matrix(job_id, rows),
              "Ranking explanation": expl, "Job details": info}
    return to_xlsx(sheets)


def job_csv(job_id: int) -> bytes:
    _, rows = service.build_comparison(job_id, include_archived=True)
    return to_csv(service.comparison_frame(rows))


# ---- backup / restore ---------------------------------------------------------
def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, (bytes, bytearray)):
        raise TypeError("binary data must not be placed in JSON")
    raise TypeError(f"Cannot serialise {type(o)}")


def backup_zip() -> bytes:
    d = dbm.get_db()
    tables = {n: d.dump_table(n) for n in dbm.ORDER}
    meta = {"app": APP_MARK, "format_version": BACKUP_FORMAT, "created_at": dbm.utcnow().isoformat(),
            "counts": {n: len(r) for n, r in tables.items()}, "tables": tables}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("backup.json", json.dumps(meta, default=_json_default, ensure_ascii=False, indent=1))
        for fid, fname, data in d.file_blobs():
            z.writestr(f"files/{fid}", data)
    return buf.getvalue()


def validate_backup(raw: bytes):
    """Returns (data_or_None, blobs, errors, warnings, summary). Nothing is written."""
    errors, warnings = [], []
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return None, {}, ["This is not a HireTrack backup (not a valid .zip file)."], [], {}
    if z.testzip() is not None:
        return None, {}, ["The backup file is damaged (zip integrity check failed)."], [], {}
    if "backup.json" not in z.namelist():
        return None, {}, ["backup.json is missing - this is not a HireTrack backup."], [], {}
    try:
        meta = json.loads(z.read("backup.json").decode("utf-8"))
    except ValueError:
        return None, {}, ["backup.json could not be read (invalid JSON)."], [], {}
    if meta.get("app") != APP_MARK:
        errors.append("This file was not created by HireTrack.")
    if meta.get("format_version", 0) > BACKUP_FORMAT:
        errors.append("This backup was made by a newer version of HireTrack. Update the app first.")
    tables = meta.get("tables")
    if not isinstance(tables, dict):
        return None, {}, errors + ["The backup has no data section."], warnings, {}
    data = {}
    for n in dbm.ORDER:
        rows = tables.get(n)
        if rows is None:
            if n in ("jobs", "candidates", "applications"):
                errors.append(f"Table '{n}' is missing from the backup.")
            rows = []
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            errors.append(f"Table '{n}' is malformed.")
            rows = []
        known = set(dbm.COLTYPES[n])
        extra = {k for r in rows for k in r} - known
        if extra:
            warnings.append(f"Table '{n}': ignoring unknown columns {sorted(extra)}.")
        data[n] = rows
        if n != "app_settings":
            ids = [r.get("id") for r in rows]
            if any(not isinstance(i, int) for i in ids) or len(ids) != len(set(ids)):
                errors.append(f"Table '{n}' has missing or duplicate ids.")
    ids = {n: {r.get("id") for r in data[n]} for n in dbm.ORDER if n != "app_settings"}
    for n, spec in dbm.TABLES.items():
        for col, parent in spec.get("fks", {}).items():
            bad = [r for r in data[n] if r.get(col) is not None and r.get(col) not in ids[parent]]
            if bad:
                errors.append(f"{len(bad)} row(s) in '{n}' point to a missing {parent} record (column {col}).")
    blobs = {}
    for r in data["files"]:
        name = f"files/{r.get('id')}"
        if name in z.namelist():
            blobs[r["id"]] = z.read(name)
        else:
            errors.append(f"Attached file '{r.get('filename')}' is missing from the backup.")
    for n, cnt in (meta.get("counts") or {}).items():
        if n in data and cnt != len(data[n]):
            errors.append(f"Table '{n}' should hold {cnt} rows but has {len(data[n])}.")
    summary = {"created_at": meta.get("created_at"), "counts": {n: len(data[n]) for n in dbm.ORDER}}
    return (data if not errors else None), blobs, errors, warnings, summary


def restore_backup(data: dict, blobs: dict) -> None:
    dbm.get_db().replace_all(data, blobs)


def all_json() -> bytes:
    """Readable JSON of every table (attached files excluded; use the backup zip for those)."""
    d = dbm.get_db()
    meta = {"app": APP_MARK, "exported_at": dbm.utcnow().isoformat(),
            "tables": {n: d.dump_table(n) for n in dbm.ORDER}}
    return json.dumps(meta, indent=1, default=_json_default, ensure_ascii=False).encode("utf-8")
