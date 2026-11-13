"""Database layer.

* Local / testing: SQLite file (no setup).
* Hosted: PostgreSQL (Supabase) when DATABASE_URL is configured.

Plain DB-API (sqlite3 / psycopg2) with `?` placeholders; no ORM. The schema is
described once in TABLES and the DDL is generated for each dialect.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone

from .config import get_setting

# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
# types: pk, pktext, int, float, text, bool, date, dt, jsonl (list), jsond (dict), blob
TABLES = {
    "jobs": {
        "cols": [
            ("id", "pk"), ("title", "text"), ("department", "text"), ("location", "text"),
            ("work_mode", "text"), ("exp_min", "float"), ("exp_max", "float"),
            ("budget_min", "float"), ("budget_max", "float"),
            ("mandatory_skills", "jsonl"), ("preferred_skills", "jsonl"),
            ("jd_text", "text"), ("status", "text"), ("weights", "jsond"),
            ("strict_mandatory", "bool"), ("created_at", "dt"), ("updated_at", "dt"),
        ],
    },
    "candidates": {
        "cols": [
            ("id", "pk"), ("full_name", "text"), ("email", "text"), ("phone", "text"),
            ("current_company", "text"), ("current_designation", "text"),
            ("total_exp", "float"), ("relevant_exp", "float"),
            ("primary_skills", "jsonl"), ("secondary_skills", "jsonl"), ("additional_skills", "jsonl"),
            ("project_experience", "text"), ("current_ctc", "float"), ("expected_ctc", "float"),
            ("negotiable", "text"), ("reason_for_switch", "text"), ("preferred_location", "text"),
            ("current_city", "text"), ("relocation", "text"), ("work_mode_pref", "text"),
            ("employment_status", "text"), ("notice_period", "text"), ("immediate_joiner", "text"),
            ("last_working_day", "date"), ("earliest_joining", "date"),
            ("archived", "bool"), ("created_at", "dt"), ("updated_at", "dt"),
        ],
    },
    "applications": {
        "cols": [
            ("id", "pk"), ("job_id", "int"), ("candidate_id", "int"), ("status", "text"),
            ("screening_status", "text"), ("communication", "text"), ("impression", "text"),
            ("recommendation", "text"), ("observations", "text"), ("score_at_decision", "float"),
            ("archived", "bool"), ("created_at", "dt"), ("updated_at", "dt"),
        ],
        "fks": {"job_id": "jobs", "candidate_id": "candidates"},
        "unique": [("job_id", "candidate_id")],
    },
    "screening_questions": {
        "cols": [
            ("id", "pk"), ("job_id", "int"), ("sort_order", "int"), ("question", "text"),
            ("answer_type", "text"), ("choices", "jsonl"), ("created_at", "dt"),
        ],
        "fks": {"job_id": "jobs"},
    },
    "screening_responses": {
        "cols": [
            ("id", "pk"), ("application_id", "int"), ("question_id", "int"),
            ("answer", "text"), ("updated_at", "dt"),
        ],
        "fks": {"application_id": "applications", "question_id": "screening_questions"},
        "unique": [("application_id", "question_id")],
    },
    "notes": {
        "cols": [
            ("id", "pk"), ("candidate_id", "int"), ("application_id", "int"), ("kind", "text"),
            ("body", "text"), ("created_at", "dt"), ("updated_at", "dt"),
        ],
        "fks": {"candidate_id": "candidates", "application_id": "applications"},
    },
    "files": {
        "cols": [
            ("id", "pk"), ("kind", "text"), ("candidate_id", "int"), ("job_id", "int"),
            ("filename", "text"), ("mime", "text"), ("size_bytes", "int"), ("data", "blob"),
            ("created_at", "dt"),
        ],
        "fks": {"candidate_id": "candidates", "job_id": "jobs"},
    },
    "options": {
        "cols": [("id", "pk"), ("category", "text"), ("label", "text")],
        "unique": [("category", "label")],
    },
    "app_settings": {"cols": [("name", "pktext"), ("val", "text")]},
}
ORDER = ["jobs", "candidates", "applications", "screening_questions", "screening_responses",
         "notes", "files", "options", "app_settings"]
COLTYPES = {t: dict(spec["cols"]) for t, spec in TABLES.items()}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_apps_job ON applications (job_id)",
    "CREATE INDEX IF NOT EXISTS idx_apps_cand ON applications (candidate_id)",
    "CREATE INDEX IF NOT EXISTS idx_resp_app ON screening_responses (application_id)",
    "CREATE INDEX IF NOT EXISTS idx_q_job ON screening_questions (job_id)",
    "CREATE INDEX IF NOT EXISTS idx_notes_cand ON notes (candidate_id)",
    "CREATE INDEX IF NOT EXISTS idx_files_cand ON files (candidate_id)",
    "CREATE INDEX IF NOT EXISTS idx_files_job ON files (job_id)",
]

TYPE_MAP = {
    "sqlite": {"pk": "INTEGER PRIMARY KEY AUTOINCREMENT", "pktext": "TEXT PRIMARY KEY", "int": "INTEGER",
               "float": "REAL", "text": "TEXT", "bool": "INTEGER", "date": "TEXT", "dt": "TEXT",
               "jsonl": "TEXT", "jsond": "TEXT", "blob": "BLOB"},
    "postgres": {"pk": "SERIAL PRIMARY KEY", "pktext": "TEXT PRIMARY KEY", "int": "INTEGER",
                 "float": "DOUBLE PRECISION", "text": "TEXT", "bool": "BOOLEAN", "date": "DATE",
                 "dt": "TIMESTAMP", "jsonl": "TEXT", "jsond": "TEXT", "blob": "BYTEA"},
}

DEFAULTS = {
    "jobs": {"status": "Active", "strict_mandatory": True, "mandatory_skills": [],
             "preferred_skills": [], "weights": {}},
    "candidates": {"archived": False, "primary_skills": [], "secondary_skills": [], "additional_skills": []},
    "applications": {"status": "Added", "screening_status": "Not started", "archived": False},
    "screening_questions": {"answer_type": "Text", "choices": []},
    "notes": {"kind": "general"},
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def norm_email(e):
    e = (e or "").strip().lower()
    return e or None


def norm_phone(p):
    digits = re.sub(r"\D", "", p or "")
    if len(digits) < 7:
        return None
    return digits[-10:]


# --------------------------------------------------------------------------
# Connection handling
# --------------------------------------------------------------------------
class _PGPool:
    """Tiny connection pool that re-validates connections that sat idle."""

    def __init__(self, dsn: str, size: int = 4):
        self.dsn, self.size, self.idle, self.lock = dsn, size, [], threading.Lock()

    def get(self):
        import psycopg2  # imported lazily so local/SQLite use needs no driver

        with self.lock:
            while self.idle:
                conn, last = self.idle.pop()
                if conn.closed:
                    continue
                if time.time() - last > 30:
                    try:
                        cur = conn.cursor()
                        cur.execute("SELECT 1")
                        cur.close()
                        conn.rollback()
                    except Exception:
                        try:
                            conn.close()
                        except Exception:
                            pass
                        continue
                return conn
        return psycopg2.connect(self.dsn, connect_timeout=15)

    def put(self, conn):
        if conn.closed:
            return
        with self.lock:
            if len(self.idle) < self.size:
                self.idle.append((conn, time.time()))
                return
        conn.close()


class _Tx:
    def __init__(self, db: "Database", raw):
        self.db, self.raw = db, raw

    def _sql(self, sql: str) -> str:
        return sql if self.db.sqlite else sql.replace("?", "%s")

    def all(self, sql, params=()):
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), tuple(params))
        if cur.description is None:
            cur.close()
            return []
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        return [dict(zip(cols, r)) for r in rows]

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def run(self, sql, params=()):
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), tuple(params))
        n = cur.rowcount
        cur.close()
        return n

    def insert(self, table, values: dict):
        cols = list(values)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        cur = self.raw.cursor()
        if self.db.sqlite:
            cur.execute(sql, tuple(values.values()))
            new_id = cur.lastrowid
        else:
            if "id" in COLTYPES[table]:
                sql += " RETURNING id"
            cur.execute(self._sql(sql), tuple(values.values()))
            new_id = cur.fetchone()[0] if "id" in COLTYPES[table] else None
        cur.close()
        return new_id


class Database:
    def __init__(self, url: str | None = None, path: str = "hiretrack.db"):
        self.url = url or None
        self.sqlite = not self.url
        self.path = path
        self.pool = _PGPool(self.url) if self.url else None
        self._ready = False
        self._lock = threading.Lock()

    # ---- transactions ----------------------------------------------------
    @contextmanager
    def tx(self):
        if self.sqlite:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.execute("PRAGMA foreign_keys = ON")
        else:
            conn = self.pool.get()
        t = _Tx(self, conn)
        try:
            yield t
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            if self.sqlite:
                conn.close()
            else:
                self.pool.put(conn)

    # ---- schema ----------------------------------------------------------
    def _ddl(self, name, spec):
        tm = TYPE_MAP["sqlite" if self.sqlite else "postgres"]
        fks = spec.get("fks", {})
        parts = []
        for col, typ in spec["cols"]:
            line = f"{col} {tm[typ]}"
            if col in fks:
                line += f" REFERENCES {fks[col]}(id) ON DELETE CASCADE"
            parts.append(line)
        for cols in spec.get("unique", []):
            parts.append(f"UNIQUE ({', '.join(cols)})")
        return f"CREATE TABLE IF NOT EXISTS {name} ({', '.join(parts)})"

    def ddl_preview(self) -> str:
        return ";\n".join(self._ddl(n, TABLES[n]) for n in ORDER) + ";"

    def init(self):
        """Create tables, add any missing columns, lock down the API. Safe to repeat."""
        with self._lock:
            if self._ready:
                return
            if self.sqlite:
                with self.tx() as t:
                    t.run("PRAGMA journal_mode = WAL")
            with self.tx() as t:
                for n in ORDER:
                    t.run(self._ddl(n, TABLES[n]))
                for stmt in INDEXES:
                    t.run(stmt)
            self._migrate()
            if not self.sqlite:
                self._lockdown()
            self._ready = True

    def _existing_columns(self, t, table):
        if self.sqlite:
            return {r["name"] for r in t.all(f"PRAGMA table_info({table})")}
        rows = t.all("SELECT column_name FROM information_schema.columns "
                     "WHERE table_schema = current_schema() AND table_name = ?", (table,))
        return {r["column_name"] for r in rows}

    def _migrate(self):
        """Additive migration: new columns added in later versions appear automatically."""
        tm = TYPE_MAP["sqlite" if self.sqlite else "postgres"]
        with self.tx() as t:
            for n in ORDER:
                have = self._existing_columns(t, n)
                for col, typ in TABLES[n]["cols"]:
                    if col not in have and typ not in ("pk", "pktext"):
                        t.run(f"ALTER TABLE {n} ADD COLUMN {col} {tm[typ]}")

    def _lockdown(self):
        """Supabase exposes tables over a public REST API. Turn on Row Level Security with
        no policies so that API (anon / authenticated roles) can read nothing. The app itself
        connects directly as the database owner, which is not affected by RLS."""
        stmts = [f"ALTER TABLE {n} ENABLE ROW LEVEL SECURITY" for n in ORDER]
        stmts += [f"REVOKE ALL ON TABLE {n} FROM anon, authenticated" for n in ORDER]
        stmts += ["REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated"]
        for s in stmts:
            try:
                with self.tx() as t:
                    t.run(s)
            except Exception:
                pass  # e.g. roles absent on a non-Supabase Postgres

    # ---- encoding / decoding --------------------------------------------
    def _enc(self, typ, v):
        if v is None:
            return None
        if typ in ("jsonl", "jsond"):
            return json.dumps(v, ensure_ascii=False)
        if typ in ("text", "pktext"):
            v = str(v)
            return v if v.strip() else None
        if typ == "bool":
            return bool(v)
        if typ in ("int", "pk"):
            return int(v)
        if typ == "float":
            f = float(v)
            return None if f != f else f
        if typ == "date":
            if isinstance(v, datetime):
                v = v.date()
            elif isinstance(v, str):
                v = date.fromisoformat(v[:10])
            return v.isoformat() if self.sqlite else v
        if typ == "dt":
            if isinstance(v, str):
                v = datetime.fromisoformat(v)
            return v.isoformat(sep=" ") if self.sqlite else v
        if typ == "blob":
            return bytes(v)
        return v

    @staticmethod
    def _dec(typ, v):
        if typ in ("jsonl", "jsond"):
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except ValueError:
                    return [] if typ == "jsonl" else {}
            return v if v else ([] if typ == "jsonl" else {})
        if v is None:
            return None
        if typ == "bool":
            return bool(v)
        if typ == "date":
            if isinstance(v, datetime):
                return v.date()
            return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
        if typ == "dt":
            return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
        if typ == "blob":
            return bytes(v)
        return v

    def _decode(self, table, row):
        types = COLTYPES[table]
        return {k: (self._dec(types[k], v) if k in types else v) for k, v in row.items()}

    def _prepare(self, table, values: dict, defaults: bool):
        types = COLTYPES[table]
        merged = {}
        if defaults:
            merged.update(DEFAULTS.get(table, {}))
        merged.update({k: v for k, v in values.items() if k in types and k != "id"})
        out = {k: self._enc(types[k], v) for k, v in merged.items()}
        return out

    # ---- generic CRUD ----------------------------------------------------
    def insert(self, table, values: dict) -> int:
        vals = self._prepare(table, values, defaults=True)
        now = self._enc("dt", utcnow())
        if "created_at" in COLTYPES[table] and "created_at" not in vals:
            vals["created_at"] = now
        if "updated_at" in COLTYPES[table] and "updated_at" not in vals:
            vals["updated_at"] = now
        with self.tx() as t:
            return t.insert(table, vals)

    def update(self, table, row_id: int, values: dict) -> None:
        vals = self._prepare(table, values, defaults=False)
        if "updated_at" in COLTYPES[table]:
            vals["updated_at"] = self._enc("dt", utcnow())
        if not vals:
            return
        sets = ", ".join(f"{k} = ?" for k in vals)
        with self.tx() as t:
            t.run(f"UPDATE {table} SET {sets} WHERE id = ?", (*vals.values(), row_id))

    def get(self, table, row_id):
        with self.tx() as t:
            r = t.one(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
        return self._decode(table, r) if r else None

    def rows(self, table, where="", params=(), order="id"):
        sql = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "") + (f" ORDER BY {order}" if order else "")
        with self.tx() as t:
            res = t.all(sql, params)
        return [self._decode(table, r) for r in res]

    def delete(self, table, row_id) -> None:
        with self.tx() as t:
            t.run(f"DELETE FROM {table} WHERE id = ?", (row_id,))

    def count(self, table, where="", params=()) -> int:
        with self.tx() as t:
            r = t.one(f"SELECT COUNT(*) AS n FROM {table}" + (f" WHERE {where}" if where else ""), params)
        return int(r["n"])

    def table_counts(self) -> dict:
        return {n: self.count(n) for n in ORDER}

    # ---- jobs ------------------------------------------------------------
    def job_stats(self) -> dict:
        """job_id -> {n_apps, n_done, n_reco} for non-archived applications."""
        sql = ("SELECT job_id, COUNT(*) AS n_apps, "
               "SUM(CASE WHEN screening_status = 'Completed' THEN 1 ELSE 0 END) AS n_done, "
               "SUM(CASE WHEN status IN ('Recommended','Shared with hiring manager','Selected') THEN 1 ELSE 0 END) AS n_reco "
               "FROM applications WHERE archived = ? GROUP BY job_id")
        with self.tx() as t:
            res = t.all(sql, (self._enc("bool", False),))
        return {r["job_id"]: {"n_apps": int(r["n_apps"]), "n_done": int(r["n_done"] or 0),
                              "n_reco": int(r["n_reco"] or 0)} for r in res}

    def job_impact(self, job_id) -> dict:
        with self.tx() as t:
            apps = t.one("SELECT COUNT(*) AS n FROM applications WHERE job_id = ?", (job_id,))["n"]
            resp = t.one("SELECT COUNT(*) AS n FROM screening_responses WHERE application_id IN "
                         "(SELECT id FROM applications WHERE job_id = ?)", (job_id,))["n"]
            notes = t.one("SELECT COUNT(*) AS n FROM notes WHERE application_id IN "
                          "(SELECT id FROM applications WHERE job_id = ?)", (job_id,))["n"]
            qs = t.one("SELECT COUNT(*) AS n FROM screening_questions WHERE job_id = ?", (job_id,))["n"]
        return {"applications": int(apps), "responses": int(resp), "notes": int(notes), "questions": int(qs)}

    def clone_job(self, job_id) -> int:
        job = self.get("jobs", job_id)
        data = {k: v for k, v in job.items() if k not in ("id", "created_at", "updated_at")}
        data["title"] = f"{job['title']} (copy)"
        data["status"] = "Active"
        new_id = self.insert("jobs", data)
        for q in self.questions(job_id):
            self.insert("screening_questions", {"job_id": new_id, "sort_order": q["sort_order"],
                                                "question": q["question"], "answer_type": q["answer_type"],
                                                "choices": q["choices"]})
        return new_id

    # ---- questions & responses ------------------------------------------
    def questions(self, job_id):
        return self.rows("screening_questions", "job_id = ?", (job_id,), order="sort_order, id")

    def add_question(self, job_id, text, answer_type="Text", choices=None) -> int:
        with self.tx() as t:
            r = t.one("SELECT MAX(sort_order) AS m FROM screening_questions WHERE job_id = ?", (job_id,))
        nxt = (r["m"] or 0) + 1
        return self.insert("screening_questions", {"job_id": job_id, "sort_order": nxt, "question": text,
                                                   "answer_type": answer_type, "choices": choices or []})

    def move_question(self, job_id, question_id, direction: int) -> None:
        qs = self.questions(job_id)
        ids = [q["id"] for q in qs]
        if question_id not in ids:
            return
        i = ids.index(question_id)
        j = i + direction
        if j < 0 or j >= len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        with self.tx() as t:
            for pos, qid in enumerate(ids, start=1):
                t.run("UPDATE screening_questions SET sort_order = ? WHERE id = ?", (pos, qid))

    def responses(self, application_id) -> dict:
        rows = self.rows("screening_responses", "application_id = ?", (application_id,))
        return {r["question_id"]: r["answer"] for r in rows}

    def save_responses(self, application_id, answers: dict) -> None:
        now = self._enc("dt", utcnow())
        with self.tx() as t:
            for qid, ans in answers.items():
                ans = self._enc("text", ans)
                if ans is None:
                    t.run("DELETE FROM screening_responses WHERE application_id = ? AND question_id = ?",
                          (application_id, qid))
                else:
                    t.run("INSERT INTO screening_responses (application_id, question_id, answer, updated_at) "
                          "VALUES (?, ?, ?, ?) ON CONFLICT (application_id, question_id) "
                          "DO UPDATE SET answer = excluded.answer, updated_at = excluded.updated_at",
                          (application_id, qid, ans, now))

    # ---- applications ----------------------------------------------------
    def job_pairs(self, job_id, include_archived=False):
        """[(application, candidate)] for a job."""
        where = "job_id = ?" + ("" if include_archived else " AND archived = ?")
        params = (job_id,) if include_archived else (job_id, self._enc("bool", False))
        apps = self.rows("applications", where, params)
        ids = sorted({a["candidate_id"] for a in apps})
        cands = {}
        if ids:
            ph = ", ".join("?" * len(ids))
            cands = {c["id"]: c for c in self.rows("candidates", f"id IN ({ph})", ids)}
        return [(a, cands[a["candidate_id"]]) for a in apps if a["candidate_id"] in cands]

    def candidate_apps(self, candidate_id):
        """[(application, job)] for a candidate."""
        apps = self.rows("applications", "candidate_id = ?", (candidate_id,))
        out = []
        for a in apps:
            j = self.get("jobs", a["job_id"])
            if j:
                out.append((a, j))
        return out

    def find_application(self, job_id, candidate_id):
        r = self.rows("applications", "job_id = ? AND candidate_id = ?", (job_id, candidate_id))
        return r[0] if r else None

    def add_application(self, job_id, candidate_id) -> int:
        existing = self.find_application(job_id, candidate_id)
        if existing:
            if existing["archived"]:
                self.update("applications", existing["id"], {"archived": False})
            return existing["id"]
        return self.insert("applications", {"job_id": job_id, "candidate_id": candidate_id})

    # ---- candidates ------------------------------------------------------
    def candidate_impact(self, candidate_id) -> dict:
        with self.tx() as t:
            apps = t.one("SELECT COUNT(*) AS n FROM applications WHERE candidate_id = ?", (candidate_id,))["n"]
            resp = t.one("SELECT COUNT(*) AS n FROM screening_responses WHERE application_id IN "
                         "(SELECT id FROM applications WHERE candidate_id = ?)", (candidate_id,))["n"]
            notes = t.one("SELECT COUNT(*) AS n FROM notes WHERE candidate_id = ?", (candidate_id,))["n"]
            files = t.one("SELECT COUNT(*) AS n FROM files WHERE candidate_id = ?", (candidate_id,))["n"]
        return {"applications": int(apps), "responses": int(resp), "notes": int(notes), "files": int(files)}

    def find_duplicates(self, email=None, phone=None, exclude_id=None):
        e, p = norm_email(email), norm_phone(phone)
        if not e and not p:
            return []
        hits = []
        for c in self.rows("candidates"):
            if exclude_id and c["id"] == exclude_id:
                continue
            by_email = e and norm_email(c["email"]) == e
            by_phone = p and norm_phone(c["phone"]) == p
            if by_email or by_phone:
                c = dict(c)
                c["match_on"] = " & ".join(x for x, ok in (("email", by_email), ("phone", by_phone)) if ok)
                hits.append(c)
        return hits

    def duplicate_groups(self):
        """Groups of existing candidates sharing an email or phone number."""
        cands = self.rows("candidates")
        groups = []
        for label, fn in (("email", norm_email), ("phone", norm_phone)):
            seen: dict = {}
            for c in cands:
                k = fn(c[label])
                if k:
                    seen.setdefault(k, []).append(c)
            groups += [(label, k, v) for k, v in seen.items() if len(v) > 1]
        return groups

    # ---- notes -----------------------------------------------------------
    def get_screening_note(self, application_id):
        r = self.rows("notes", "application_id = ? AND kind = 'screening'", (application_id,))
        return r[0] if r else None

    def save_screening_note(self, application_id, candidate_id, body) -> None:
        existing = self.get_screening_note(application_id)
        body = self._enc("text", body)
        if existing:
            if body is None:
                self.delete("notes", existing["id"])
            else:
                self.update("notes", existing["id"], {"body": body})
        elif body is not None:
            self.insert("notes", {"candidate_id": candidate_id, "application_id": application_id,
                                  "kind": "screening", "body": body})

    # ---- files (resumes, JD PDFs) ---------------------------------------
    def save_file(self, kind, filename, mime, data: bytes, candidate_id=None, job_id=None) -> int:
        owner_col, owner = ("candidate_id", candidate_id) if candidate_id else ("job_id", job_id)
        with self.tx() as t:
            t.run(f"DELETE FROM files WHERE kind = ? AND {owner_col} = ?", (kind, owner))
        return self.insert("files", {"kind": kind, owner_col: owner, "filename": filename, "mime": mime,
                                     "size_bytes": len(data), "data": data})

    def file_meta(self, kind, candidate_id=None, job_id=None):
        owner_col, owner = ("candidate_id", candidate_id) if candidate_id else ("job_id", job_id)
        with self.tx() as t:
            r = t.one(f"SELECT id, filename, mime, size_bytes, created_at FROM files "
                      f"WHERE kind = ? AND {owner_col} = ?", (kind, owner))
        return self._decode("files", r) if r else None

    def file_data(self, file_id):
        r = self.get("files", file_id)
        return r

    def delete_file(self, file_id):
        self.delete("files", file_id)

    # ---- dropdown options & settings ------------------------------------
    def custom_options(self) -> dict:
        out: dict = {}
        for r in self.rows("options", order="category, label"):
            out.setdefault(r["category"], []).append(r["label"])
        return out

    def add_option(self, category, label) -> None:
        label = (label or "").strip()
        if not label:
            return
        with self.tx() as t:
            t.run("INSERT INTO options (category, label) VALUES (?, ?) ON CONFLICT (category, label) DO NOTHING",
                  (category, label))

    def delete_option(self, category, label) -> None:
        with self.tx() as t:
            t.run("DELETE FROM options WHERE category = ? AND label = ?", (category, label))

    def get_setting(self, name, default=None):
        with self.tx() as t:
            r = t.one("SELECT val FROM app_settings WHERE name = ?", (name,))
        return r["val"] if r and r["val"] is not None else default

    def set_setting(self, name, value) -> None:
        with self.tx() as t:
            t.run("INSERT INTO app_settings (name, val) VALUES (?, ?) ON CONFLICT (name) "
                  "DO UPDATE SET val = excluded.val", (name, None if value is None else str(value)))

    # ---- health check ----------------------------------------------------
    def selftest(self) -> str:
        """Write, read back and delete a test value. Returns a short status string."""
        token = str(time.time())
        self.set_setting("_healthcheck", token)
        ok = self.get_setting("_healthcheck") == token
        with self.tx() as t:
            t.run("DELETE FROM app_settings WHERE name = ?", ("_healthcheck",))
        if not ok:
            raise RuntimeError("Database read-back failed")
        return "PostgreSQL (Supabase)" if not self.sqlite else f"SQLite file ({self.path})"

    # ---- backup helpers --------------------------------------------------
    def dump_table(self, table):
        if table == "files":
            sql = "SELECT id, kind, candidate_id, job_id, filename, mime, size_bytes, created_at FROM files ORDER BY id"
        elif table == "app_settings":
            sql = "SELECT * FROM app_settings ORDER BY name"
        else:
            sql = f"SELECT * FROM {table} ORDER BY id"
        with self.tx() as t:
            res = t.all(sql)
        return [self._decode(table, r) for r in res]

    def file_blobs(self):
        with self.tx() as t:
            ids = [r["id"] for r in t.all("SELECT id FROM files ORDER BY id")]
        for fid in ids:
            with self.tx() as t:
                r = t.one("SELECT id, filename, data FROM files WHERE id = ?", (fid,))
            if r:
                yield r["id"], r["filename"], bytes(r["data"])

    def replace_all(self, data: dict, blobs: dict) -> None:
        """Replace ALL data with a backup, in one transaction (all-or-nothing)."""
        with self.tx() as t:
            for n in reversed(ORDER):
                t.run(f"DELETE FROM {n}")
            for n in ORDER:
                types = COLTYPES[n]
                for row in data.get(n, []):
                    vals = {}
                    for col, typ in TABLES[n]["cols"]:
                        if n == "files" and col == "data":
                            vals[col] = blobs[row["id"]]
                        elif col in row:
                            vals[col] = self._enc(typ, row[col])
                    t.insert(n, vals)
            if not self.sqlite:
                for n in ORDER:
                    if "id" in types_of(n):
                        t.run(f"SELECT setval(pg_get_serial_sequence('{n}', 'id'), "
                              f"COALESCE((SELECT MAX(id) FROM {n}), 0) + 1, false)")


def types_of(table):
    return COLTYPES[table]


# --------------------------------------------------------------------------
# Process-wide singleton
# --------------------------------------------------------------------------
_DB: Database | None = None
_DB_LOCK = threading.Lock()


def get_db() -> Database:
    global _DB
    with _DB_LOCK:
        if _DB is None:
            url = get_setting("DATABASE_URL")
            path = get_setting("HIRETRACK_DB_PATH", os.path.join(os.getcwd(), "hiretrack_local.db"))
            _DB = Database(url=url, path=path)
        db = _DB
    db.init()
    return db


def set_db(db: Database | None) -> None:
    """For tests."""
    global _DB
    with _DB_LOCK:
        _DB = db
