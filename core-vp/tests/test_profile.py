import datetime as dt

import pandas as pd
import pytest

from core.profile import (PHASE_CLOSE, PHASE_CONTINUOUS, PHASE_OPEN, PHASE_PM,
                          ProfileError, decode_profile)
from tests.fixtures import raw_profile

SYM = "000001.C2"
DATE = dt.date(2026, 7, 29)


def test_header_scalars_read_from_rows_0_to_3():
    p = decode_profile(raw_profile(), SYM, DATE)
    assert p.adv == 105156029.0
    assert p.v_open == 445700.0
    assert p.v_close == 799800.0
    assert p.v_open_pm == 2000.0
    assert p.vtot == pytest.approx(105156029.0 + 445700.0 + 799800.0 + 2000.0)


def test_cc0_drives_the_header_skip():
    p = decode_profile(raw_profile(cc0=True), SYM, DATE)
    assert p.continuous.minute.min() == 570


def test_cc0_and_the_fallback_agree():
    a = decode_profile(raw_profile(cc0=True), SYM, DATE)
    b = decode_profile(raw_profile(cc0=False), SYM, DATE)
    assert list(a.continuous.minute) == list(b.continuous.minute)
    assert list(a.continuous.share) == list(b.continuous.share)


def test_share_is_the_difference_of_the_cumulative():
    p = decode_profile(raw_profile(), SYM, DATE)
    cont = p.continuous
    row = cont[cont.minute == 580].iloc[0]
    assert row.share == pytest.approx(0.134472 - 0.0380905)
    assert cont.iloc[0].share == 0.0


def test_all_four_phases_present_and_shares_sum_to_one():
    p = decode_profile(raw_profile(), SYM, DATE)
    assert set(p.buckets.phase) == {PHASE_OPEN, PHASE_CONTINUOUS, PHASE_PM,
                                    PHASE_CLOSE}
    assert p.buckets.share_of_day.sum() == pytest.approx(1.0)
    assert p.buckets.cum_of_day.iloc[-1] == pytest.approx(1.0)


def test_auctions_sit_outside_the_continuous_span():
    p = decode_profile(raw_profile(), SYM, DATE)
    b = p.buckets.set_index("phase")
    assert b.loc[PHASE_OPEN, "minute"] < 570
    assert b.loc[PHASE_CLOSE, "minute"] > 900
    assert 690 < b.loc[PHASE_PM, "minute"] <= 780


def test_clock_column_is_readable():
    p = decode_profile(raw_profile(), SYM, DATE)
    cont = p.continuous
    assert cont[cont.minute == 570].iloc[0].clock == "09:30"


def test_empty_frame_rejected():
    with pytest.raises(ProfileError, match="no rows"):
        decode_profile(pd.DataFrame(columns=["time", "vmed"]), SYM, DATE)


def test_non_monotonic_cumulative_rejected():
    raw = raw_profile()
    raw.loc[raw.time == 600, "vmed"] = 0.05
    with pytest.raises(ProfileError, match="not non-decreasing"):
        decode_profile(raw, SYM, DATE)


def test_cumulative_not_reaching_one_rejected():
    raw = raw_profile()
    raw = raw[raw.time <= 850]
    with pytest.raises(ProfileError, match="reach 1.0"):
        decode_profile(raw, SYM, DATE)


def test_missing_header_rows_rejected():
    raw = raw_profile()
    with pytest.raises(ProfileError, match="header"):
        decode_profile(raw[raw.time != 2], SYM, DATE)
