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
# v9 (10 Oct 2026, release-472 QA, F13): the page-1 contingency line is read when printed as a percentage of trip fuel
# ("3% CONT", genuine SQ314 SIN-LGW 15 Aug) as well as "STAT CONT", and the row holds its printed label; a v8 analysis of
# such a plan holds no contingency and reports its fuel arithmetic unverified.
# v10 (12 Oct 2026, F30-OCR-1): one bounded image-rescaling retry can recover a
# printed weather-chart identity missing from the first OCR pass. Held v9
# analyses keep their original chart classifications until the source is
# re-read into a separate analysis. Corpus case records and digests are unchanged.
# v11 (14 Oct 2026, ITEM 3 Gatwick timing): a LIDO station record's VALID range and Item D are read by the rules the
# app reads them by (notam_timing_rules.json): Item D is the record's leading schedule lines joined (a D field wrapped
# over two lines is read whole; a bare "2130-0330", a day-number line or "DAILY SR-SS" is Item D, not free text read as
# no schedule); a schedule-like line inside the free text is a review, never a second schedule; an absent end is a
# review, never an open end. Notice records held under v10 can differ in schedule, schedule_review, validity_review and
# valid_to; a v10 analysis is an older extraction and Create updated briefing re-reads the OFP.
# v12 (15 Oct 2026, Codex QA of release 500): Item D is the whole leading run of schedule lines across line wraps and
# is accepted only when the grammar reads all of it; schedule language left in the free text must agree with it, and with
# no Item D any schedule hours in the free text are a review; every date is checked against the calendar. Notice records
# held under v11 can differ in schedule and schedule_review; a v11 analysis is an older extraction.
# v13 (15 Oct 2026, ALTERNATES-PARSE): the FLT PLANNING ALTN SUMMARY row reads APPROACH and MINIMA as optional columns,
# told apart by word shape, so a row printed with either blank is read and the blank stays blank; the EDTO ENROUTE ALTN
# AIRPORTS row takes its last word as the minima only when it is minima-shaped; a row printed in either table that is
# not read is held in alternates_unread. Analyses held under v12 can lack planned alternates (16 in 9 of the 30 held
# originals) and their station NOTAM and weather records; a v12 analysis is an older extraction.
# v14 (15 Oct 2026, release 502 + ALTERNATES-PARSE + QA502 integrated): v13's alternate rows, and one shared detector
# finds schedule-bearing language anywhere in a LIDO record's text; every statement must be accounted for or the record
# is held for timing review. Analyses held under v12 or v13 can lack planned alternates and their records, or differ in
# schedule_review; a v12 or v13 analysis is an older extraction.
# v15 (15 Oct 2026, release 506 + QA504 integrated, QA504-01): v14, and both alternate tables are read inside their
# printed bounds and every line in them is accounted - a row with an unreadable identity, runway or cell is held (by
# airport when readable), a row wrapped onto the next line is read whole, the two printings are reconciled and a
# route-line alternate with no row is held. Genuine holdings are unchanged; a v14 analysis of a damaged table can lack
# alternates without a review, so a v14 analysis is an older extraction.
# v16 (15 Oct 2026, QA504 integrated + QA506): v15's alternate tables, and every temporal token in a LIDO record's text,
# outside the stated benign classes, must sit in a statement read whole and proven equal on its own to Item D or the
# validity, else the record is held for timing review. Analyses held under v15 can differ in schedule_review (80 records
# in 28 of the 30 held originals); a v15 analysis is an older extraction.
# v17 (15 Oct 2026, QA508-01): v16, and an alternate table ends only at the next block's structure - a line that opens
# a row is a table line whatever its cells hold - so a lowercase, dotted or junk cell is read or held, never an end; a
# table with no identified end holds its remainder; EDTO printings are reconciled and an ETP-named EDTO alternate with
# no row is held by name. Genuine holdings are unchanged; a v16 analysis of a damaged table can lack the damaged row
# and the rows after it (EDTO with no review), so a v16 analysis is an older extraction.
# v18 (16 Oct 2026, QA510): v17, and the timing spec notam-timing-2026-10-16-v5 - a clock-like shape the grammar does
# not read (out of range, a letter for a digit, suffix letters, a dot, colon, space or H separator, a partial range)
# and a duration attached to the restriction (FOR, MAX, LAST, PERIOD OF, DURING) are temporal content and hold the
# record for timing review, where v17 read them as no schedule. Analyses held under v17 can differ in schedule_review
# (10 of the 2,989 unique records of the 30 held originals); a v17 analysis is an older extraction.
# v19 (16 Oct 2026, QA512-01/02, on v18): every numeric or coded table cell is checked against the shared table-cell
# rules (table_cell_rules.json) before its row is read: an invalid clock, runway, distance, level, wind component,
# time, fuel, minima or identifier holds the row naming the field; one row's failure holds that row; fuel-enroute
# station rows are held when they do not read. Genuine holdings are unchanged; a v18 analysis of a table with an
# invalid cell can hold an impossible value as read (or have failed), so a v18 analysis is an older extraction.
# v21 (17 Oct 2026, on v19: QA514 and QA516 integrated on release 516, each was its own v20). QA514: the timing spec
# notam-timing-2026-10-17-v7 - every digit left once the benign spans are masked (any Unicode decimal digit) must lie
# in a statement the grammar reads and accounts for, a benign mask is never the object of a temporal connective, an
# office's hours are benign only under a contact verb, genuine non-time numbers are benign by what governs them, and
# a time designator glued to a valid clock is a clock; held station records can differ in schedule_review. QA516-01:
# accounting is never truncated - the app parser holds every unread row, alternate, EDTO alternate, deferred item,
# remark, weather report (four originals lost 1-23 at the old cap of 64), SIGMET, terrain event and FIR crossing;
# destination rows are reconciled by slot; every weather/NOTAM block of a station is read; a table cell is ASCII in
# both runtimes. A v19 analysis is an older extraction.
# v22 (18 Oct 2026, on v21). QA518: the timing spec notam-timing-2026-10-18-v8 - every governance relation is read on
# the syntactic text (wrapping and joining punctuation removed by role; one clause boundary; a record's field and
# free text each one stream across line breaks), numeric content in words is numeric content, the object of a
# temporal connective in a restriction sentence is temporal content unless a role its connective admits classifies
# it, and every connective list names its same-role synonyms; held station records can differ in schedule_review.
# A v21 analysis is an older extraction.
# v23 (18 Oct 2026, on v22). QA520: the timing spec notam-timing-2026-10-18-v9 - a temporal connective's operand
# is classified token by token (I7: one unclassified, temporal or event token makes it temporal content; the head of
# a noun phrase by stated composition) and every connective is an obligation in one ledger checked once (I8: a
# missing, separated or cut-off operand is a review); held station records can differ in schedule_review. A v22
# analysis is an older extraction.
# v24: spatial metadata and independent-clause boundaries; timing spec v10. Re-mint derived corpus expectations.
EXTRACTION_RULES = "2026-10-18-operand-boundaries-v24"
