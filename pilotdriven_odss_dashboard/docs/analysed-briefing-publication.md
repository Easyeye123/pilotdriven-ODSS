# Analysed flight briefing publication

The default combined download follows the supplied SQ605 REV1 layout in nine landscape pages. `operational_format.py` measures card content at a fixed readable size and fails publication on overflow. It never truncates a source or creates continuation pages. Surface figures use validated supplied geometry; missing geometry stays missing.

`airport_pdf_analysis.py` projects the existing airport panels into bounded flight-time consequences. It uses each airport role separately, reuses the existing dated runway analysis and never promotes unresolved applicability or a component outage into an airport/approach closure. Original airport cards and Show full NOTAM remain in the app.

`concise_pdf_gate.py` checks the nine page owners, analysed lines and inline IDs, no raw Item E, no source attachment, no repeated per-item review label, and working internal links. The corpus runner also checks physical overlap and parsed input checksums. The app publication gate compares the same consequence/ID model while retaining full dashboard-source checks.

The explicit internal audit renderer remains for historical regression and the pinned REV3 raster contract; no service download requests its appendix. Historical drawing tests are in `test_reference_brief_composition.py`. Production format acceptance is in `test_combined_brief.py`; historical tests alone cannot certify a current download.

The v42 report cache revision invalidates older combined PDFs. A release must pass the guarded script and then fresh signed-in browser/download checks. Local fixtures and the private audit are not production proof.
