from pathlib import Path


root = Path("pilotdriven_odss_dashboard")
tests_path = root / "tests/test_reporting_regressions.py"
tests = tests_path.read_text(encoding="utf-8")

old = (
    '    assert "PILOTDRIVEN" in first\n'
    '    assert "REVIEW REQUIRED" not in first\n'
)
new = (
    '    assert "PILOT" in first and "DRIVEN" in first\n'
    '    assert "REVIEW REQUIRED" not in first\n'
)

if old in tests:
    tests = tests.replace(old, new, 1)
elif new not in tests:
    raise RuntimeError("Level 1 two-colour brand assertion was not found")

tests_path.write_text(tests, encoding="utf-8")
