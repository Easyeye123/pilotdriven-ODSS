# Weather-page capacity repair

The release-522 renderer refused the retained 18 October SQ302 analysis with
`423pt of content in 421pt of page`, after exhausting all existing deferrals.
The full weather content missed the best fixed grid by 32.9pt. A neighbouring
column had spare space, but fixed column weights could not transfer it.

The shared planner now supports measured balancing of two adjacent text cards.
It measures both cards at each candidate width using their actual titles, tags,
paragraphs, fonts and leading, and retains the best measured result including
the original widths. It uses exactly those widths when drawing. The search is
a bounded improvement, not an exhaustive packing solver. Other row types keep
their declared geometry. Only the weather page opts in, after its existing
layouts have failed and before advancing to a content-deferral step.

This changes neither aviation decisions nor source text. The six-page format,
body/readability floor, margins, padding and capacity refusal stay in force.
There are no flight, airport or record-ID exceptions in production code.
Publication v114 invalidates server PDF caches and refreshes saved views; the
extraction and timing versions do not change.

## Regression evidence

`test_measured_column_widths.py` exercises asymmetric text, provenance tags,
both column orders, stable measurement/drawing, unchanged non-text rows, and
an unfit row that must still fail without truncation.

`test_saved_weather_layout_20261020.py` requires the immutable private input at
`private_cfp_corpus/saved-layout-inputs/SQ302-18OCT26-release522.json.gz`.
Its decompressed SHA-256 is
`abe84b632dc8fd78d0dffb1ca1d5ebfb674570ccc6160eefa3816bf2f787ba07`.
The test fails against release 522 and passes with this repair. It requires
every original weather paragraph on the physical PDF, no deferral step,
six readable pages, and the physical/PDF gates. Missing private input is an
explicit skip, never proof that this regression passed. Native release checks
must include it; cloud suites without that private archive report it separately.

Five existing long-TAF stress cases now retain the entire TAF; their assertions
were strengthened to require that. The larger 32-group case retains the prior
explicit whole-group deferral contract. This repair adds no content deferral.

The original source PDF is retained separately in the same private subfolder,
with SHA-256 `32864c3b57795527d96fa3fa1f573e6a6d682bba3d8f5fac72e961639f39e0c9`.
It is not added to the independently pinned extraction corpus implicitly.
Local and deployed acceptance receipts belong to the task output directory;
this note does not claim production deployment or live QA completion.
