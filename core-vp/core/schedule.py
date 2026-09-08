"""The order's expected curve, and what it actually did.

Three actual series, because two of them are routinely confused:

    filled                 execution.cum_qty                where the order is
    committed              target_state.commit_open
                             + commit_close                 reserved for auctions
    filled_plus_committed  the sum                          including the reserve

A VWAP order reserving quantity for the close reads as behind schedule on a
naive filled-vs-expected chart while doing exactly what it was told. The gap
between the second and third series is that reserve, made visible instead of
left to be misread as slippage.

execution.cum_qty is already cumulative per fill, so `filled` is a step line off
one column - exact, and needing no re-aggregation. target_state.make moves only
on state changes and so sits flat between fills; it is the cross-check, not the
primary.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from core.profile import PHASE_CLOSE, PHASE_OPEN, Profile


def to_minute(value) -> int | None:
    """Minutes-of-day from whatever kdb handed back, or None."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, pd.Timedelta):
        return int(value.total_seconds() // 60)
    if isinstance(value, dt.datetime):
        return value.hour * 60 + value.minute
    if isinstance(value, dt.time):
        return value.hour * 60 + value.minute
    if isinstance(value, dt.timedelta):
        return int(value.total_seconds() // 60)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flag(order: pd.Series, name: str) -> bool:
    """A kdb 0/1 flag, defaulting to on when absent or null."""
    value = order.get(name, 1)
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return True


def _step_series(frame: pd.DataFrame, time_col: str, value_cols: list[str],
                 minutes: list[int]) -> pd.DataFrame:
    """Last value at or before each grid minute, held flat in between."""
    zeros = pd.DataFrame(
        {c: np.zeros(len(minutes), dtype=float) for c in value_cols})
    if frame is None or len(frame) == 0 or time_col not in frame.columns:
        return zeros

    f = frame.copy()
    f["_m"] = f[time_col].map(to_minute)
    f = f.dropna(subset=["_m"])
    if len(f) == 0:
        return zeros
    f["_m"] = f["_m"].astype("int64")

    present = [c for c in value_cols if c in f.columns]
    if not present:
        return zeros

    grouped = f.sort_values("_m").groupby("_m")[present].last()
    idx = grouped.index.to_numpy(dtype="int64")
    grid = np.asarray(minutes, dtype="int64")
    pos = np.searchsorted(idx, grid, side="right") - 1

    out = zeros
    for c in present:
        vals = grouped[c].astype(float).to_numpy()
        out[c] = np.where(pos >= 0, vals[np.clip(pos, 0, len(vals) - 1)], 0.0)
    return out


def build_schedule(profile: Profile, order: pd.Series,
                   executions: pd.DataFrame,
                   states: pd.DataFrame) -> pd.DataFrame:
    """Expected vs filled vs filled-plus-committed, on the profile's grid."""
    size = float(order.get("size", 0) or 0)

    b = profile.buckets.copy()
    if not _flag(order, "doopen"):
        b = b[b.phase != PHASE_OPEN]
    if not _flag(order, "doclose"):
        b = b[b.phase != PHASE_CLOSE]

    lo = to_minute(order.get("t_start"))
    hi = to_minute(order.get("t_end"))
    if lo is not None:
        b = b[b.minute >= lo]
    if hi is not None:
        b = b[b.minute <= hi]
    if len(b) == 0:
        raise ValueError("the order's window selects no profile buckets")

    b = b.sort_values("minute").reset_index(drop=True)
    total = float(b["share_of_day"].sum())
    if total <= 0:
        raise ValueError("the order's window carries no expected volume")
    b["expected_qty"] = (b["share_of_day"] / total).cumsum() * size

    minutes = b["minute"].astype(int).tolist()
    filled = _step_series(executions, "time", ["cum_qty"], minutes)["cum_qty"]
    commit = _step_series(states, "t_algo",
                          ["commit_open", "commit_close"], minutes)

    b["filled_qty"] = filled.to_numpy()
    b["committed_qty"] = (commit["commit_open"] + commit["commit_close"]).to_numpy()
    b["filled_plus_committed"] = b["filled_qty"] + b["committed_qty"]
    b["ahead_qty"] = b["filled_qty"] - b["expected_qty"]

    return b[["minute", "clock", "phase", "expected_qty", "filled_qty",
              "committed_qty", "filled_plus_committed", "ahead_qty"]]
