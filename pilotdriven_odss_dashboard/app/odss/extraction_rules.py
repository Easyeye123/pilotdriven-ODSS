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

EXTRACTION_RULES = "2026-09-24-atc-radio-source-extraction-v2"
