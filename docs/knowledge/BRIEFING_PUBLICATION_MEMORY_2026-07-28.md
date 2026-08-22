# Briefing Publication Memory - 28 July 2026

This memory records the accepted Level 1 and Level 2 publication baseline and supersedes any earlier conflicting layout note.

- Authoritative sources, not AI wording, remain the operational authority.
- Level 1 stays at a maximum of three A4 landscape pages.
- Level 2 is the Operational Evidence Brief.
- Level 1 and Level 2 Page 1 headers include flight, route, month/year, aircraft type, registration, UTC schedule, block time and local times with UTC offsets.
- Aircraft type and registration remain visible on every page.
- Block time is scheduled arrival minus scheduled departure.
- Detailed table/card text is enlarged by 2 pt from the superseded compact baseline, with a 7 pt normal minimum.
- Table headings and body wording are vertically centred using actual cell bounds and font metrics.
- Rows are content-aware with balanced vertical padding; clipping, overflow, duplicate overlays and covered final rows are release failures.
- High Terrain Exposure means MSA strictly greater than `100*`. Exactly `100*` is the boundary and is not a qualifying event.
- Isolated high-MSA events remain separate after any waypoint at or below the threshold.
- Every source chip/link must resolve to the intended authoritative paragraph or page.

Detailed implementation is in [`../protocols/ODSS_BRIEFING_PUBLICATION_PROTOCOL_V1_2.md`](../protocols/ODSS_BRIEFING_PUBLICATION_PROTOCOL_V1_2.md).
