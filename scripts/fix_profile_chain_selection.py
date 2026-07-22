from pathlib import Path

path = Path("pilotdriven_odss_dashboard/app/odss/engines.py")
text = path.read_text(encoding="utf-8")
old = '''                    -(entry[1]["end_index"] - entry[1]["start_index"]),
                    str(entry[1]["profile"].get("chart") or ""),
'''
new = '''                    entry[1]["end_index"] - entry[1]["start_index"],
                    str(entry[1]["profile"].get("chart") or ""),
'''
if text.count(old) != 1:
    raise RuntimeError("profile selection tie-breaker anchor not found exactly once")
text = text.replace(old, new, 1)
old = '''    deduplicated: dict[tuple[int, str], dict[str, Any]] = {}
    for match in matches:
        key = (match["event"]["first_high"]["actm_minutes"], match["profile"]["chart"])
        deduplicated[key] = match
    return sorted(
        deduplicated.values(),
        key=lambda item: (
            item["event"]["first_high"]["actm_minutes"],
            item["start_index"],
        ),
    )
'''
new = '''    deduplicated: dict[tuple[str, int, int], dict[str, Any]] = {}
    for match in matches:
        key = (
            str(match["profile"]["chart"]),
            match["start_index"],
            match["end_index"],
        )
        current = deduplicated.get(key)
        if current is None or match["event"]["first_high"]["actm_minutes"] < current["event"]["first_high"]["actm_minutes"]:
            deduplicated[key] = match

    candidates = list(deduplicated.values())
    pruned = [
        candidate
        for candidate in candidates
        if not any(
            other is not candidate
            and other["start_index"] <= candidate["start_index"]
            and other["end_index"] >= candidate["end_index"]
            and (
                other["start_index"] < candidate["start_index"]
                or other["end_index"] > candidate["end_index"]
            )
            for other in candidates
        )
    ]
    return sorted(
        pruned,
        key=lambda item: (
            item["event"]["first_high"]["actm_minutes"],
            item["start_index"],
        ),
    )
'''
if text.count(old) != 1:
    raise RuntimeError("profile deduplication anchor not found exactly once")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
