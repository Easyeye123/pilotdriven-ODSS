"""Synthetic refusal controls for the custom-component scan comparison."""
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


SPEC = spec_from_file_location("ocr_scan_image", Path(__file__).resolve().parents[1] / "ocr/scan_image.py")
SCAN = module_from_spec(SPEC)
SPEC.loader.exec_module(SCAN)


def reports():
    matches = [{"vulnerability": {"id": cve, "severity": "High"},
                "artifact": {"name": "tesseract", "version": "5.5.3"}}
               for cve in SCAN.LOCK["fixes"]]
    return ({"matches": [], "ignoredMatches": []},
            {"matches": matches, "ignoredMatches": []},
            {"matches": [], "ignoredMatches": deepcopy(matches)})


def test_exact_proven_component_disposition_preserves_every_raw_finding():
    assert SCAN.validate_findings(*reports(), set(SCAN.LOCK["fixes"])) == []


@pytest.mark.parametrize("case", ["new-high", "image-critical", "hidden-image", "missing-feed", "lost-finding", "other-package", "unresolved-fixed", "malformed"])
def test_uncertain_or_unresolved_security_results_block(case):
    image, raw, fixed = reports()
    finding = {"vulnerability": {"id": "CVE-SYNTHETIC-UNKNOWN", "severity": "High"},
               "artifact": {"name": "other", "version": "1"}}
    if case == "new-high":
        raw["matches"].append(finding)
        fixed["matches"].append(deepcopy(finding))
    elif case == "image-critical":
        finding["vulnerability"]["severity"] = "Critical"
        image["matches"].append(finding)
    elif case == "hidden-image":
        image["ignoredMatches"].append(finding)
    elif case == "missing-feed":
        raw["matches"].pop()
        fixed["ignoredMatches"].pop()
    elif case == "lost-finding":
        fixed["ignoredMatches"].pop()
    elif case == "other-package":
        fixed["ignoredMatches"][0]["artifact"]["name"] = "another-component"
    elif case == "unresolved-fixed":
        fixed["matches"].append(fixed["ignoredMatches"].pop())
    else:
        del image["matches"]
    assert SCAN.validate_findings(image, raw, fixed, set(SCAN.LOCK["fixes"]))
