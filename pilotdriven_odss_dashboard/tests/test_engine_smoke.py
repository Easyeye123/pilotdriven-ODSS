from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis import actm_minutes, format_actm


def test_actm_round_trip() -> None:
    assert actm_minutes("05.36") == 336
    assert format_actm(336) == "05.36"
