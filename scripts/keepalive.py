"""Tiny database ping used by the GitHub Action, so a free Supabase project is not paused for inactivity."""
import os
import sys

import psycopg2

url = os.environ.get("DATABASE_URL")
if not url:
    sys.exit("DATABASE_URL secret is not set")
conn = psycopg2.connect(url, connect_timeout=20)
cur = conn.cursor()
cur.execute("SELECT 1")
print("ok", cur.fetchone())
conn.close()
