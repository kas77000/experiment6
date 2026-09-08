"""Today's realised volume, bucketed onto the profile's own grid.

Follows getsymprof_realRT: a trade belongs to the first grid minute at or after
it, and the opening auction print is subtracted from whichever bucket contains
it and seated in the first bucket instead, so the auction is not counted twice
into the continuous curve.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.profile import Profile
from core.schedule import to_minute

TIME_COLUMNS = ("tradeTime", "time", "t_algo")
SIZE_COLUMNS = ("size", "fillsize")


def _pick(frame: pd.DataFrame, candidates) -> str | None:
    for c in candidates:
        if c in frame.columns:
            return c
    return None


def realized_curve(qatt: pd.DataFrame, profile: Profile,
                   open_print: tuple[int, float] | None = None) -> pd.DataFrame:
    """Realised volume per profile bucket, cumulative, and normalised."""
    cont = profile.continuous
    grid = cont["minute"].astype("int64").to_numpy()
    volume = np.zeros(len(grid), dtype=float)

    if qatt is not None and len(qatt):
        tcol = _pick(qatt, TIME_COLUMNS)
        scol = _pick(qatt, SIZE_COLUMNS)
        if tcol is not None and scol is not None:
            f = qatt[[tcol, scol]].copy()
            f["_m"] = f[tcol].map(to_minute)
            f = f.dropna(subset=["_m", scol])
            f = f[f[scol] > 0]
            if len(f):
                pos = np.searchsorted(grid, f["_m"].to_numpy(dtype="int64"),
                                      side="left")
                keep = pos < len(grid)
                np.add.at(volume, pos[keep], f[scol].to_numpy(dtype=float)[keep])

    if open_print is not None:
        op_minute, op_size = open_print
        pos = int(np.searchsorted(grid, int(op_minute), side="left"))
        if pos < len(grid):
            volume[pos] -= float(op_size)
        volume[0] = float(op_size)
        volume = np.maximum(volume, 0.0)

    cum = volume.cumsum()
    total = float(cum[-1]) if len(cum) else 0.0
    adv = float(profile.adv)

    # Two normalisations, because they answer different questions.
    #
    #   cum_frac    share of the day's OWN volume - compares shape, but both
    #               curves are forced to 100% at the close, so the divergence
    #               at the end is always zero by construction.
    #   cum_of_adv  share of a MEDIAN day - a heavy day ends above 100%, so
    #               level and shape are both readable, and an intraday curve
    #               simply stops where it has got to.
    return pd.DataFrame({
        "minute": grid,
        "clock": cont["clock"].to_numpy(),
        "volume": volume,
        "cum_volume": cum,
        "share": volume / total if total > 0 else np.nan,
        "cum_frac": cum / total if total > 0 else np.nan,
        "share_of_adv": volume / adv if adv > 0 else np.nan,
        "cum_of_adv": cum / adv if adv > 0 else np.nan,
    })
