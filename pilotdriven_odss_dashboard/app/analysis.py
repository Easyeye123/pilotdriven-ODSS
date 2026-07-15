from __future__ import annotations

from pathlib import Path
import re

def infer_metadata(filename: str) -> dict[str, str]:
    stem = Path(filename).stem.upper()
    result = {
        "flight_number": "",
        "flight_date": "",
        "departure": "",
        "destination": "",
        "aircraft": "",
        "registration": "",
    }

    m = re.search(r"\b(SQ|SIA)[-_ ]?(\d{2,4})\b", stem)
    if m:
        result["flight_number"] = f"SQ{m.group(2)}"

    # Filename-only inference is deliberately conservative.
    return result

def run_placeholder_analysis(file_path: Path) -> dict:
    '''
    Temporary deterministic placeholder.
    Replace this with the ODSS parser and engine pipeline.
    '''
    return {
        "status": "Ready for ODSS engine",
        "file_size_bytes": file_path.stat().st_size,
        "modules": [
            "CFP Page 1",
            "MEL",
            "CDDL",
            "NOTAM",
            "Weather",
            "Performance",
            "BOBCAT",
            "EDTO",
            "Terrain / MSA",
            "VWS",
            "Early ATC calls",
            "Depressurisation profiles",
            "Report generation",
        ],
    }
