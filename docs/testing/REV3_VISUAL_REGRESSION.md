# SQ214 REV3 exact visual regression gate

## What this checks

This gate answers one narrow question: does the candidate seven-page SQ214 briefing render to exactly the same pixels as the approved REV3 reference?

The comparison uses the pinned PyMuPDF runtime from `pilotdriven_odss_dashboard/requirements.txt`. Every page is rendered at scale 1 into DeviceRGB with annotations enabled and no alpha channel. Page count, physical page size, raster size and every RGB pixel must match. There is no visual tolerance.

For example, if one card moves by one pixel on page 4, the command exits `1` and the JSON receipt records that page's changed-pixel ratio, mean absolute error, maximum channel delta and changed bounding box.

## Private asset strategy

The approved reference PDF is proprietary and must not be committed. Git contains only `pilotdriven_odss_dashboard/tests/rev3_visual_reference_manifest.json`, which pins:

- the approved reference filename and SHA-256;
- the PyMuPDF and MuPDF renderer versions;
- seven page geometries and raster dimensions;
- each approved page's raster SHA-256; and
- zero-tolerance comparison thresholds.

Keep the reference PDF in approved private storage or an ignored local path. Keep generated receipts and difference PNGs under the repository's ignored `tmp/` directory. Do not add the PDF or PNGs to Git.

## Run the gate

From `pilotdriven-ODSS`:

```bash
cd pilotdriven_odss_dashboard
python -m pip install -r requirements.txt
cd ..

export ODSS_REV3_VISUAL_REFERENCE_PDF=/secure/path/SQ214_REV3_reference.pdf
export ODSS_REV3_VISUAL_CANDIDATE_PDF=/private/output/SQ214-PER-SIN-19AUG_Flight_Briefing.pdf

python pilotdriven_odss_dashboard/scripts/check_rev3_visual_regression.py \
  --reference "$ODSS_REV3_VISUAL_REFERENCE_PDF" \
  --candidate "$ODSS_REV3_VISUAL_CANDIDATE_PDF" \
  --output tmp/rev3-visual-gate/receipt.json \
  --diff-dir tmp/rev3-visual-gate/diffs
```

Exit `0` means exact equality. Exit `1` means the reference preflight failed, the document structure changed, or at least one pixel differs. The receipt contains filenames and hashes, not absolute private paths.

The same check is available as an opt-in test:

```bash
ODSS_REV3_VISUAL_REFERENCE_PDF=/secure/path/SQ214_REV3_reference.pdf \
ODSS_REV3_VISUAL_CANDIDATE_PDF=/private/output/SQ214-PER-SIN-19AUG_Flight_Briefing.pdf \
python -m pytest -q pilotdriven_odss_dashboard/tests/test_rev3_visual_regression.py
```

Without those two environment variables, the proprietary case is skipped while the synthetic pass, mismatch, checksum and manifest tests still run.

## Reference changes

Do not weaken thresholds or replace the pinned hashes to make a candidate pass. If REV3 is deliberately superseded, first obtain approval for the new private reference, visually inspect every rendered page, then update the manifest in a dedicated reviewed change. A renderer-version mismatch is also a failed preflight; reinstall the pinned requirements instead of silently rebaselining.
