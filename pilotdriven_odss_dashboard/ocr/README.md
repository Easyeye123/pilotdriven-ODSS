# Pinned OCR component

ODSS uses Tesseract to read printed weather-chart headings. For example, a
WSSS briefing with arrival on 11 July 2026 at 10:30Z still requires the chart's
printed route, flight levels and UTC validity before classification. This
dependency build preserves that application behavior and its processing budget.

Ubuntu's [USN-8882-1](https://ubuntu.com/security/notices/USN-8882-1) provides the
Noble fix through Ubuntu Pro/ESM. There is no authorized subscription for this
deployment. `component.lock.json` therefore selects official upstream source
at `552771236b0d80cbdb0c7dd856120fa21a4672e5`, the immediate descendant of the
initial five-fix candidate. It also includes the empty-stack fix linked from
[CVE-2026-88054](https://ubuntu.com/security/CVE-2026-88054).

This is a PilotDriven-maintained build of upstream 5.5.3 plus an exact commit.
It is neither a released 5.5.4 nor an Ubuntu ESM package. The lock contains the
eight upstream fix URLs, archive digests, regression-source hashes, compiler
package versions, Ubuntu base digest and English model digest.

`build_component.py` validates those inputs, builds static libtesseract into
the executable and runs 26 upstream tests in each of two builds: release and
ASan/UBSan. These tests cover the eight model-loading advisories; they are a
bounded subset of the upstream suite. A failure prevents package creation.
The resulting `pilotdriven-tesseract` Debian package retains normal package
metadata, Ubuntu runtime-library dependencies and the upstream license.
Required provenance and verification files live in
`/usr/share/pilotdriven-tesseract`; the license is under `/usr/share/doc`.

Compilation defaults to two workers for small local builds. The Docker build
argument `OCR_BUILD_JOBS` sets CMake's worker budget for both builds; only whole
numbers from 1 through 8 are accepted. CodeBuild uses four workers on its
four-CPU Linux Medium builder so compilation leaves time for the full suite
and security scan. This setting changes concurrency only: source pins,
compiler flags, regression targets and sanitizer checks remain mandatory.

The image retains the complete ODSS pytest build stage, non-root runtime,
Playwright browser probe and a real OCR probe with AI disabled. The OCR probe
uses labelled synthetic printed/scanned inputs and fail-closed controls.
Private flight-corpus and dashboard/PDF checks remain separate release gates.

`scan_image.py` pins Syft and Grype releases and verifies their archive hashes.
It generates the full image SBOM plus an explicit upstream entry for the
statically linked component. It checks the complete image and the component
against a freshly updated vulnerability database (maximum age 48 hours).
Raw findings are retained. For the verified binary only, an OpenVEX `fixed`
document records the eight included upstream fixes. The scan comparison
requires coverage of every named advisory, preserves every raw finding and
refuses unknown HIGH/CRITICAL findings or unexpected filtering. See
[Grype's VEX behavior](https://oss.anchore.com/docs/guides/vulnerability/filter-results/).
This records proven fixes; it does not accept remaining risk. The independent
ECR gate still runs with an empty accepted-findings policy.

Build logs contain native command exits and a SHA-256 checked evidence archive.
The final image inventory binds the executable, model, compiler inputs and
regression receipts. A successful build is only candidate evidence. Deployment
also requires the exact source pair, existing release gates, independent
review and serving-image readback.

To update: choose an official immutable source, review its full change from
this pin, refresh all relevant fix/test hashes, rerun the component and image
checks, inspect every raw security finding, and repeat the product gates.
Reassess the standard Ubuntu package when a public fix or separately authorized
ESM entitlement becomes available. Missing pinned inputs should fail the build
and trigger this review rather than silently substitute a newer compiler.
