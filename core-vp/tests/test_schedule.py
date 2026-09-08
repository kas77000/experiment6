import datetime as dt

import pandas as pd
import pytest

from core.profile import decode_profile
from core.schedule import build_schedule, to_minute
from tests.fixtures import raw_profile

PROFILE = decode_profile(raw_profile(), "000001.C2", dt.date(2026, 7, 29))


def order(size=1_000_000, doopen=1, doclose=1, t_start=None, t_end=None):
    return pd.Series({"size": size, "doopen": doopen, "doclose": doclose,
                      "t_start": t_start, "t_end": t_end, "sym": "000001.C2"})


def execs(pairs):
    return pd.DataFrame({"time": [pd.Timedelta(minutes=m) for m, _ in pairs],
                         "cum_qty": [q for _, q in pairs]})


def states(triples):
    return pd.DataFrame({
        "t_algo": [pd.Timedelta(minutes=m) for m, _, _ in triples],
        "commit_open": [a for _, a, _ in triples],
        "commit_close": [b for _, _, b in triples]})


def test_to_minute_accepts_the_shapes_kdb_returns():
    assert to_minute(pd.Timedelta(minutes=570)) == 570
    assert to_minute(dt.time(9, 30)) == 570
    assert to_minute(570) == 570
    assert to_minute(None) is None
    assert to_minute(pd.NaT) is None


def test_expected_reaches_the_full_order_size():
    s = build_schedule(PROFILE, order(), execs([]), states([]))
    assert s.expected_qty.iloc[-1] == pytest.approx(1_000_000)
    assert s.expected_qty.is_monotonic_increasing


def test_doclose_off_removes_the_close_auction_from_the_schedule():
    on = build_schedule(PROFILE, order(doclose=1), execs([]), states([]))
    off = build_schedule(PROFILE, order(doclose=0), execs([]), states([]))
    assert "close auction" in set(on.phase)
    assert "close auction" not in set(off.phase)
    assert off.expected_qty.iloc[-1] == pytest.approx(1_000_000)


def test_window_clips_the_schedule():
    s = build_schedule(PROFILE,
                       order(t_start=pd.Timedelta(minutes=600),
                             t_end=pd.Timedelta(minutes=700)),
                       execs([]), states([]))
    assert s.minute.min() >= 600 and s.minute.max() <= 700
    assert s.expected_qty.iloc[-1] == pytest.approx(1_000_000)


def test_filled_is_forward_filled_from_cum_qty():
    s = build_schedule(PROFILE, order(),
                       execs([(600, 200_000), (700, 500_000)]), states([]))
    assert s[s.minute == 590].filled_qty.iloc[0] == 0
    assert s[s.minute == 600].filled_qty.iloc[0] == 200_000
    assert s[s.minute == 650].filled_qty.iloc[0] == 200_000
    assert s.filled_qty.iloc[-1] == 500_000


def test_committed_is_separate_from_filled():
    s = build_schedule(PROFILE, order(), execs([(600, 200_000)]),
                       states([(600, 0, 300_000)]))
    row = s[s.minute == 650].iloc[0]
    assert row.filled_qty == 200_000
    assert row.committed_qty == 300_000
    assert row.filled_plus_committed == 500_000


def test_an_order_reserving_for_the_close_is_not_reported_as_behind():
    """500k of a 1m order filled and 500k reserved for the close: the naive
    read says behind, the true read says complete."""
    s = build_schedule(PROFILE, order(size=1_000_000),
                       execs([(880, 500_000)]), states([(880, 0, 500_000)]))
    row = s[s.minute == 890].iloc[0]
    assert row.ahead_qty < 0
    assert row.filled_plus_committed == 1_000_000


def test_no_fills_gives_a_zero_column_not_a_crash():
    s = build_schedule(PROFILE, order(), execs([]), states([]))
    assert (s.filled_qty == 0).all() and (s.committed_qty == 0).all()


def test_a_window_selecting_nothing_is_an_error():
    with pytest.raises(ValueError, match="no profile buckets"):
        build_schedule(PROFILE, order(t_start=pd.Timedelta(minutes=1200)),
                       execs([]), states([]))
