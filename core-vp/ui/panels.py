"""The three panels.

Each one catches its own failures. Three endpoints answer this page and they
fail independently, so a dead qatt server must grey its own panel and leave the
other two working rather than taking the page down.

A gap is a gap: an unavailable number shows an em dash with the reason, never a
zero that reads as real.
"""
from __future__ import annotations

import datetime as dt
import traceback

import pandas as pd
import streamlit as st

from core.markets import (auction_minutes, display_offset_minutes,
                          zone_label)
from core.profile import ProfileError, decode_profile
from core.realized import realized_curve
from core.schedule import build_schedule
from ui import charts, tables

DASH = "—"


LAST_TRACEBACKS: dict[str, str] = {}


def guarded(label: str, fn, *args, **kwargs):
    """Run a provider call. Returns (value, error_message).

    The traceback is kept in LAST_TRACEBACKS so a panel can offer it. A one
    line summary names the exception but not the frame that raised it, and for
    an error coming out of a library that is the only part that identifies it.
    """
    try:
        return fn(*args, **kwargs), None
    except Exception as exc:  # noqa: BLE001
        LAST_TRACEBACKS[label] = traceback.format_exc()
        return None, f"{label}: {type(exc).__name__}: {exc}"


def show_error(message: str, label: str) -> None:
    """The message, with the traceback one click away."""
    st.error(message)
    detail = LAST_TRACEBACKS.get(label)
    if detail:
        with st.expander("Full traceback", expanded=False):
            st.code(detail, language="text")


def qty(value) -> str:
    if value is None or pd.isna(value):
        return DASH
    value = float(value)
    if abs(value) < 0.5:        # never render a rounding artefact as "-0"
        return "0"
    return f"{value:,.0f}"


def qty_compact(value) -> str:
    """Big numbers for a metric tile, which truncates anything long."""
    if value is None or pd.isna(value):
        return DASH
    value = float(value)
    for divisor, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= divisor:
            return f"{value / divisor:,.1f}{suffix}"
    return f"{value:,.0f}"


def pct(value) -> str:
    if value is None or pd.isna(value):
        return DASH
    return f"{float(value):.2%}"


# ------------------------------------------------------------------ panel 1
def profile_panel(profile) -> None:
    st.subheader("Volume profile")

    for warning in profile.session.warnings:
        st.warning(warning)

    cols = st.columns(6)
    cols[0].metric("ADV (continuous)", qty_compact(profile.adv),
                   help=f"{qty(profile.adv)} shares")
    cols[1].metric("Open auction", qty_compact(profile.v_open),
                   help=f"{qty(profile.v_open)} shares")
    cols[2].metric("Close auction", qty_compact(profile.v_close),
                   help=f"{qty(profile.v_close)} shares")
    cols[3].metric("PM auction",
                   qty_compact(profile.v_open_pm)
                   if profile.session.has_pm_auction else DASH,
                   help="Volume of the afternoon reopen auction (time=3)")
    cols[4].metric("Buckets", f"{len(profile.continuous):,}")
    cols[5].metric("Busiest bucket", pct(profile.continuous["share"].max()))

    st.plotly_chart(charts.profile_figure(profile), use_container_width=True)
    st.plotly_chart(charts.bucket_figure(profile), use_container_width=True)

    with st.expander("Buckets", expanded=False):
        st.dataframe(
            tables.bucket_table(profile), use_container_width=True,
            hide_index=True,
            column_config={
                "Cumulated": st.column_config.NumberColumn(format="%.2f%%"),
                "This bucket": st.column_config.NumberColumn(format="%.2f%%"),
                "Even pace": st.column_config.NumberColumn(format="%.2f%%"),
                "Share of day": st.column_config.NumberColumn(format="%.2f%%"),
            })


