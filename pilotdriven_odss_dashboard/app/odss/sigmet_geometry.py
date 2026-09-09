"""Read an explicit primary SIGMET polygon without guessing a FIR sector.

Directional OF LINE and corridor areas require boundaries not supplied here.
Reject partial coordinate lists, and never substitute a later forecast area.
"""
from __future__ import annotations

import re

_POINT = r'[NS]\d{4}\s+[EW]\d{5}'
_COORDINATES = re.compile(r'([NS])(\d{2})(\d{2})\s+([EW])(\d{3})(\d{2})')


def source_polygon(value):
    source = str(value or '')
    declaration = re.search(r'\b(?:OBS|FCST)\b', source)
    if declaration:
        forecast = re.search(r'\bFCST\b', source[declaration.end():])
        if forecast:
            source = source[:declaration.end() + forecast.start()]
    within = re.search(r'\bWI\s+', source)
    if not within:
        return []
    area = source[within.end():]
    end = re.search(r'\b(?:TOP|SFC|FL\d{2,3}|\d{4,5}(?:M|FT|/\d{4,5}(?:M|FT))|ABV|BLW|MOV|STNR|NC|WKN|INTSF|FCST|OBS)\b|=', area)
    area = (area[:end.start()] if end else area).strip()
    # Validate the entire area: a malformed fourth point must not turn a
    # four-sided area into a valid-looking three-point prefix.
    if not re.fullmatch(rf'{_POINT}(?:\s*(?:-\s*)?{_POINT}){{2,}}', area):
        return []
    points = []
    for ns, latd, latm, ew, lond, lonm in _COORDINATES.findall(area):
        if (int(latm) >= 60 or int(lonm) >= 60 or int(latd) > 90 or int(lond) > 180
                or (int(latd) == 90 and int(latm)) or (int(lond) == 180 and int(lonm))):
            return []
        points.append(((int(latd) + int(latm) / 60) * (-1 if ns == 'S' else 1),
                       (int(lond) + int(lonm) / 60) * (-1 if ew == 'W' else 1)))
    from shapely.geometry import Polygon
    polygon = Polygon(points)
    return points if polygon.is_valid and polygon.area > 0 else []
