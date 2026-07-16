from __future__ import annotations

from typing import Any

PERSONAL_NOTE_PLACEMENT_LABELS: dict[str, str] = {
    "separate": "Separate personal-notes section",
    "departure": "Departure airport section",
    "destination": "Destination airport section",
    "communications": "Enroute ATC / communications section",
}

MAX_PERSONAL_NOTE_CHARS = 2_000


def validate_personal_note(
    placement: str,
    note_text: str,
    include_level1: bool,
    include_level2: bool,
) -> tuple[str, str, bool, bool]:
    normalized_placement = placement.strip().lower()
    if normalized_placement not in PERSONAL_NOTE_PLACEMENT_LABELS:
        raise ValueError("Select a valid personal-note placement")

    normalized_text = note_text.strip()
    if not normalized_text:
        raise ValueError("Personal note cannot be empty")
    if len(normalized_text) > MAX_PERSONAL_NOTE_CHARS:
        raise ValueError(
            f"Personal note cannot exceed {MAX_PERSONAL_NOTE_CHARS:,} characters"
        )
    if not include_level1 and not include_level2:
        raise ValueError("Select Level 1, Level 2, or both for the personal note")

    return normalized_placement, normalized_text, include_level1, include_level2


def serialise_personal_note(note: dict[str, Any]) -> dict[str, Any]:
    placement = str(note.get("placement") or "separate")
    return {
        "id": int(note["id"]) if note.get("id") is not None else None,
        "placement": placement,
        "placement_label": PERSONAL_NOTE_PLACEMENT_LABELS.get(
            placement,
            "Personal notes",
        ),
        "note_text": str(note.get("note_text") or "").strip(),
        "include_level1": bool(note.get("include_level1")),
        "include_level2": bool(note.get("include_level2")),
        "created_at": note.get("created_at"),
        "updated_at": note.get("updated_at"),
        "source": "pilot_personal_note",
    }
