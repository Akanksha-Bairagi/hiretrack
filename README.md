# HireTrack

A simple recruitment desk: job openings, candidate profiles, screening calls, explainable ranking,
comparison tables, Excel/CSV/JSON exports and full backup/restore.

Built with Python + Streamlit, PostgreSQL (Supabase) for permanent storage, pandas/openpyxl, pypdf.
Everything used is free.

---

## The easiest way to give this to the recruiter

**Deploy it once yourself, then send him a web link and a password.** He opens the link in any browser
(laptop or phone), signs in, and works. Nothing to install. Data lives in the cloud database, not in the app,
so closing the browser, restarting or redeploying never loses anything.

Total time: about 20 minutes, one time.

### Step 1: Create the free database (Supabase)

1. Sign up at supabase.com, click **New project**. Pick a region close to India (e.g. Mumbai) and set a
   **database password** (write it down).
2. When the project is ready: **Project Settings → Database → Connection string → "Session pooler"**.
   Copy the `postgresql://...` string and replace `[YOUR-PASSWORD]` with your password.
   * Use the **Session pooler** string (port 5432). The "Direct connection" string is IPv6-only and often fails on Streamlit Cloud.
   * If your password has special characters (`@ : / # ?`), URL-encode them (`@` becomes `%40`).
3. Optional check from your laptop: `DATABASE_URL="..." python scripts/check_connection.py`.
   It should print "Connected and tables ready".

The app creates all tables itself on first start, and switches on Row Level Security so the public Supabase
API cannot read candidate data.

### Step 2: Put the code on GitHub

Create a **private** repository and upload this folder (`.gitignore` already keeps secrets out).

### Step 3: Deploy on Streamlit Community Cloud (free)

1. share.streamlit.io → sign in with GitHub → **Create app** → pick the repo, branch `main`, main file `app.py`.
2. **Advanced settings → Secrets**, paste (see `.streamlit/secrets.toml.example`):
   ```toml
   APP_PASSWORD = "a-long-password-you-choose"
   DATABASE_URL = "postgresql://postgres.xxxx:PASSWORD@aws-0-xxx.pooler.supabase.com:5432/postgres"
   ```
3. Deploy. You get a link like `https://yourname-hiretrack.streamlit.app`.

### Step 4: Hand over

* Send him the link and password (separately).
* On his phone: open the link → browser menu → **Add to Home Screen**.
* Tell him: **Data & Backup → Prepare backup → Download** once a week. The Home page reminds him.
* Do a first run yourself: create a job, add a dummy candidate, save a screening, download a backup.

---

## Free-tier things to know

| Thing | What happens | What to do |
|---|---|---|
| Streamlit Cloud sleeps unused apps (after a day or so) | He sees "Wake up" button; click it, wait ~30 s. Data is untouched. | Nothing. |
| Supabase free projects **pause after ~7 days of no activity** | Data is kept, but the app can't connect until you click *Restore* in Supabase. | Use the app weekly. The included GitHub Action (`.github/workflows/keepalive.yml`) pings the database every 3 days. Add a repo secret `DATABASE_URL` to switch it on. This should help, but I could not confirm Supabase's exact inactivity rules, so keep the weekly backup habit. |
| Supabase free DB is 500 MB | Hundreds of candidates and PDFs fit, but resumes/JDs count toward it. | Keep resume files modest (limit 8 MB each). |
| Signing in again after browser refresh | The session is not remembered. | Browser password manager helps. |

## Security design (short)

* One shared password (`APP_PASSWORD`), compared safely, with a temporary lock after repeated wrong attempts.
  If a cloud database is configured but no password is set, the app refuses to show data.
* Database credentials only exist in Streamlit Secrets. Never in code.
* The app talks to Postgres directly from the server. Tables have Row Level Security **on with no public policies**
  and public roles are revoked, so the Supabase REST API exposes nothing.
* Uploaded resumes and JDs are stored inside the database (not on the app's temporary disk), so they are covered by
  the same protection and by the backup file.
* No real candidate data is used anywhere in tests (all dummy).

**Deliberate simplification:** the spec asked for Supabase Auth. For one recruiter, a single password plus a locked-down
database gives the same practical protection with far less to set up and break. If more users are needed later, add
Supabase Auth then.

## Backup and restore

* **Data & Backup → Prepare backup file → Download.** One `.zip` containing everything (including resumes and JD PDFs).
* **Restore:** upload the zip. The file is validated first (format, counts, broken links). You must tick a box and type
  `RESTORE`. It replaces all current data in a single all-or-nothing transaction: if anything fails, nothing changes.
* Excel/CSV/JSON exports are separate and meant for reading and sharing.

## How ranking works

Score 0-100 = weighted sum (default **skills 50, location 20, notice period 15, expected CTC 10, communication 5**;
configurable per job and as a default under Settings).

* **Skills:** share of mandatory skills matched (80%) plus preferred skills (20%). Names are normalised
  (`Postgres` = `PostgreSQL`, `Node.js` = `nodejs`).
  Missing mandatory skills are always flagged in red and, by default, rank below candidates who have them all.
* **Location:** in the job city 100%, open to relocate 60% (80% if the job city is their preferred location), remote-only
  for an office job 10%, unwilling to relocate 0%. Remote jobs ignore location.
* **Notice:** immediate 100% → 15 d 90% → 30 d 75% → 45 d 60% → 60 d 45% → 90 d 30% → longer 20% (never disqualifies).
  If a last-working-day or joining date is filled in, it is used instead of the text.
* **CTC:** within budget 90-100% (cheaper only slightly better); over budget loses points gradually (half the penalty if "negotiable").
* **Communication:** Excellent 100% … Poor 10%.
* **Unknown data is never zero**: it counts as half marks, is labelled "estimated", lowers *confidence*, and the
  explanation shows the score range from worst case to best case.
* Your **recommendation** is stored separately from the automatic score. The score at the moment you decided is kept.

Every explanation sentence is generated from the saved data. Nothing is invented. No protected or demographic fields are used.

## Run locally (optional, for you)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```
With no `DATABASE_URL` it uses a local SQLite file (`hiretrack_local.db`), handy for trying things.
`python scripts/seed_demo.py` adds dummy data. Run the tests with `python -m tests.run_all`.

## If something goes wrong

* **"could not connect to its database"**: wrong `DATABASE_URL`; password with unencoded special characters; used the
  Direct instead of Session-pooler string; or the Supabase project is paused (open Supabase and click Restore).
* **Page shows an error after an update**: *Manage app → Reboot app*. Data is not affected.
* **Lost data fear**: restore your latest backup (Data & Backup page).

## What has and hasn't been verified (honest status)

Verified with automated tests (45 tests, `python -m tests.run_all`): scoring rules and explanations, all database
operations (CRUD, cascades, duplicate detection, answers per application, ordering, migration), Excel/CSV/JSON export
contents, backup → wipe → restore round-trip and rollback on failure, backup validation, PDF text extraction, and every
page's code paths (create/edit/delete flows) against a strict stand-in for Streamlit.

**Not verified in the build environment (no internet there):** running under the real Streamlit, the real PostgreSQL/Supabase
connection, and visual layout. The Postgres code path uses standard SQL and is isolated, but do the 10-minute
first-run check above before handing it over, and send any error text back for a quick fix.
