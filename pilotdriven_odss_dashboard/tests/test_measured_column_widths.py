"""Synthetic layout cases preserve content while sharing spare column width."""
from copy import deepcopy

import pytest

from app.odss.operational_format import Card, GAP, card_height, balanced_row_widths, row_widths, plan_page


@pytest.mark.parametrize("lengths", [(90, 20), (20, 90), (60, 50), (1, 1)])
@pytest.mark.parametrize("width,body,leading", [(774, 9.6, 11.6), (620, 9.0, 10.3)])
def test_measured_columns_never_worsen_height_or_change_content(lengths, width, body, leading):
    cards = [Card("SOURCE TEXT", [f"Record {i}: " + "variable " * n], tag="SOURCE" if i == 0 else None)
             for i, n in enumerate(lengths)]
    before = deepcopy(cards)
    standard = row_widths(cards, width)
    balanced = balanced_row_widths(cards, width, body, leading)
    old = max(card_height(c, w, body, leading) for c, w in zip(cards, standard))
    new = max(card_height(c, w, body, leading) for c, w in zip(cards, balanced))
    assert new <= old
    assert sum(balanced) + GAP == pytest.approx(width)
    assert min(balanced) > 28
    assert cards == before
    assert balanced == balanced_row_widths(cards, width, body, leading)
    if max(lengths) > 2 * min(lengths):
        assert new < old


def test_empty_and_non_text_rows_keep_their_declared_geometry():
    for cards in ([], [Card("ONE", ["held"])], [Card("MAP", kind="map"), Card("TEXT", ["held"])],
                  [Card(str(i), ["held"]) for i in range(3)]):
        assert balanced_row_widths(cards, 774, 9.0, 10.3) == row_widths(cards, 774)


@pytest.mark.parametrize("reverse", [False, True])
def test_planner_draws_with_the_same_widths_that_made_the_complete_row_fit(reverse):
    cards = [Card("LONG SOURCE", ["variable " * 200]), Card("SHORT SOURCE", ["short " * 20])]
    if reverse:
        cards.reverse()
    with pytest.raises(ValueError, match="capacity exceeded"):
        plan_page("TEST", "test", [(200, cards)], body=9.0, leading=10.3)
    page, = plan_page("TEST", "test", [(200, cards)], body=9.0, leading=10.3, balance_columns=True)
    assert [box.card for box in page.boxes] == cards
    assert all(card_height(box.card, box.width, page.body, page.leading) <= box.height for box in page.boxes)
    assert page.boxes[0].x + page.boxes[0].width + GAP == pytest.approx(page.boxes[1].x)


def test_unfit_content_still_fails_without_truncation():
    cards = [Card("HELD", ["variable " * 2000]), Card("ALSO HELD", ["variable " * 2000])]
    before = deepcopy(cards)
    with pytest.raises(ValueError, match="capacity exceeded"):
        plan_page("TEST", "test", [(200, cards)], balance_columns=True)
    assert cards == before
