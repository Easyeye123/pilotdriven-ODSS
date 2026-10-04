"""Locate the app's JS derivation for cross-runtime differentials.

The ODSS image builds and tests itself with no app checkout and no Node, at a
path too shallow for the sibling-worktree fallback. Resolving that fallback
eagerly crashed the container build with IndexError before the skip could run
(release-24, 18 Sep 2026), so resolution must fail to None and let the caller
skip.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

WORKTREE_NAME = "pd-09sep-fixes-20260915"
JS_MODULE = "web/src/lib/notam-restriction-line.mjs"


def sibling_app_root(start: Path, name: str = WORKTREE_NAME) -> Path | None:
    """The sibling app worktree, or None when this tree is not nested that deep."""
    parents = start.resolve().parents
    return parents[3] / name if len(parents) > 3 else None


def js_derivation_module(start: Path) -> Path | None:
    """The app's JS derivation module, or None when it or Node is unavailable."""
    configured = os.environ.get("PILOTDRIVEN_APP_ROOT")
    app_root = Path(configured) if configured else sibling_app_root(start)
    if app_root is None:
        return None
    module = app_root / JS_MODULE
    if not module.exists() or not shutil.which("node"):
        return None
    return module
