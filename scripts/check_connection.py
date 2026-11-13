"""Check your database settings BEFORE deploying:

    DATABASE_URL="postgresql://..." python scripts/check_connection.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hiretrack import db as dbm  # noqa: E402

url = os.environ.get("DATABASE_URL")
if not url:
    sys.exit("Set DATABASE_URL first (see .streamlit/secrets.toml.example).")
d = dbm.Database(url=url)
d.init()
print("Connected and tables ready:", d.selftest())
print("Row counts:", d.table_counts())
