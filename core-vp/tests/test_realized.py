import datetime as dt

import pandas as pd
import pytest

from core.profile import decode_profile
from core.realized import realized_curve
from tests.fixtures import raw_profile

PROFILE = decode_profile(raw_profile(), "000001.C2", dt.date(2026, 7, 29))


def qatt(pairs):
    return pd.DataFrame({"tradeTime": [pd.Timedelta(minutes=m) for m, _ in pairs],
                         "size": [s for _, s in pairs]})


def test_trades_land_in_the_bucket_that_closes_after_them():
    r = realized_curve(qatt([(575, 100), (585, 200)]), PROFILE)
    assert r[r.minute == 580].volume.iloc[0] == 100
    assert r[r.minute == 590].volume.iloc[0] == 200


def test_cumulative_and_normalised_columns():
    r = realized_curve(qatt([(575, 100), (585, 300)]), PROFILE)
    assert r.cum_volume.iloc[-1] == 400
    assert r.cum_frac.iloc[-1] == pytest.approx(1.0)
    assert r[r.minute == 580].share.iloc[0] == pytest.approx(0.25)


def test_open_print_is_reseated_into_the_first_bucket_not_counted_twice():
    """getsymprof_realRT subtracts the opening print from the bucket holding it
    and seats it in the first bucket instead."""
    r = realized_curve(qatt([(571, 5000), (585, 200)]), PROFILE,
                       open_print=(571, 5000))
    assert r.iloc[0].volume == 5000
    assert r[r.minute == 571].volume.iloc[0] == 0
    assert r.cum_volume.iloc[-1] == 5200


def test_empty_qatt_gives_zeros_on_the_full_grid():
    r = realized_curve(pd.DataFrame(columns=["tradeTime", "size"]), PROFILE)
    assert len(r) == len(PROFILE.continuous)
    assert (r.volume == 0).all()
    assert r.cum_frac.isna().all()


def test_falls_back_to_time_when_tradetime_is_absent():
    q = pd.DataFrame({"time": [pd.Timedelta(minutes=575)], "size": [100]})
    r = realized_curve(q, PROFILE)
    assert r[r.minute == 580].volume.iloc[0] == 100


def test_a_frame_without_a_size_column_is_not_a_crash():
    q = pd.DataFrame({"tradeTime": [pd.Timedelta(minutes=575)], "qbid": [1.0]})
    r = realized_curve(q, PROFILE)
    assert (r.volume == 0).all()


def test_trades_after_the_close_are_dropped_not_folded_into_the_last_bucket():
    r = realized_curve(qatt([(575, 100), (1200, 999)]), PROFILE)
    assert r.cum_volume.iloc[-1] == 100
