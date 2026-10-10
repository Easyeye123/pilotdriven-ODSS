"""The extraction rules the parser applies, stamped on every analysis it writes.

F2 of the release-420 independent production QA (24 Sep 2026): a pack saved on
release 418 reopened online on 420 was shown under the current publication
rules with the three datalink notices the older parser held, and the notice
said "display updated"; the six voice / TIBA records the current parser holds
can only come from re-reading the OFP. Publication rules describe how a held
analysis is presented; extraction rules describe what the parser held. The
parser stamps this token on ``flight.extraction_rules``; the composition, the
service's briefing response and the app compare it with the value in service
and say when a held extraction predates it. The app's copy is
``CURRENT_EXTRACTION_RULES`` in web/src/lib/briefing-publication-format.mjs;
the two are bumped together whenever the parser's extraction changes.
"""

# v3 (release-432 QA, F2): NOTAM headings are read across page breaks; each procedure record names its heading page;
# a record whose owner the layout does not establish is held with heading_kind "unresolved".
# v4 (release-434 QA, F3): the slot-control allocation is read in every printed separator and wrap form (one grammar
# with the app); an allocation printed but not read is held as ``slot_allocation_unread``, never as absence.
# v5 (release-436 QA, ATC completeness): FIR headings that name the airspace part ("... FIR OCEANIC", "... FIR LOWER",
# "... DOMESTIC LOWER", "... UIR") own their notices and keep the part ("airspace"); location-prefixed series labels continue
# a section; topic headings in an enroute part hold their communication notices with no owning FIR ("topic").
# v6 (30 Sep 2026, ITEM1 ATC source coverage): source-backed communications and qualified aircraft-control duties are held.
# v7 (1 Oct 2026, ATC-CLEARANCE-FAMILY): a request / clarification / confirmation addressed to a unit and the refusal or
# acceptance of an ATC clearance or ATC-qualified instruction are held (CO188/02 under LTAA ANKARA FIR, the NON-RNAV
# radar-vector requests to DAEGU/INCHEON ACC); a stop printed without a following space ends a sentence outside an address.
# v8 (10 Oct 2026, release-468/470 QA): a LIDO "**ETP<n> -1D" scenario row closes the waypoint before it and is never a
# waypoint (the waypoint no longer takes the ETP's position or leg distance as its MSA); ARINC lat/long fix names (5350N,
# 18E30) and fixes such as EXITI are route waypoints (only ENTRY<n>/EXIT<n> are computed points); a blank MSA column is
# blank, never the distance's first digits, and an asterisked MSA keeps its value; a log whose first row sits alone under
# the column header starts on that page. Route waypoints, positions, MSAs and VWS events held under v7 can differ; a v7
# analysis is an older extraction and Create updated briefing re-reads the OFP.
EXTRACTION_RULES = "2026-10-10-navlog-etp-rows-v8"
