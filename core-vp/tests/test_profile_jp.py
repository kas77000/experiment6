"""7203.JP - a real gateway result for a Tokyo name.

Different from the Shenzhen sample in every way that could break the decoder:
a 60-minute lunch instead of 90, one more pre-open row, no cc0 column, a PM
reopen auction two orders of magnitude larger, and a closing auction worth
nearly a quarter of the day.
"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from core.markets import (auction_minutes, display_offset_minutes,
                          zone_label)
from core.profile import PHASE_CLOSE, PHASE_PM, decode_profile
from core.schedule import build_schedule
from tests.fixtures import raw_profile_jp
from ui import charts

DATE = dt.date(2026, 9, 3)
P = decode_profile(raw_profile_jp(), "7203.JP", DATE)


def test_header_scalars():
    assert P.adv == 17_110_800
    assert P.v_open == 1_109_400
    assert P.v_close == 5_570_500
    assert P.v_open_pm == 247_700


def test_the_sixty_minute_lunch_is_found():
    """Shenzhen's gap is 90 minutes, Tokyo's is 60. The rule is 'largest gap
    over twice the median spacing', so both must work."""
    assert P.session.lunch == (630, 690)
    assert P.session.open_min == 480 and P.session.close_min == 865
    assert P.session.warnings == ()


def test_the_flat_bucket_across_lunch_carries_no_volume():
    row = P.continuous[P.continuous.minute == 690].iloc[0]
    assert row.cum_frac == 0.57841        # identical to 630
    assert row.share == 0.0


def test_the_extra_pre_open_row_is_handled_without_cc0():
    """This result has seven zero rows to Shenzhen's six, and no cc0 column,
    so the header skip has to be derived."""
    assert P.continuous.minute.min() == 480      # the session open, at cum 0
    assert P.continuous.iloc[0].share == 0.0
    assert 481 in set(P.continuous.minute)


def test_cc0_and_the_derived_skip_agree_on_this_symbol_too():
    with_cc0 = decode_profile(raw_profile_jp(cc0=True), "7203.JP", DATE)
    assert list(with_cc0.continuous.minute) == list(P.continuous.minute)


def test_the_pm_auction_sits_at_the_afternoon_reopen():
    """12:30 JST - which is exactly where the lunch gap ends, so this needs no
    lookup at all."""
    row = P.buckets[P.buckets.phase == PHASE_PM].iloc[0]
    assert row.minute == P.session.lunch[1] == 690


def test_auctions_are_seated_at_the_real_tse_print_times():
    local = decode_profile(
        raw_profile_jp(), "7203.JP", DATE,
        tz_offset_min=display_offset_minutes("7203.JP", DATE),
        auctions=auction_minutes("7203.JP", DATE))
    at = dict(zip(local.buckets.phase, local.buckets.clock))
    assert at["open auction"] == "09:00"     # Itayose
    assert at["pm auction"] == "12:30"       # afternoon reopen
    assert at["close auction"] == "15:30"    # closing auction
    assert local.session.warnings == ()


def test_a_stale_auction_time_falls_back_instead_of_drawing_it_wrong():
    """If TSE moves its close again, the listed time stops agreeing with the
    session in the data. That must degrade visibly, not silently."""
    stale = decode_profile(raw_profile_jp(), "7203.JP", DATE,
                           auctions=(480, 700))   # close before the session ends
    assert stale.session.warnings
    assert "close auction" in " ".join(stale.session.warnings)
    close = stale.buckets[stale.buckets.phase == PHASE_CLOSE].iloc[0]
    assert close.minute > stale.session.close_min


def test_shares_still_sum_to_one_with_a_large_close_auction():
    assert P.buckets.share_of_day.sum() == pytest.approx(1.0)
    close = P.buckets[P.buckets.phase == PHASE_CLOSE].iloc[0]
    assert close.share_of_day > 0.20      # TSE's closing auction is enormous


def test_the_line_breaks_over_lunch():
    line = [t for t in charts.profile_figure(P).data if t.name == "cumulated"][0]
    assert sum(1 for v in line.y if isinstance(v, float) and np.isnan(v)) == 1


def test_even_pace_does_not_accrue_over_a_sixty_minute_lunch():
    at = dict(zip(*charts.even_pace(P)))
    assert at[630] == pytest.approx(at[690], abs=1e-9)


def test_a_schedule_can_be_built_against_this_profile():
    order = pd.Series({"size": 500_000, "doopen": 1, "doclose": 1,
                       "t_start": None, "t_end": None, "sym": "7203.JP"})
    s = build_schedule(P, order, pd.DataFrame(), pd.DataFrame())
    assert s.expected_qty.iloc[-1] == pytest.approx(500_000)
    assert s.expected_qty.is_monotonic_increasing


def test_the_bucket_after_lunch_is_not_sixty_minutes_wide():
    minutes = P.continuous["minute"].tolist()
    widths = dict(zip(minutes, charts.bar_widths(minutes, P.session)))
    assert widths[690] == pytest.approx(10 * 0.82, abs=1e-9)


def test_the_raw_minutes_are_region_time():
    """The gateway and qatt both report on the region clock (HKT). Tokyo
    trades 09:00-11:30 / 12:30-15:30 JST, and this profile opens at 480 and
    breaks 630-690 - exactly JST minus one hour. Shenzhen is on UTC+8, so its
    570 == 09:30 matched local time by coincidence.

    `minute` must stay on the region clock: it is what the profile, qatt and
    the order tables join on.
    """
    assert P.session.open_min == 480                # 09:00 JST
    assert P.session.lunch == (630, 690)            # 11:30-12:30 JST
    assert P.session.close_min == 865               # 15:25 JST


def test_labels_are_shifted_to_tokyo_time():
    local = decode_profile(
        raw_profile_jp(), "7203.JP", DATE,
        tz_offset_min=display_offset_minutes("7203.JP", DATE),
        tz_label=zone_label("7203.JP", DATE))

    assert local.tz_offset_min == 60
    assert "Tokyo" in local.tz_label and "UTC+9" in local.tz_label
    assert local.continuous.clock.iloc[0] == "09:00"    # the TSE open
    assert local.continuous.clock.iloc[-1] == "15:25"   # into the close auction

    # the numbers themselves must not have moved
    assert list(local.continuous.minute) == list(P.continuous.minute)
    assert list(local.continuous.share) == list(P.continuous.share)
    assert local.session == P.session


def test_the_chart_axis_is_labelled_in_local_time_too():
    local = decode_profile(raw_profile_jp(), "7203.JP", DATE,
                           tz_offset_min=display_offset_minutes("7203.JP", DATE))
    fig = charts.profile_figure(local)
    labels = list(fig.layout.xaxis.ticktext)
    assert "09:00" in labels and "15:00" in labels
    assert "08:00" not in labels
