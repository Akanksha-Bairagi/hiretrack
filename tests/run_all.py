"""Tiny test runner (works without pytest):  python -m tests.run_all"""
import importlib
import inspect
import sys
import traceback

MODULES = ["tests.test_scoring", "tests.test_db", "tests.test_pdf", "tests.test_ui_smoke"]
failed = passed = 0
for m in MODULES:
    mod = importlib.import_module(m)
    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        if name.startswith("test_"):
            try:
                fn()
                passed += 1
                print(f"PASS {m}.{name}")
            except Exception:
                failed += 1
                print(f"FAIL {m}.{name}")
                traceback.print_exc()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
