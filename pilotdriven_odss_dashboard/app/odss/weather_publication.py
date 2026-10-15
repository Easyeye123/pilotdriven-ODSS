"""Concise PDF projection of governed EDTO and weather evidence.

Screened-out records still need an explanation. Missing observations or an
unfinished applicability assessment must never become a no-hazard verdict.
This module does not change dashboard analysis or perform weather matching.
"""
from __future__ import annotations

import re

from .analysed_briefing_content import clean, flight_window, window_label
from .vaa import _utc


def _matched_lines(flight, view, *, ash):
    """Keep the live route/time/level matches already admitted to the map."""
    start, end = flight_window(flight)
    lines = []
    for feature in (view.get('route_map') or {}).get('hazard_features') or []:
        p = feature.get('properties') or {}
        if (p.get('hazard') == 'volcanic_ash') != ash or p.get('hazard') == 'tropical_cyclone':
            continue
        begin, finish = _utc(p.get('valid_from_utc')), _utc(p.get('valid_to_utc'))
        if not (p.get('hazard_state') == 'affecting' and start and end and begin and finish
                and start <= finish and begin <= end):
            continue
        ref = clean(p.get('advisory_id') or feature.get('id')) or 'ID unresolved'
        hazard = 'ash' if ash else clean(p.get('hazard_code')) or 'significant weather'
        lines.append(f'{ref}: {hazard} intersects the filed route/time/level; '
                     f'valid {begin:%d%b %H%MZ}-{finish:%d%b %H%MZ}.')
    return list(dict.fromkeys(lines))


def edto_window_lines(flight, view):
    from .briefing import _edto_assessment_view

    edto = view.get('edto') or {}
    assessment = _edto_assessment_view(flight.get('edto') or {})
    # QA508-01: an EDTO table row that was not read is a review in its printed place, never an absent window.
    reviews = sorted(
        ((int(r.get('position') or 0), f"{clean(r.get('airport')) or '----'} · {clean(r.get('review'))}")
         for r in edto.get('unread_rows') or [] if isinstance(r, dict)),
        key=lambda item: item[0],
    )
    if (assessment['status'] == 'verified_not_applicable' and not edto.get('airports') and not edto.get('sectors')
            and not reviews):
        return ['Not applicable - this flight is NON-EDTO.']
    rows = [f"{clean(r.get('airport')) or 'Not held'}/{clean(r.get('runway')) or 'Not held'}: "
            f"{clean(r.get('approach')) or 'Not held'} {clean(r.get('minima')) or 'Not held'}; "
            f"{clean(r.get('period')) or 'Not held'}." for r in edto.get('airports') or []]
    windows = bool(rows)
    for position, line in reviews:
        rows.insert(min(position, len(rows)), line)
    if windows:
        return rows
    if assessment['status'] == 'affected':
        return [*rows, 'EDTO applies, but airport suitability windows are missing.']
    return [*rows, 'EDTO applicability is unresolved; airport suitability windows cannot be established.']


