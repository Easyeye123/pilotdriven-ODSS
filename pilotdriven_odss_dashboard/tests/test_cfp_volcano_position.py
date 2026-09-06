import pytest

from app.odss.enrichment import _cfp_volcano_position
from app.odss_map_v06.config import MapSettings
from app.odss_map_v06.geojson import build_map_contract


@pytest.mark.parametrize("name,text,expected", [
    ("MAYON", "MAYON VOLCANO (1315N 12341E)", (13.25, 123 + 41/60)),
    ("KANLAON", "ERUPTION OF VOLCANO KANLAON (CAVW 0702-02) 1024N 12307E PHILIPPINES", (10.4, 123 + 7/60)),
    ("EXAMPLE", "EXAMPLE (1230S 17930W)", (-12.5, -179.5)),
    ("KRAKATAU", "VOLCANO: KRAKATAU 262000 PSN: S0606 E10525", (-6.1, 105 + 25/60)),
    ("KRAKATAU", "C)KRAKATAU 602-00 D)S0606E10525 E)ORANGE", (-6.1, 105 + 25/60)),
    ("KRAKATAU", "VA ERUPTION MT KRAKATAU PSN S0606 E10525", (-6.1, 105 + 25/60)),
    ("SEMERU", "C)SEMERU 603-30 D)S0806E11255 E)ORANGE", (-8.1, 112 + 55/60)),
    ("STROMBOLI", "VOLCANO STROMBOLI ID 211040, PSN COORDINATES 384728N0151246E", (38 + 47/60 + 28/3600, 15 + 12/60 + 46/3600)),
    ("EXAMPLE", "VOLCANO: EXAMPLE 123456 PSN: S123000 W1793000", (-12.5, -179.5)),
])
def test_position_belongs_to_named_source_volcano(name, text, expected):
    position = _cfp_volcano_position(text, name)
    assert position["latitude"] == pytest.approx(expected[0])
    assert position["longitude"] == pytest.approx(expected[1])
    assert position["source"] == "ofp_printed_position"


@pytest.mark.parametrize("text", [
    "MAYON ASH OBS N OF 1315N 12341E",  # ash extent, not volcano position
    "TAAL VOLCANO (1315N 12341E)",  # different volcano
    "MAYON VOLCANO (1399N 12341E)",
    "MAYON VOLCANO (9115N 12341E)",
    "MAYON VOLCANO (1315N 18141E)",
    "MAYON (1315N 12341E) MAYON (1415N 12341E)",
    "MAYON PSN N1399 E12341",
    "MAYON PSN 131560N1234100E",
    "MAYON PSN N9001 E12341",
    "MAYON PSN N1315 E18001",
    "MAYON OBS VA CLD N1315 E12341",
    "MAYON ERUPTION. VOLCANO: TAAL 123456 PSN N1315 E12341",
    "MAYON PSN N1315 E12341 MAYON PSN N1415 E12341",
    "MAYON PSN N1315 E12341 MAYON PSN N1399 E12341",
])
def test_unverified_or_ambiguous_position_is_not_plotted(text):
    assert _cfp_volcano_position(text, "MAYON") is None


def test_ofp_marker_is_source_bound_without_ash_or_proximity_claim():
    flight = {
        "route_waypoints": [
            {"name": "A", "latitude": 1, "longitude": 100},
            {"name": "B", "latitude": 15, "longitude": 125},
        ],
        "volcanic_advisories": [{
            "volcano": "MAYON", "notam_id": "A0001/26", "source_page": 34,
            "volcano_position": _cfp_volcano_position("MAYON (1315N 12341E)", "MAYON"),
        }, {"volcano": "UNKNOWN", "volcano_position": None}],
    }
    contract = build_map_contract(flight, [], MapSettings(provider="schematic"))
    features = contract.hazards_geojson["features"]
    assert len(features) == 1
    marker = features[0]
    assert marker["geometry"]["type"] == "Point"
    assert marker["properties"]["source_page"] == 34
    assert marker["properties"]["notam_id"] == "A0001/26"
    assert "volcano_ring" not in marker["properties"]
    assert "within_corridor" not in marker["properties"]
    # Exercise the real offline/PDF fallback, not only the JSON contract:
    # treating point coordinates as polygon rings used to crash rendering.
    from app.odss_map_v06.schematic import _render_svg
    svg = _render_svg(contract, width=800, height=450)
    assert "MAYON</text>" in svg
    assert "<path " in svg
    assert "<polygon " not in svg
