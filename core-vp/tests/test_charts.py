import datetime as dt
import inspect

import numpy as np
import pytest

from core.profile import decode_profile
from core.provider_demo import DemoProvider
from core.realized import realized_curve
from core.schedule import build_schedule
from tests.fixtures import raw_profile
from ui import charts

P = decode_profile(raw_profile(), "000001.C2", dt.date(2026, 7, 29))
PROV = DemoProvider()
D = PROV.available_dates()[-1]


def _schedule(behaviour_index=0):
    orders = PROV.list_vwap_orders(D, {})
    o = orders.iloc[behaviour_index]
    prof = decode_profile(PROV.get_profile(D, o.sym), o.sym, D)
    return prof, o, build_schedule(
        prof, o,
        PROV.get_executions(D, o.id_server, o.id_target),
        PROV.get_target_state(D, o.id_server, o.id_target))


def test_profile_figure_has_the_curve_and_the_even_pace_reference():
    names = [t.name for t in charts.profile_figure(P).data]
    assert "cumulated" in names and "even pace" in names


def test_lunch_is_shaded():
    fig = charts.profile_figure(P)
    assert any(s.type == "rect" for s in fig.layout.shapes)


def test_lines_break_across_lunch_rather_than_running_through_it():
    fig = charts.profile_figure(P)
    line = [t for t in fig.data if t.name == "cumulated"][0]
    assert line.connectgaps is False
    assert any(v is None or (isinstance(v, float) and np.isnan(v))
               for v in line.y), "expected a NaN at the lunch break"


def test_even_pace_does_not_accrue_over_lunch():
    minutes, pace = charts.even_pace(P)
    at = dict(zip(minutes, pace))
    assert at[690] == pytest.approx(at[780], abs=1e-9)   # 11:30 and 13:00 equal
    assert pace[0] == 0.0 and pace[-1] == pytest.approx(1.0)


def test_progression_figure_shows_expected_and_filled():
    prof, order, sched = _schedule()
    names = [t.name for t in charts.progression_figure(sched, order,
                                                       prof.session).data]
    assert "expected" in names and "filled" in names


def test_committed_series_appears_only_when_there_is_a_reserve():
    orders = PROV.list_vwap_orders(D, {})
    with_commit, without = [], []
    for i in range(len(orders)):
        prof, order, sched = _schedule(i)
        names = [t.name for t in charts.progression_figure(
            sched, order, prof.session).data]
        (with_commit if sched.committed_qty.max() > 0 else without).append(
            "filled + committed" in names)
    assert with_commit and all(with_commit)
    assert without and not any(without)


def test_the_ahead_behind_band_carries_no_status_colour():
    """Red for 'behind' would assert the misreading this panel prevents."""
    prof, order, sched = _schedule()
    fig = charts.progression_figure(sched, order, prof.session)
    fills = [t.fillcolor for t in fig.data if getattr(t, "fill", None) == "tonexty"]
    assert fills == [charts.BAND]
    assert "137, 135, 129" in charts.BAND      # the muted grey, not a hue


def test_realized_figures_compare_two_series_on_one_scale():
    prof = decode_profile(PROV.get_profile(D, "000001.C2"), "000001.C2", D)
    real = realized_curve(PROV.get_qatt(D, "000001.C2"), prof,
                          PROV.get_open_print(D, "000001.C2"))
    for fig in (charts.realized_figure(prof, real),
                charts.realized_bucket_figure(prof, real)):
        names = [t.name for t in fig.data]
        assert "profile (median)" in names and "today" in names
        assert "yaxis2" not in fig.layout          # never a dual axis


def test_every_figure_declares_a_legend_when_it_has_two_series():
    prof, order, sched = _schedule()
    real = realized_curve(PROV.get_qatt(D, prof.sym), prof, None)
    for fig in (charts.profile_figure(prof),
                charts.progression_figure(sched, order, prof.session),
                charts.realized_figure(prof, real)):
        assert fig.layout.showlegend is True


def test_charts_module_imports_no_streamlit():
    assert "streamlit" not in inspect.getsource(charts)
