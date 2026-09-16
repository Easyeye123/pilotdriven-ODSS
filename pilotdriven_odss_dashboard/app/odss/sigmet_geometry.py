"""Read an explicit primary SIGMET polygon without guessing a FIR sector.

Directional OF LINE and corridor areas require boundaries not supplied here.
Reject partial coordinate lists, and never substitute a later forecast area.
"""
from __future__ import annotations

import re

_POINT = r'[NS]\d{4}\s+[EW]\d{5}'
_COORDINATES = re.compile(r'([NS])(\d{2})(\d{2})\s+([EW])(\d{3})(\d{2})')
# ICAO Annex 3 vertical extent: an explicit base/top, or a top alone for the
# surface-based phenomena. A six-digit validity group never matches the
# four-to-five-digit height alternative because it has no word boundary inside.
_EXPLICIT_LAYER = re.compile(
    r'\b(?P<base>SFC|FL\d{3}|\d{4,5}(?:M|FT)?)/(?P<top>(?:FL)?\d{3}|\d{4,5}(?:M|FT))\b')
_TOP_ONLY = re.compile(r'\bTOP\s+(?:(?P<qualifier>ABV|BLW)\s+)?FL(?P<level>\d{3})\b')
_ABOVE = re.compile(r'\bABV\s+FL(?P<level>\d{3})\b')
_BELOW = re.compile(r'\bBLW\s+FL(?P<level>\d{3})\b')
# The phenomena the live matcher already treats as surface-based when the
# source states a top only (``vaa._SURFACE_BASE_WHEN_OMITTED``).
_SURFACE_BASED_WHEN_ONLY_A_TOP = re.compile(r'\b(?:TS(?:GR)?|DS|SS|TC)\b')


def _feet(token, unit_hint=None):
    token = str(token).upper()
    if token == 'SFC':
        return 0
    if re.fullmatch(r'(?:FL)?\d{3}', token):
        return int(token[-3:]) * 100
    height = re.fullmatch(r'(\d{4,5})(M|FT)?', token)
    unit = (height.group(2) or unit_hint) if height else None
    if unit == 'FT':
        return int(height.group(1))
    if unit == 'M':
        return round(int(height.group(1)) * 3.28084)
    return None


def source_layer(value, phenomenon=None):
    """The vertical extent the SIGMET states, in feet, without guessing a base.

    ``SFC/FL100``, ``FL250/400`` and geometric heights are explicit. Lido
    prints thunderstorm SIGMETs with a top only (``TOP FL450``); TS, DS, SS
    and TC are surface-based phenomena, so the top alone fixes their layer -
    the convention the live matcher applies. Any other top-only source, and a
    source with no layer at all, returns None: nothing is asserted about a
    level the source did not give. ``upper_ft`` is None for an open top.
    """
    source = str(value or '')
    explicit = _EXPLICIT_LAYER.search(source)
    if explicit:
        base, top = explicit.group('base').upper(), explicit.group('top').upper()
        hint = 'M' if top.endswith('M') else 'FT' if top.endswith('FT') else None
        lower, upper = _feet(base, hint), _feet(top)
        if lower is None or upper is None or lower > upper:
            return None
        top_label = f'FL{top}' if re.fullmatch(r'\d{3}', top) else top
        return {'lower_ft': lower, 'upper_ft': upper, 'label': f'{base}/{top_label}', 'kind': 'layer'}
    top_only = _TOP_ONLY.search(source)
    if top_only:
        if not _SURFACE_BASED_WHEN_ONLY_A_TOP.search(str(phenomenon or '').upper()):
            return None
        qualifier = top_only.group('qualifier')
        level = int(top_only.group('level')) * 100
        return {'lower_ft': 0, 'upper_ft': None if qualifier == 'ABV' else level,
                'label': f"{qualifier + ' ' if qualifier else ''}FL{top_only.group('level')}",
                'kind': 'top'}
    above = _ABOVE.search(source)
    if above:
        return {'lower_ft': int(above.group('level')) * 100, 'upper_ft': None,
                'label': f"ABV FL{above.group('level')}", 'kind': 'layer'}
    below = _BELOW.search(source)
    if below:
        return {'lower_ft': 0, 'upper_ft': int(below.group('level')) * 100,
                'label': f"BLW FL{below.group('level')}", 'kind': 'layer'}
    return None


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
