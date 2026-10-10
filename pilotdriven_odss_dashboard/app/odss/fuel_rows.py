"""The page-1 contingency line, read and printed under the label the OFP gives it.

F13 of Codex's independent QA of release 472 (10 Oct 2026): LIDO prints the
contingency either as "STAT CONT" (statistical) or as a percentage of trip fuel
("3% CONT" on the genuine SQ314 SIN-LGW 15 Aug, which plans an ERA en-route
alternate). The row keeps its key ("stat_cont", the contingency line) and holds
its printed label; every surface prints that label and none relabels one form
as the other.
"""
from __future__ import annotations

from typing import Any

# "STAT CONT" or "<n>% CONT"; interior spacing varies like every page-1 label.
CONTINGENCY_LABEL = r"(?:STAT|\d{1,2}(?:\.\d)?%)\s+CONT"


def contingency_label(rows: dict[str, Any] | None) -> str:
    """The label to print for the contingency row.

    A row held before labels were kept was read only from "STAT CONT", so that
    is its printed label; with no contingency line read the neutral "CONT" is
    printed beside the not-held state, never a label the source did not print.
    """
    row = (rows or {}).get("stat_cont")
    if isinstance(row, dict):
        return str(row.get("label") or "STAT CONT")
    return "CONT"
