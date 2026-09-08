"""Plotly figures, all on one shared minutes-of-day axis.

Colour follows the dataviz reference palette, dark steps, slots 1-3 only
(blue / orange / aqua) - the set documented as clearing every pair gate in both
modes. Nothing here needs a fourth series.

Two deliberate choices:

* Reference lines (even pace, average bucket) are muted grey and dashed, not a
  categorical hue. A reference is not a competing identity.

* The ahead/behind band is NEUTRAL, not red/green. Status colour would assert
  "behind = bad", which is the exact misreading this panel exists to prevent:
  an order reserving quantity for the close is behind on the filled line and
  perfectly on track. The sign is stated in the KPI text instead.

Lunch is a real gap. A NaN is inserted at the break so no line is drawn across
90 minutes in which nothing traded.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

# dataviz reference palette, dark steps
SERIES_1 = "#3987e5"   # blue    - the profile / the expected shape
SERIES_2 = "#d95926"   # orange  - what actually happened
SERIES_3 = "#199e70"   # aqua    - what happened including the reserve

SURFACE = "#1a1a19"
INK = "#ffffff"
INK_SECONDARY = "#c3c2b7"
MUTED = "#898781"
GRID = "#2c2c2a"
BASELINE = "#383835"
BAND = "rgba(137, 135, 129, 0.18)"
LUNCH = "rgba(137, 135, 129, 0.10)"

LINE_WIDTH = 2
MARKER_SIZE = 8


def clock(minute, offset_min: int = 0) -> str:
    m = (int(minute) + int(offset_min)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _gapped(minutes, values, session):
    """Insert a NaN across the lunch break so the line breaks instead of
    running flat through 90 minutes of no trading."""
    x = list(minutes)
    y = list(values)
    if session is None or session.lunch is None:
        return x, y
    lo, hi = session.lunch
    for i in range(len(x) - 1):
        if x[i] <= lo and x[i + 1] >= hi:
            return (x[:i + 1] + [(lo + hi) / 2] + x[i + 1:],
                    y[:i + 1] + [np.nan] + y[i + 1:])
    return x, y


def _layout(fig: go.Figure, title: str, ytitle: str, yfmt: str = ".0%",
            session=None, legend: bool = True, offset: int = 0) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=INK), x=0, xanchor="left"),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif',
                  color=INK_SECONDARY, size=12),
        margin=dict(l=64, r=16, t=44, b=76),
        hovermode="x unified",
        showlegend=legend,
        legend=dict(orientation="h", yanchor="top", y=-0.18, x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(color=INK_SECONDARY)),
        height=340,
    )
    ticks = _ticks(session)
    fig.update_xaxes(
        title=None, gridcolor=GRID, zeroline=False, linecolor=BASELINE,
        tickcolor=BASELINE, tickfont=dict(color=MUTED, size=11),
        tickvals=ticks, ticktext=[clock(t, offset) for t in ticks])
    fig.update_yaxes(
        title=dict(text=ytitle, font=dict(color=MUTED, size=11)),
        gridcolor=GRID, zeroline=False, linecolor=BASELINE,
        tickfont=dict(color=MUTED, size=11), tickformat=yfmt)
    return fig


def bar_widths(minutes, session) -> np.ndarray:
    """Each bar as wide as the time it covers.

    Buckets are labelled by the minute they close and are not evenly spaced -
    571 and 572 are one minute wide, the rest ten. Drawing them all the same
    width would make a one-minute bucket look like a ten-minute one, so the
    area of a bar would stop meaning anything.
    """
    m = np.asarray(minutes, dtype=float)
    if len(m) == 0:
        return np.array([])
    first_step = (m[1] - m[0]) if len(m) > 1 else 1.0
    previous = np.concatenate([[m[0] - first_step], m[:-1]])
    width = m - previous

    if session is not None and session.lunch is not None and len(m) > 1:
        # The first bucket after lunch has no predecessor within its own
        # session, so its span back to 11:30 is not trading time. Give it the
        # session's normal step rather than nothing.
        steps = np.diff(m)
        typical = float(np.median(steps[steps > 0])) if (steps > 0).any() else 1.0
        lo, hi = session.lunch
        width = np.where((m >= hi) & (previous <= lo), typical, width)

    return np.clip(width, 0.5, None) * 0.82


def _ticks(session):
    if session is None:
        return list(range(570, 961, 30))
    start = (session.open_min // 30) * 30
    end = session.close_min + 30
    return list(range(start, end + 1, 30))


def add_session_bands(fig: go.Figure, session) -> go.Figure:
    """Shade lunch. The auctions are marks in their own right, not bands."""
    if session is not None and session.lunch is not None:
        lo, hi = session.lunch
        fig.add_vrect(x0=lo, x1=hi, fillcolor=LUNCH, line_width=0, layer="below",
                      annotation_text="lunch", annotation_position="top left",
                      annotation_font=dict(color=MUTED, size=10))
    return fig


def even_pace(profile) -> tuple[list, list]:
    """A flat schedule: linear in TRADING time, so lunch does not accrue pace.

    kdbmonitor's dashboard used one step per bucket; buckets here are unevenly
    spaced (571, 572, then every 10 minutes), so time-linear is the honest
    benchmark and the one a VWAP order is actually measured against.
    """
    cont = profile.continuous
    minutes = cont["minute"].to_numpy(dtype=float)
    steps = np.diff(minutes, prepend=minutes[0])

    lunch = profile.session.lunch
    if lunch is not None:
        lo, hi = lunch
        previous = np.concatenate([[minutes[0]], minutes[:-1]])
        crossing = (minutes >= hi) & (previous <= lo)
        steps = np.where(crossing, steps - (hi - lo), steps)

    elapsed = np.cumsum(np.maximum(steps, 0.0))
    total = elapsed[-1] if elapsed[-1] > 0 else 1.0
    return list(minutes), list(elapsed / total)


# --------------------------------------------------------------- panel 1
def profile_figure(profile) -> go.Figure:
    cont = profile.continuous
    fig = go.Figure()

    ex, ey = even_pace(profile)
    ex, ey = _gapped(ex, ey, profile.session)
    fig.add_trace(go.Scatter(
        x=ex, y=ey, name="even pace", mode="lines", connectgaps=False,
        line=dict(color=MUTED, width=1.5, dash="dash"),
        hovertemplate="even pace %{y:.2%}<extra></extra>"))

    x, y = _gapped(cont["minute"], cont["cum_frac"], profile.session)
    fig.add_trace(go.Scatter(
        x=x, y=y, name="cumulated", mode="lines", connectgaps=False,
        line=dict(color=SERIES_1, width=LINE_WIDTH),
        hovertemplate="cumulated %{y:.2%}<extra></extra>"))

    _layout(fig, f"Cumulated volume - {profile.sym}", "share of continuous volume",
            session=profile.session, offset=profile.tz_offset_min)
    return add_session_bands(fig, profile.session)


def bucket_figure(profile) -> go.Figure:
    cont = profile.continuous
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=cont["minute"], y=cont["share"], name="this bucket",
        width=bar_widths(cont["minute"], profile.session),
        marker=dict(color=SERIES_1, line=dict(width=0)),
        hovertemplate="%{y:.2%}<extra></extra>"))

    # Park the label over the lunch gap, which is the only empty region.
    mean = float(cont["share"].mean())
    lunch = profile.session.lunch
    annotation = dict(text="average bucket", font=dict(color=MUTED, size=10),
                      yanchor="bottom")
    if lunch is not None:
        annotation |= dict(x=(lunch[0] + lunch[1]) / 2, xanchor="center")
    fig.add_hline(y=mean, line=dict(color=MUTED, width=1.5, dash="dash"),
                  annotation=annotation)

    _layout(fig, "Volume per bucket", "share of continuous volume",
            session=profile.session, legend=False,
            offset=profile.tz_offset_min)
    return add_session_bands(fig, profile.session)


# --------------------------------------------------------------- panel 2
def progression_figure(schedule: pd.DataFrame, order: pd.Series,
                       session=None, offset: int = 0) -> go.Figure:
    x = schedule["minute"].tolist()
    fig = go.Figure()

    # the divergence, drawn behind everything and deliberately colourless
    fig.add_trace(go.Scatter(
        x=x, y=schedule["expected_qty"], mode="lines", showlegend=False,
        line=dict(width=0), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=x, y=schedule["filled_qty"], mode="lines", showlegend=False,
        line=dict(width=0), fill="tonexty", fillcolor=BAND, hoverinfo="skip"))

    fig.add_trace(go.Scatter(
        x=x, y=schedule["expected_qty"], name="expected", mode="lines",
        line=dict(color=SERIES_1, width=LINE_WIDTH),
        hovertemplate="expected %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=x, y=schedule["filled_qty"], name="filled", mode="lines",
        line=dict(color=SERIES_2, width=LINE_WIDTH, shape="hv"),
        hovertemplate="filled %{y:,.0f}<extra></extra>"))

    if float(schedule["committed_qty"].max()) > 0:
        fig.add_trace(go.Scatter(
            x=x, y=schedule["filled_plus_committed"], name="filled + committed",
            mode="lines",
            line=dict(color=SERIES_3, width=LINE_WIDTH, dash="dot", shape="hv"),
            hovertemplate="filled + committed %{y:,.0f}<extra></extra>"))

    title = f"Order {order.get('id_target', '')} - {order.get('sym', '')} " \
            f"{order.get('side', '')} {float(order.get('size', 0)):,.0f}"
    _layout(fig, title, "shares", yfmt=",.0f", session=session, offset=offset)
    return add_session_bands(fig, session)


# --------------------------------------------------------------- panel 3
CUM_COLUMN = {"adv": "cum_of_adv", "day": "cum_frac"}
SHARE_COLUMN = {"adv": "share_of_adv", "day": "share"}
BASIS_LABEL = {"adv": "share of a median day", "day": "share of the day"}


def realized_figure(profile, realized: pd.DataFrame,
                    basis: str = "adv") -> go.Figure:
    """Profile against today, cumulated.

    `basis="adv"` measures both against a median day, so a heavy day ends above
    100% and the level is readable. `basis="day"` normalises today by its own
    total, which compares shape only - and forces both curves to meet at 100%,
    so the divergence at the close is zero by construction.
    """
    fig = go.Figure()
    cont = profile.continuous
    column = CUM_COLUMN.get(basis, "cum_of_adv")

    px_, py = _gapped(cont["minute"], cont["cum_frac"], profile.session)
    fig.add_trace(go.Scatter(
        x=px_, y=py, name="profile (median)", mode="lines", connectgaps=False,
        line=dict(color=SERIES_1, width=LINE_WIDTH),
        hovertemplate="profile %{y:.2%}<extra></extra>"))

    rx, ry = _gapped(realized["minute"], realized[column], profile.session)
    fig.add_trace(go.Scatter(
        x=rx, y=ry, name="today", mode="lines", connectgaps=False,
        line=dict(color=SERIES_2, width=LINE_WIDTH),
        hovertemplate="today %{y:.2%}<extra></extra>"))

    _layout(fig, "Profile vs today - cumulated", BASIS_LABEL.get(basis, ""),
            session=profile.session, offset=profile.tz_offset_min)
    return add_session_bands(fig, profile.session)


def realized_bucket_figure(profile, realized: pd.DataFrame,
                           basis: str = "adv") -> go.Figure:
    cont = profile.continuous
    column = SHARE_COLUMN.get(basis, "share_of_adv")
    widths = bar_widths(cont["minute"], profile.session)

    # Paired, with a gap between the two fills rather than a shared edge.
    paired = widths / 2 * 0.88

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=cont["minute"] - widths / 4, y=cont["share"], name="profile (median)",
        width=paired,
        marker=dict(color=SERIES_1, line=dict(width=0)),
        hovertemplate="profile %{y:.2%}<extra></extra>"))
    fig.add_trace(go.Bar(
        x=realized["minute"] + widths / 4, y=realized[column], name="today",
        width=paired,
        marker=dict(color=SERIES_2, line=dict(width=0)),
        hovertemplate="today %{y:.2%}<extra></extra>"))

    _layout(fig, "Profile vs today - per bucket", BASIS_LABEL.get(basis, ""),
            session=profile.session, offset=profile.tz_offset_min)
    fig.update_layout(barmode="overlay")
    return add_session_bands(fig, profile.session)
