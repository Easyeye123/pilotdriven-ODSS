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
EXTRACTION_RULES = "2026-09-30-atc-source-coverage-v6"