# ------------------------------------------------------------------ panel 2
def progression_panel(provider, profile, date: dt.date, filters: dict) -> None:
    st.subheader("Order progression")

    # The schedule is built from THIS symbol's profile, so the list must not
    # offer an order for another one.
    scoped = dict(filters or {}, sym=profile.sym)
    orders, err = guarded("target", provider.list_vwap_orders, date, scoped)
    if err:
        st.warning(f"VWAP orders unavailable {DASH} {err}")
        return
    if orders is None or len(orders) == 0:
        st.info(f"No VWAP orders on {profile.sym} on {date} for this filter.")
        return

    labels = [tables.order_label(o) for _, o in orders.iterrows()]
    chosen = st.selectbox("Order", labels, key="order_choice")
    order = orders.iloc[labels.index(chosen)]

    execs, e1 = guarded("execution", provider.get_executions, date,
                        order["id_server"], order["id_target"])
    states, e2 = guarded("target_state", provider.get_target_state, date,
                         order["id_server"], order["id_target"])
    for problem in (e1, e2):
        if problem:
            st.warning(problem)
    execs = execs if execs is not None else pd.DataFrame()
    states = states if states is not None else pd.DataFrame()

    try:
        schedule = build_schedule(profile, order, execs, states)
    except ValueError as exc:
        st.warning(f"Cannot build a schedule for this order: {exc}")
        return

    last = schedule.iloc[-1]
    size = float(order["size"])
    reserved = float(schedule["committed_qty"].max())

    ahead = float(last.ahead_qty)
    if abs(ahead) < 0.5:
        stance = "on schedule"
    else:
        stance = "ahead" if ahead > 0 else "behind"

    cols = st.columns(5)
    cols[0].metric("Order size", qty(size))
    cols[1].metric("Filled", qty(last.filled_qty),
                   help=f"{pct(last.filled_qty / size) if size else DASH} of the order")
    cols[2].metric("Schedule says", qty(last.expected_qty))
    cols[3].metric("Ahead / behind", qty(ahead), help=f"The order is {stance}.")
    cols[4].metric("Reserved for auctions", qty(reserved) if reserved else DASH,
                   help="commit_open + commit_close: quantity the algo is "
                        "holding back for the auctions rather than working.")
    st.caption(f"Filled {pct(last.filled_qty / size) if size else DASH} of the "
               f"order and currently **{stance}**.")

    if reserved > 0 and last.ahead_qty < 0:
        st.info(
            f"This order is {qty(-last.ahead_qty)} behind the filled line while "
            f"holding {qty(reserved)} for the auctions. Counting the reserve it "
            f"stands at {qty(last.filled_plus_committed)} of {qty(size)}.")

    st.plotly_chart(
        charts.progression_figure(schedule, order, profile.session,
                                  profile.tz_offset_min),
        use_container_width=True)


# ------------------------------------------------------------------ panel 3
def realized_panel(provider, profile, date: dt.date) -> None:
    st.subheader("Profile vs today")

    ticks, err = guarded("qatt", provider.get_qatt, date, profile.sym)
    if err:
        st.warning(f"Market data unavailable {DASH} {err}")
        return
    if ticks is None or len(ticks) == 0:
        st.info(f"No qatt rows for {profile.sym} on {date}.")
        return

    open_print, _ = guarded("open_print", provider.get_open_print, date,
                            profile.sym)
    realized = realized_curve(ticks, profile, open_print)

    basis = st.radio(
        "Measure both against", ["a median day (ADV)", "the day's own volume"],
        horizontal=True, key="basis",
        help="Normalising today by its own total compares shape only, and "
             "forces both curves to meet at 100% - so the gap at the close is "
             "always zero. Against ADV, a heavy day ends above 100%.")
    key = "adv" if basis.startswith("a median") else "day"

    traded = float(realized["cum_volume"].iloc[-1])
    cols = st.columns(3)
    cols[0].metric("Traded so far", qty_compact(traded),
                   help=f"{qty(traded)} shares")
    cols[1].metric("vs ADV", pct(traded / profile.adv) if profile.adv else DASH)

    column = charts.CUM_COLUMN[key]
    merged = profile.continuous[["minute", "cum_frac"]].merge(
        realized[["minute", column]], on="minute")
    live = merged.dropna()
    drift = (live[column] - live["cum_frac"]).iloc[-1] if len(live) else None
    stance = ("ahead of the profile" if (drift or 0) >= 0
              else "behind the profile")
    cols[2].metric("Day vs profile", pct(drift), help=f"The day is {stance}.")

    st.plotly_chart(charts.realized_figure(profile, realized, key),
                    use_container_width=True)
    st.plotly_chart(charts.realized_bucket_figure(profile, realized, key),
                    use_container_width=True)


# ------------------------------------------------------------------- shared
def load_profile(provider, date: dt.date, sym: str):
    """Decode the profile, or return the reason it could not be decoded."""
    raw, err = guarded(
        "profile", provider.get_profile, date, sym)
    if err:
        return None, err
    # The gateway and qatt both report on the region clock (HKT). Shifting is
    # display only: `minute` stays region time everywhere, so the profile, qatt
    # and the order tables still share one axis and join without conversion.
    try:
        return decode_profile(raw, sym, date,
                              tz_offset_min=display_offset_minutes(sym, date),
                              tz_label=zone_label(sym, date),
                              auctions=auction_minutes(sym, date)), None
    except ProfileError as exc:
        return None, str(exc)