def sigmet_lines(flight, view):
    from .briefing import _sigmet_screening_cards, _sigmet_utc

    lines, outside, unreadable, expired = _matched_lines(flight, view, ash=False), [], [], {}
    departure = _utc(flight.get('scheduled_departure_utc'))
    rechecked_cards = None
    for card in (view.get('hazards') or {}).get('sigmet_cards') or []:
        if 'route_intersection' not in card:
            # Older producers mistook missing timed inside fixes for no spatial
            # crossing. Re-screen the identical original message for a newly
            # rendered PDF; never rewrite the held card or original saved PDF.
            if rechecked_cards is None:
                rechecked_cards = {
                    (row.get('fir'), row.get('sigmet_id'), clean(row.get('text'))): row
                    for row in _sigmet_screening_cards(flight)
                }
            key = (card.get('fir'), card.get('sigmet_id'), clean(card.get('text')))
            card = rechecked_cards.get(key) or {
                **card, 'route_intersection': 'unresolved',
                'screening': 'Legacy spatial verdict cannot be verified from its original source; route applicability unresolved.',
            }
        ref = f"{clean(card.get('fir')) or 'FIR unresolved'}/{clean(card.get('sigmet_id')) or 'ID unresolved'}"
        screening = clean(card.get('screening'))
        if card.get('route_intersection') == 'outside':
            distance = re.search(r'approximately (\d+) NM ([a-z]+)', screening)
            suffix = f" ({distance[1]} NM {distance[2]})" if distance else ''
            outside.append(ref + suffix)
        elif card.get('route_intersection') == 'unresolved' or screening.startswith('No readable polygon'):
            unreadable.append(ref)
        else:
            analysed = re.sub(r'\s*(?:NOT PROMOTED\.|PROMOTED - review required\.)$', '', screening)
            # Keep the route-passage UTC interval; ACTM remains when UTC is absent.
            analysed = re.sub(r'The polygon crosses the route about ACTM \S+ / (\d{4}-\d{4}Z)', r'Route crossing \1', analysed)
            analysed = analysed.replace('The polygon crosses the route about ', 'Route crossing ')
            analysed = analysed.replace('The polygon crosses the route within filed leg bounds ', 'Crossing leg bounds ')
            analysed = re.sub(r'Crossing leg bounds ACTM \S+ / (\d{4}-\d{4}Z)', r'Crossing leg bounds \1', analysed)
            analysed = re.sub(r'\s*, but the product expires (\d+) minutes before the earliest possible crossing\.',
                              r'; expires \1 min before earliest bound.', analysed)
            analysed = re.sub(r'\s*, but the product only becomes valid (\d+) minutes after the latest possible crossing\.',
                              r'; starts \1 min after latest bound.', analysed)
            analysed = analysed.replace('The source polygon intersects the filed route, but crossing timing is unresolved because intersecting legs lack complete ordered ACTM values.', 'Route intersection; crossing timing unresolved (incomplete or unordered ACTM).')
            analysed = analysed.replace("inside the product's validity", 'within validity')
            analysed = re.sub(r'Route crossing .*?, but the product ', 'Product ', analysed)
            lines.append(f"{ref} ({clean(card.get('phenomenon')) or 'phenomenon unresolved'}): "
                         f"{analysed or 'Flight applicability is not established.'}")
        # Validity is an independent exclusion even when geometry is unavailable.
        start = _sigmet_utc(flight, card.get('valid_from'))
        end = _sigmet_utc(flight, card.get('valid_to'), near=start)
        if departure and start and end and start < end < departure:
            minutes = (departure - end).total_seconds() / 60
            validity = (f'{start:%d%b %H%M}-{end:%H%MZ}' if start.date() == end.date()
                        else f'{start:%d%b %H%MZ}-{end:%d%b %H%MZ}').upper()
            fir, identifier = ref.split('/', 1)
            expired.setdefault(fir, []).append(f'{identifier} {validity} ({minutes:g} min)')
    if outside:
        lines.append('Outside filed route: ' + '; '.join(outside) + '.')
    if unreadable:
        lines.append('Source polygon or route geometry unavailable: ' + ', '.join(unreadable) + '; route applicability unresolved.')
    if expired:
        lines.append(f'Expired before scheduled departure {departure:%d%b %H%MZ} '
                     '(validity UTC; minutes early):')
        lines.extend(f"{fir}: {'; '.join(records)}." for fir, records in expired.items())
        lines.append('These expired records do not establish successor SIGMET coverage for this flight.')
    if not lines:
        lines = [f'No flight-specific SIGMET screening result is held for {window_label(flight)}. '
                 'This does not establish that no SIGMET applies.']
    return lines


def volcanic_ash_lines(flight, view, live='whole'):
    lines = _matched_lines(flight, view, ash=True)
    for row in (view.get('vaa') or {}).get('cfp_advisories') or []:
        if row.get('advisory_kind') == 'CFP_VAA_NOTICE':
            continue
        derived = clean(row.get('derived')) or 'Applicability not established'
        derived = re.sub(r'\. Flight-analysis screening of the OFP advisory polygon.*$', '.', derived)
        derived = derived.replace('Closest approach ', 'Closest ').replace("the SIGMET's validity", 'validity')
        lines.append(f"{clean(row.get('volcano') or row.get('name')) or 'Unnamed advisory'}: {derived}")
    # VOLCANIC-CHECK-436: the live sources, named with what each returned - the
    # feed and every route-responsible VAAC (reached / NOT reached / not
    # queried, advisories held, unsettled route points). The card printed the
    # same sentence whether those sources were off, failed or answered with
    # nothing, and never named a centre (SQ34 SIN-SFO, release 436 QA).
    check = (view.get('vaa') or {}).get('check') or {}
    if check.get('live_line'):
        # ``live`` is the page's own capacity step, taken before any SIGMET, EDTO or clock row is deferred: the live
        # sources by name ("whole"), as counts ("compact"), or - beside held OFP records - left to page 6's source line
        # and checklist, which name them unreached, partial or not queried ("omit"). A card with nothing else to say
        # always prints the counts; the generic sentence never replaces a held check.
        if live == 'whole':
            lines.append(check['live_line'])
        elif live == 'compact' or not lines:
            lines.append(check.get('live_compact') or check['live_line'])
    else:
        direct = flight.get('direct_vaa_source_review') or (flight.get('vaa_review') or {}).get('direct_vaa_source_review') or {}
        count = len(direct.get('official_advisories') or [])
        reached = [clean(r.get('centre')) for r in direct.get('responsible_centre_receipts') or []
                   if r.get('reached') is True and clean(r.get('centre'))]
        centres = '/'.join(dict.fromkeys(reached))
        if count and direct.get('applicability_status') == 'not_assessed':
            noun = 'advisory' if count == 1 else 'advisories'
            prefix = f'{centres} reached; ' if centres else ''
            lines.append(f'{prefix}{count} direct VAAC {noun} held; route/time/level applicability has not been assessed.')
        if direct.get('source_status') == 'partial':
            lines.append('Direct VAAC coverage is partial; the held evidence does not establish an ash-free flight.')
    if not lines:
        lines = [f'No flight-specific ash screening result is held for {window_label(flight)}. '
                 'This does not establish that the route is ash-free.']
    return lines
