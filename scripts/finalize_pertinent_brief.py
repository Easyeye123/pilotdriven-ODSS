from pathlib import Path


path = Path("pilotdriven_odss_dashboard/app/odss/pertinent_brief.py")
text = path.read_text(encoding="utf-8")

old_lines = '''    edto_bobcat_lines = (
        _finding_lines(edto_bobcat, finding_limit=6, detail_limit=2)
        + edto_summary_lines
    )
    vaa_weather = grouped.get("vaa", []) + [
'''
new_lines = '''    edto_bobcat_lines = (
        _finding_lines(edto_bobcat, finding_limit=6, detail_limit=2)
        + edto_summary_lines
    )
    has_edto = bool(grouped.get("edto") or edto_summary_lines)
    has_bobcat = bool(grouped.get("bobcat"))
    edto_bobcat_title = (
        "EDTO / BOBCAT"
        if has_edto and has_bobcat
        else "EDTO"
        if has_edto
        else "BOBCAT"
    )
    vaa_weather = grouped.get("vaa", []) + [
'''
old_panel = '            {"title": "EDTO / BOBCAT", "lines": edto_bobcat_lines, "accent": _EDTO},\n'
new_panel = '            {"title": edto_bobcat_title, "lines": edto_bobcat_lines, "accent": _EDTO},\n'

if text.count(old_lines) != 1:
    raise RuntimeError("EDTO/BOBCAT title context was not found exactly once")
if text.count(old_panel) != 1:
    raise RuntimeError("EDTO/BOBCAT panel definition was not found exactly once")

text = text.replace(old_lines, new_lines, 1).replace(old_panel, new_panel, 1)
path.write_text(text, encoding="utf-8")
