"""Join the bulletin role to its independently parsed operational role in parity checks.

This is a comparison contract, not a production timing policy. An adequate-airport
bulletin heading does not designate that airport in the flight's EDTO table.
"""

ODSS_ROLE = {
    "departure": "departure", "destination": "destination",
    "destination_alternate": "destination alternate", "edto": "EDTO",
    "edto_suitable": "EDTO", "edto_adequate": "EDTO",
    "fuel_enroute": "fuel enroute airport", "enroute": "informational",
}


def operational_role(primary: str, icao: str, station_roles: list[str], selected_edto: list[str]) -> str:
    # Either parser's explicit EDTO selection requires an EDTO assessment. In
    # particular, never choose a fallback by looking at the assessment rows:
    # a missing selected-role row is exactly the defect the comparison must catch.
    if primary == "edto_adequate" and "edto" not in station_roles and icao not in selected_edto:
        return "informational"
    return ODSS_ROLE[primary]
