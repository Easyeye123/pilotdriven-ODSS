# Historical saved-analysis regression inputs

`saved-analysis-v74-manifest.json` pins four actual archived SQ34 analyses whose
stored v74 briefing predates the composed volcanic check and coverage checklist.
Provider scenarios are identified individually, including the two simulated ones.
The full proprietary payloads stay outside git, alongside the private CFP corpus:

```
<PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR>/saved-analysis-v74/SQ34-<case id>.json.gz
```

Without that variable, the tests use the repository's sibling `private_cfp_corpus`
mount. Each gzip expands to the exact bytes of its `archive_source`, verified
against the committed SHA-256 before use. Never regenerate these inputs with the
current parser or change the hash to make a test pass. Missing, modified or corrupt
historical input fails the test. Keep the directory with the private corpus when
moving or backing up a release workspace.

The original test used an absolute path into one release-436 gate run. Its exact
SQ34 file (hash recorded in the manifest) was lost; these files are **not** that
file. They recover its regression coverage with four independently archived inputs
from the same v74 contract. Every original assertion is retained, plus an explicit
expected result for each provider condition, network blocking, input immutability,
and missing/modified-input failure checks.

Run `python -m pytest -q tests/test_volcanic_check_20260927.py` with the private
corpus mounted. No live provider access is needed.

The guarded release packages exactly the manifest's files into
`.private-build-inputs/saved-analysis-v74.tar` inside the encrypted private source
archive. This directory is excluded from Git and Docker COPY. CodeBuild supplies
the directory as the `saved_analyses` named build context. The pytest stage mounts
the tar read-only; a missing context or file stops the build. The tests read it via
`PILOTDRIVEN_SAVED_ANALYSIS_BUNDLE` without extraction. A checksum build argument
invalidates cached test results when bundle bytes change. All compressed and raw
fixture hashes are still checked. The runtime image receives neither this bundle
nor the full test tree; the build verifies the private input paths are absent.

Named contexts avoid BuildKit's per-secret size limit. The build makes this
private test input readable by its non-root test user; it is not a credential.
The payload remains in the private build context and is never a runtime layer.
