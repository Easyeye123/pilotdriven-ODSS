# SQ214 REV3 exact visual regression gate

## What this checks

This gate answers one narrow question: does the candidate SQ214 combined Flight Briefing (all 41 pages, as produced by the private CFP corpus run) render to exactly the same pixels as the approved reference render?

The comparison uses the pinned PyMuPDF runtime from `pilotdriven_odss_dashboard/requirements.txt`. Every page is rendered at scale 1 into DeviceRGB with annotations enabled and no alpha channel. Page count, physical page size, raster size and every RGB pixel must match. There is no visual tolerance.

For example, if one card moves by one pixel on page 4, the command exits `1` and the JSON receipt records that page's changed-pixel ratio, mean absolute error, maximum channel delta and changed bounding box.

## Current approved reference

The pinned manifest (`tests/rev3_visual_reference_manifest.json`) is the
authority for the current reference — this section is prose and has gone
stale before (30 Aug: a deploy was attempted against v9 while the manifest
pinned v10).

`SQ214_REV3_reference_v12_APPROACH_EVIDENCE_CORRECTED.pdf`
(`8bf7b209…42e2`) — the SQ214-PER-SIN-19AUG corpus render under
`COMBINED_BRIEFING_SCHEMA_VERSION = "2026-08-31-surface-shortening-v32"`,
minted on 31 Aug 2026. It applies the independently reviewed positive-ownership
instrument-approach classifier: exact IAP/IAC, ILS/LOC/GP/DME, marker and
partial-category outages are critical, while approach-lighting-only notices do
not borrow an ILS outage. The 1,152-record replay produced only the three
intended lighting demotions. All 41 pages were inspected as a contact sheet,
with the changed airport-detail pages inspected at full size; there is no
clipping, overlap, blank-page, footer or source-retention regression.

Superseded without deployment:
`SQ214_REV3_reference_v11_CRITICAL_APPROACH_EVIDENCE.pdf`
(`4c679dfe…6027a`) — an intermediate candidate that incorrectly promoted the
WMKK sequence-flashing-light notice despite its explicit statement that the
approach lights remained available.

Superseded: `SQ214_REV3_reference_v10_VAA_SOURCE_SEPARATION.pdf`
(`1521203d…b57f`) — the render under
`COMBINED_BRIEFING_SCHEMA_VERSION = "2026-08-26-vaa-source-separation-v27"`,
minted on 26 Aug 2026. Relative to v9, page 37 intentionally separates the VA
SIGMET review from direct VAA source reach and applicability; the other 40
pages are pixel-identical to v9.

Superseded: `SQ214_REV3_reference_v9_OFP_VWS.pdf` (`4df2f631…4f78`) — the
render under
`COMBINED_BRIEFING_SCHEMA_VERSION = "2026-08-25-vws-fir-ofp-v26"`, minted on
25 Aug 2026. Relative to v8, generated product labels say OFP, exact printed
Lido `SUMMARY … CFP` headings remain identified as source text, and the
deterministic terrain summary always includes the VWS review. The corrected
render remains 41 pages with zero outside text boxes, visible overlaps, or
blank pages; all pages were inspected as a contact sheet and pages 1, 2, and
13 at full size. It supersedes v8 (`a4774fc0…970a`, ATOT/ETA parity), v7
(`dba0f288…d434e`, compact visible
`BACK TO OVERVIEW`), v6 (`4397ed3f…`, the flow-round reference), v5
(`73475f4c…`, the 20–21 Aug punch-list skin), and the original 7-page pypdf
REV3 artefact (`b02b0b36…`), which could never match the combined briefing the
release gate actually compares.

The deploy and release-gate scripts read the reference path from
`PILOTDRIVEN_REV3_REFERENCE_PDF`; the filename must equal the one pinned in the
manifest.

## Private asset strategy

The approved reference PDF is proprietary and must not be committed. Git contains only `pilotdriven_odss_dashboard/tests/rev3_visual_reference_manifest.json`, which pins:

- the approved reference filename and SHA-256;
- the PyMuPDF and MuPDF renderer versions;
- every page's geometry and raster dimensions;
- each approved page's raster SHA-256;
- zero-tolerance comparison thresholds; and
- the approval provenance (date, basis, combined-briefing schema version).

Keep the reference PDF in approved private storage or an ignored local path. Keep generated receipts and difference PNGs under the repository's ignored `tmp/` directory. Do not add the PDF or PNGs to Git.

The 41-page corpus artifact deliberately includes private lossless audit
appendices. Pages 3–8, 11–12, and 39–41 are not part of the seven-page
pilot-facing production download; they preserve the parsed-fact publication
coverage that the private corpus gate verifies.

## Run the gate

From `pilotdriven-ODSS`:

```bash
cd pilotdriven_odss_dashboard
python -m pip install -r requirements.txt
cd ..

export ODSS_REV3_VISUAL_REFERENCE_PDF=/secure/path/SQ214_REV3_reference_v9_OFP_VWS.pdf
export ODSS_REV3_VISUAL_CANDIDATE_PDF=/private/output/SQ214-PER-SIN-19AUG/SQ214-PER-SIN-19AUG_Flight_Briefing.pdf

python pilotdriven_odss_dashboard/scripts/check_rev3_visual_regression.py \
  --reference "$ODSS_REV3_VISUAL_REFERENCE_PDF" \
  --candidate "$ODSS_REV3_VISUAL_CANDIDATE_PDF" \
  --output tmp/rev3-visual-gate/receipt.json \
  --diff-dir tmp/rev3-visual-gate/diffs
```

Exit `0` means exact equality. Exit `1` means the reference preflight failed, the document structure changed, or at least one pixel differs. The receipt contains filenames and hashes, not absolute private paths.

The same check is available as an opt-in test:

```bash
ODSS_REV3_VISUAL_REFERENCE_PDF=/secure/path/SQ214_REV3_reference_v9_OFP_VWS.pdf \
ODSS_REV3_VISUAL_CANDIDATE_PDF=/private/output/SQ214-PER-SIN-19AUG/SQ214-PER-SIN-19AUG_Flight_Briefing.pdf \
python -m pytest -q pilotdriven_odss_dashboard/tests/test_rev3_visual_regression.py
```

Without those two environment variables, the proprietary case is skipped while the synthetic pass, mismatch, checksum, manifest and mint tests still run.

## Reference changes

Do not weaken thresholds or replace the pinned hashes to make a candidate pass. Every deliberate skin change (which also bumps `COMBINED_BRIEFING_SCHEMA_VERSION`) supersedes the reference; the procedure is:

1. Obtain approval for the new look (boss ruling or equivalent).
2. Render the SQ214 corpus case with the new code and visually inspect every page.
3. Copy that render to private storage under a new versioned filename.
4. Mint the manifest in a dedicated reviewed change:

```bash
python pilotdriven_odss_dashboard/scripts/mint_rev3_visual_reference.py \
  --reference /secure/path/SQ214_REV3_reference_v9.pdf \
  --approval-basis "who approved it, when, and why" \
  --combined-briefing-schema-version "<COMBINED_BRIEFING_SCHEMA_VERSION>"
```

   The mint script renders with the same contract as the gate, writes the manifest, reloads it and proves the gate accepts the reference against itself before exiting `0`.

5. Update the pinned filename, SHA-256 and page count in `tests/test_rev3_visual_regression.py::test_pinned_manifest_contains_only_the_private_asset_contract`.

A renderer-version mismatch is also a failed preflight; reinstall the pinned requirements instead of silently rebaselining.
