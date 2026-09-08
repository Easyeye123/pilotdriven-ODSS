# Analysed flight briefing publication

The default combined download follows the supplied SQ605 REV1 layout in nine landscape pages. `operational_format.py` measures card content at a fixed readable size and fails publication on overflow. It never truncates a source or creates continuation pages. Surface figures use validated supplied geometry; missing geometry stays missing.

`airport_pdf_analysis.py` projects the existing airport panels into bounded flight-time consequences. It uses each airport role separately, reuses the existing dated runway analysis and never promotes unresolved applicability or a component outage into an airport/approach closure. Original airport cards and Show full NOTAM remain in the app.

`concise_pdf_gate.py` checks the nine page owners, analysed lines and inline IDs, no raw Item E, no source attachment, no repeated per-item review label, and working internal links. The corpus runner also checks physical overlap and parsed input checksums. The app publication gate compares the same consequence/ID model while retaining full dashboard-source checks.

The explicit internal audit renderer remains for historical regression and the pinned REV3 raster contract; no service download requests its appendix. Historical drawing tests are in `test_reference_brief_composition.py`. Production format acceptance is in `test_combined_brief.py`; historical tests alone cannot certify a current download.

The v43 report cache revision invalidates older combined PDFs. A release must pass the guarded script and then fresh signed-in browser/download checks. Local fixtures and the private audit are not production proof.

`analysed_briefing_map.py` draws held CFP polygons, the existing matched live hazard areas (including polygon holes), OFP VWS events, and time-matched cyclone centres on the filed route. IDs join each marker to a readable key. A volcano point is never turned into an ash area. The map distinguishes passage validity and matched live route/time/level evidence; it does not infer weather clearance. The complete source level profile is printed, including a single-level profile. Passage screening uses entered ATOT where held and checks both ends of validity.

`analysed_briefing_content.py` publishes an existing cyclone centre-distance result only within this flight's time window. Without that evidence it names the missing flight-window coverage, rather than copying unrelated current movement. Deferred effects come from explicit typed source constraints, never the MEL number: for example, a requested dry-ice uplift becomes a catering action without inventing a quantity, MEL allowance or release decision. Unresolved technical effects remain named in the closing record. Closing actions are numbered and derived from unresolved source states, affected airports and route segments. Complete/non-applicable topics and zero-count boilerplate are omitted.

Publication checks also bind the level profile, cyclone consequence, hazard key and deferred consequences to their owning PDF pages. Section footers must name their section and unsupported replacement glyphs are rejected. These are additional gates; the airport analysis in the app and historical audit renderer remain intact.

The shared `deferred_pdf_analysis` model holds each consequence with its declared references, existing gate IDs and source-item indices. The app parity check requires that analysed line on page 8 and accounts for every source-bound gate. Distinct declarations may share an OFP source row, so their gate IDs remain separate. Original descriptions and remarks remain covered by the dashboard checks; they are not demanded back into the concise PDF.
