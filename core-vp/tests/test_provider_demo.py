import pandas as pd
import pytest

from core.profile import decode_profile
from core.provider import ORDER_COLUMNS
from core.provider_demo import DemoProvider
from core.realized import realized_curve
from core.schedule import build_schedule

P = DemoProvider()
D = P.available_dates()[-1]
S = P.list_symbols()[0]


def test_profile_round_trips_through_decode():
    prof = decode_profile(P.get_profile(D, S), S, D)
    assert prof.adv == 105156029.0 and prof.v_open_pm == 2000.0
    assert prof.session.is_two_session
    assert prof.session.lunch == (690, 780)


def test_orders_are_all_vwap_and_carry_the_schedule_columns():
    o = P.list_vwap_orders(D, {})
    assert len(o) >= 3 and set(o.algo) == {"VWAP"}
    for c in ORDER_COLUMNS:
        assert c in o.columns


def test_one_demo_order_reserves_for_the_close():
    o = P.list_vwap_orders(D, {})
    reserving = [r for _, r in o.iterrows()
                 if P.get_target_state(D, r.id_server, r.id_target)
                 ["commit_close"].max() > 0]
    assert reserving, "demo data must show the reserve-for-close behaviour"


def test_executions_are_cumulative_and_within_the_order_size():
    o = P.list_vwap_orders(D, {}).iloc[0]
    ex = P.get_executions(D, o.id_server, o.id_target)
    assert ex.cum_qty.is_monotonic_increasing
    assert ex.cum_qty.iloc[-1] <= o["size"]


def test_qatt_has_the_columns_realized_curve_needs():
    q = P.get_qatt(D, S)
    assert {"tradeTime", "size"} <= set(q.columns) and len(q) > 0


def test_unknown_symbol_returns_empty_not_an_error():
    assert len(P.get_profile(D, "NOSUCH.XX")) == 0
    assert len(P.get_qatt(D, "NOSUCH.XX")) == 0
    assert P.get_open_print(D, "NOSUCH.XX") is None


def test_demo_data_flows_through_every_pure_module():
    """The end-to-end path the app takes, with no Streamlit involved."""
    prof = decode_profile(P.get_profile(D, S), S, D)
    order = P.list_vwap_orders(D, {"sym": S}).iloc[0]
    sched = build_schedule(prof, order,
                           P.get_executions(D, order.id_server, order.id_target),
                           P.get_target_state(D, order.id_server, order.id_target))
    real = realized_curve(P.get_qatt(D, S), prof, P.get_open_print(D, S))

    assert sched.expected_qty.iloc[-1] == pytest.approx(float(order["size"]))
    assert sched.filled_qty.iloc[-1] > 0
    assert real.cum_volume.iloc[-1] > 0
    assert real.cum_frac.iloc[-1] == pytest.approx(1.0)


def test_the_reserving_order_looks_behind_until_the_reserve_is_counted():
    prof_by_sym = {s: decode_profile(P.get_profile(D, s), s, D)
                   for s in P.list_symbols()}
    orders = P.list_vwap_orders(D, {})
    hits = []
    for _, o in orders.iterrows():
        states = P.get_target_state(D, o.id_server, o.id_target)
        if states["commit_close"].max() <= 0:
            continue
        s = build_schedule(prof_by_sym[o.sym], o,
                           P.get_executions(D, o.id_server, o.id_target), states)
        last = s.iloc[-1]
        hits.append((last.ahead_qty, last.filled_plus_committed, last.filled_qty))
    assert hits, "expected at least one reserving order"
    ahead, with_commit, filled = hits[0]
    assert ahead < 0
    assert with_commit > filled


def test_make_provider_falls_back_to_demo_without_a_connection():
    from core.provider import make_provider
    assert isinstance(make_provider(None), DemoProvider)
    assert isinstance(make_provider(object(), force_demo=True), DemoProvider)


def test_vwap_symbols_come_from_the_orders_actually_working():
    syms = P.list_vwap_symbols(D)
    orders = P.list_vwap_orders(D, {})
    assert syms == sorted(set(orders.sym))
    assert all(s in P.list_symbols() for s in syms)


def test_an_order_is_never_measured_against_another_symbols_profile():
    """Panel 2 scopes the order list to the symbol it holds a profile for."""
    for sym in P.list_vwap_symbols(D):
        scoped = P.list_vwap_orders(D, {"sym": sym})
        assert len(scoped) > 0
        assert set(scoped.sym) == {sym}
