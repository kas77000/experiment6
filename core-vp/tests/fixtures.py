"""The rows photographed for 000001.C2 on 2026.07.29, plus a plausible tail.

The header values and the first ten bucket values are exact, read off the
emailed qPad result. The tail is extended to a full Shenzhen session so the
cumulative curve reaches 1.0, which decode_profile requires.
"""
from __future__ import annotations

import pandas as pd

HEAD = [(0, 105156029.0), (1, 445700.0), (2, 799800.0), (3, 2000.0)]
PRE = [(540, 0.0), (550, 0.0), (560, 0.0), (565, 0.0), (568, 0.0), (569, 0.0)]
OBSERVED = [(570, 0.0), (571, 0.0216089), (572, 0.0380905), (580, 0.134472),
            (590, 0.222817), (600, 0.285873), (610, 0.341493), (620, 0.389694),
            (630, 0.428962), (640, 0.463602)]


def _tail():
    """650..690 then 780..900, rising smoothly from 0.463602 to 1.0."""
    mins = list(range(650, 700, 10)) + list(range(780, 910, 10))
    start, end = 0.463602, 1.0
    n = len(mins)
    return [(m, start + (end - start) * (i + 1) / n) for i, m in enumerate(mins)]


def raw_profile(cc0: bool = True) -> pd.DataFrame:
    rows = HEAD + PRE + OBSERVED + _tail()
    df = pd.DataFrame({
        "date": pd.Timestamp("2026-07-29").date(),
        "sym": "000001.C2",
        "time": [t for t, _ in rows],
        "vmed": [v for _, v in rows],
    })
    if cc0:
        df["cc0"] = [float(len(HEAD) + len(PRE))] + [0.0] * (len(df) - 1)
    return df


# --- 7203.JP on 2026-09-0? -----------------------------------------------
# Transcribed from the gateway result for `get_data_by_date[`profile;...]`.
# A Tokyo name: a 60-minute lunch, a large PM reopen auction, and one more
# pre-open row than the Shenzhen sample.
JP_HEAD = [(0, 17110800.0), (1, 1109400.0), (2, 5570500.0), (3, 247700.0)]
JP_PRE = [(450, 0.0), (460, 0.0), (470, 0.0), (475, 0.0), (478, 0.0),
          (479, 0.0), (480, 0.0)]
JP_BODY = [
    (481, 0.022515), (482, 0.038998), (490, 0.130115), (500, 0.207781),
    (510, 0.260936), (520, 0.300778), (530, 0.334088), (540, 0.367217),
    (550, 0.39882), (560, 0.428228), (570, 0.456119), (580, 0.482308),
    (590, 0.503572), (600, 0.522482), (610, 0.541178), (620, 0.559821),
    (630, 0.57841),
    (690, 0.57841),                      # lunch: 60 minutes, no volume
    (691, 0.586857), (692, 0.592787), (700, 0.623645), (710, 0.649343),
    (720, 0.67235), (730, 0.692777), (740, 0.712701), (750, 0.732652),
    (760, 0.751223), (770, 0.770456), (780, 0.789536), (790, 0.808187),
    (800, 0.828522), (810, 0.848276), (820, 0.868308), (830, 0.890806),
    (840, 0.91493), (850, 0.942629), (859, 0.972427), (860, 0.975855),
    (861, 0.979696), (862, 0.984017), (863, 0.988698), (864, 0.994013),
    (865, 1.0),
]


def raw_profile_jp(cc0: bool = False) -> pd.DataFrame:
    """7203.JP exactly as the gateway returned it (no cc0 column by default -
    the real request selected only date/sym/vmed/time)."""
    rows = JP_HEAD + JP_PRE + JP_BODY
    df = pd.DataFrame({
        "date": pd.Timestamp("2026-09-03").date(),
        "sym": "7203.JP",
        "time": [t for t, _ in rows],
        "vmed": [v for _, v in rows],
    })
    if cc0:
        df["cc0"] = [float(len(JP_HEAD) + len(JP_PRE) - 1)] + [0.0] * (len(df) - 1)
    return df
