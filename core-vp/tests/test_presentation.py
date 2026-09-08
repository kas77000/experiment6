"""Presentation rules that were wrong the first time the app was rendered."""
import datetime as dt

import numpy as np
import pytest

from core.profile import decode_profile
from core.provider_demo import DemoProvider
from core.realized import realized_curve
from tests.fixtures import raw_profile
from ui import charts, panels

P = decode_profile(raw_profile(), "000001.C2", dt.date(2026, 7, 29))
PROV = DemoProvider()
D = PROV.available_dates()[-1]
REAL = realized_curve(PROV.get_qatt(D, "000001.C2"), P,
                      PROV.get_open_print(D, "000001.C2"))


def test_a_bar_is_as_wide_as_the_time_it_covers():
    """571 and 572 are one-minute buckets; the rest are ten. Equal widths
    would make a bar's area meaningless."""
    minutes = P.continuous["minute"].tolist()
    widths = charts.bar_widths(minutes, P.session)
    by_minute = dict(zip(minutes, widths))
    assert by_minute[572] < by_minute[580]
    assert by_minute[572] == pytest.approx(0.82, abs=1e-9)
    assert by_minute[580] == pytest.approx(8 * 0.82, abs=1e-9)


def test_the_bucket_after_lunch_is_not_ninety_minutes_wide():
    minutes = P.continuous["minute"].tolist()
    by_minute = dict(zip(minutes, charts.bar_widths(minutes, P.session)))
    assert by_minute[780] == pytest.approx(10 * 0.82, abs=1e-9)


def test_legend_sits_below_the_plot_so_it_cannot_collide_with_the_title():
    fig = charts.profile_figure(P)
    assert fig.layout.legend.y < 0
    assert fig.layout.legend.yanchor == "top"


def test_self_normalising_makes_the_closing_divergence_zero_by_construction():
    """Why the ADV basis is the default."""
    assert REAL["cum_frac"].iloc[-1] == pytest.approx(1.0)
    assert P.continuous["cum_frac"].iloc[-1] == pytest.approx(1.0)
    day_gap = REAL["cum_frac"].iloc[-1] - P.continuous["cum_frac"].iloc[-1]
    assert day_gap == pytest.approx(0.0, abs=1e-9)


def test_the_adv_basis_keeps_a_heavy_day_readable():
    adv_gap = REAL["cum_of_adv"].iloc[-1] - P.continuous["cum_frac"].iloc[-1]
    assert adv_gap > 0.01, "the demo day runs heavy; the ADV basis must show it"


def test_realized_figure_plots_the_requested_basis():
    for key, column in (("adv", "cum_of_adv"), ("day", "cum_frac")):
        fig = charts.realized_figure(P, REAL, key)
        today = [t for t in fig.data if t.name == "today"][0]
        expected = [v for v in REAL[column]]
        drawn = [v for v in today.y if not (isinstance(v, float) and np.isnan(v))]
        assert drawn == pytest.approx(expected)


def test_neither_realized_figure_uses_a_second_axis():
    for fig in (charts.realized_figure(P, REAL, "adv"),
                charts.realized_bucket_figure(P, REAL, "adv")):
        assert "yaxis2" not in fig.layout


def test_a_rounding_artefact_never_renders_as_minus_zero():
    assert panels.qty(-0.0000001) == "0"
    assert panels.qty(-0.4) == "0"
    assert panels.qty(-1.0) == "-1"


def test_big_numbers_are_compact_so_a_metric_tile_does_not_truncate():
    assert panels.qty_compact(105156029) == "105.2M"
    assert panels.qty_compact(445700) == "445.7K"
    assert panels.qty_compact(2000) == "2.0K"
    assert panels.qty_compact(812) == "812"
    assert panels.qty_compact(None) == panels.DASH
