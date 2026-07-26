from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.odss_map_v06.config import MapSettings
from app.odss_map_v06.geojson import build_map_contract


def test_map_contract_preserves_two_edto_sectors_and_explicit_etps() -> None:
    flight = {
        "flight_number": "SQ23",
        "departure": "KJFK",
        "destination": "WSSS",
        "route_waypoints": [
            {"name": "KJFK", "latitude": 40.64, "longitude": -73.78, "actm_minutes": 0},
            {"name": "ENTRY1", "latitude": 49.0, "longitude": -60.0, "actm_minutes": 159},
            {"name": "EXIT1", "latitude": 52.0, "longitude": -30.0, "actm_minutes": 257},
            {"name": "ENTRY2", "latitude": 25.0, "longitude": 90.0, "actm_minutes": 913},
            {"name": "EXIT2", "latitude": 12.0, "longitude": 101.0, "actm_minutes": 942},
            {"name": "WSSS", "latitude": 1.36, "longitude": 103.99, "actm_minutes": 1050},
        ],
        "edto": {
            "sectors": [
                {
                    "number": 1,
                    "entry_actm_minutes": 159,
                    "exit_actm_minutes": 257,
                    "entry": {},
                    "exit": {},
                    "etp_actm_minutes": [198],
                    "etps": [
                        {
                            "label": "1E",
                            "actm_minutes": 198,
                            "latitude": 51.25,
                            "longitude": -45.5,
                            "airports": ["CYQX", "EINN"],
                        }
                    ],
                },
                {
                    "number": 2,
                    "entry_actm_minutes": 913,
                    "exit_actm_minutes": 942,
                    "entry": {},
                    "exit": {},
                    "etp_actm_minutes": [928],
                    "etps": [
                        {
                            "label": "2D",
                            "actm_minutes": 913,
                            "latitude": 25.0,
                            "longitude": 90.0,
                            "airports": ["VTSP", "WSSS"],
                        },
                        {
                            "label": "1D",
                            "actm_minutes": 913,
                            "latitude": 25.0,
                            "longitude": 90.0,
                            "airports": ["VTSP", "WSSS"],
                        }
                    ],
                },
            ]
        },
    }

    contract = build_map_contract(flight, [], MapSettings(provider="schematic"))
    markers = contract.markers_geojson["features"]
    roles = [feature["properties"]["role"] for feature in markers]

    assert roles.count("edto_entry") == 2
    assert roles.count("edto_exit") == 2
    assert roles.count("edto_etp") == 2
    assert contract.metadata["edto_sector_count"] == 2
    assert contract.metadata["edto_etp_marker_count"] == 2
    assert {
        feature["properties"]["name"]
        for feature in markers
        if feature["properties"]["role"] == "edto_etp"
    } == {"S1 ETP 1E", "S2 ETP 2D / 1D"}
    sector_two_etp = next(
        feature
        for feature in markers
        if feature["properties"]["name"] == "S2 ETP 2D / 1D"
    )
    assert sector_two_etp["geometry"]["coordinates"] == [90.0, 25.0]
    assert sector_two_etp["properties"]["etp_labels"] == ["2D", "1D"]
