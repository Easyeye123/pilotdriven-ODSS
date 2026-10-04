"""A shallow checkout must skip the JS differential, never crash collecting it."""
from pathlib import Path

from tests.cross_runtime import js_derivation_module, sibling_app_root


def test_a_shallow_tree_has_no_sibling_app_root_instead_of_raising():
    # The ODSS container tests itself from /app/tests; resolving a sibling
    # worktree three levels up is impossible there and must not raise.
    assert sibling_app_root(Path("/app/tests/test_x.py")) is None


def test_a_deep_tree_still_offers_its_sibling_worktree():
    root = sibling_app_root(Path("/a/b/c/d/tests/test_x.py"))
    assert root is not None and root.name == "pd-09sep-fixes-20260915"


def test_a_shallow_tree_yields_no_module_so_the_caller_skips(monkeypatch):
    monkeypatch.delenv("PILOTDRIVEN_APP_ROOT", raising=False)
    assert js_derivation_module(Path("/app/tests/test_x.py")) is None
