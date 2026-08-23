# SQ214 REV3 exact visual regression gate

## What this checks

This gate answers one narrow question: does the candidate SQ214 combined Flight Briefing (all 41 pages, as produced by the private CFP corpus run) render to exactly the same pixels as the approved reference render?

The comparison uses the pinned PyMuPDF runtime from `pilotdriven_odss_dashboard/requirements.txt`. Every page is rendered at scale 1 into DeviceRGB with annotations enabled and no alpha channel. Page count, physical page size, raster size and every RGB pixel must match. There is no visual tolerance.

For example, if one card moves by one pixel on page 4, the command exits `1` and the JSON receipt records that page's changed-pixel ratio, mean absolute error, maximum channel delta and changed bounding box.

## Current approved reference

`SQ214_REV3_reference_v5.pdf` — the SQ214-PER-SIN-19AUG corpus render under
`COMBINED_BRIEFING_SCHEMA_VERSION = "2026-08-21-sq910-round-v5"`, minted on
23 Aug 2026 after the boss's 20–21 Aug 2026 punch-list rulings (STATUS tab,
EDTO suppressed on non-EDTO flights, PRIORITY strip removed, DECISION ANALYSIS,
raw METAR/TAF cards, TANKER rows). It supersedes the original 7-page pypdf REV3
artefact (`b02b0b36…`), which could never match the 41-page combined briefing
the release gate actually compares.

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

## Run the gate

From `pilotdriven-ODSS`:

```bash
cd pilotdriven_odss_dashboard
python -m pip install -r requirements.txt
cd ..

export ODSS_REV3_VISUAL_REFERENCE_PDF=/secure/path/SQ214_REV3_reference_v5.pdf
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
ODSS_REV3_VISUAL_REFERENCE_PDF=/secure/path/SQ214_REV3_reference_v5.pdf \
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
  --reference /secure/path/SQ214_REV3_reference_v6.pdf \
  --approval-basis "who approved it, when, and why" \
  --combined-briefing-schema-version "<COMBINED_BRIEFING_SCHEMA_VERSION>"
```

   The mint script renders with the same contract as the gate, writes the manifest, reloads it and proves the gate accepts the reference against itself before exiting `0`.

5. Update the pinned filename, SHA-256 and page count in `tests/test_rev3_visual_regression.py::test_pinned_manifest_contains_only_the_private_asset_contract`.

A renderer-version mismatch is also a failed preflight; reinstall the pinned requirements instead of silently rebaselining.
