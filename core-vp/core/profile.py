"""Decode the VPROF `vst` rows into a usable profile.

Row layout, per idxprof.q:37-42:

    time=0    adv       median daily continuous volume
    time=1    vopen     open auction volume
    time=2    vclose    close auction volume
    time=3    vopenpm   PM reopen auction volume (lunch-break markets)
    time>=100           minutes-of-day; vmed is a CUMULATIVE fraction

getsymprof takes `deltas` of vmed, which is what establishes it as cumulative
rather than per-bucket.

Two departures from the q code, both deliberate:

1.  The header-row count is read from `cc0` on row 0 (load_equity_special.q:128)
    rather than hard-coded. getsymprof's `n:10` and idxprof's `11_` do not
    survive a symbol with a different number of pre-open rows.

2.  `vtot` includes `v_open_pm`. getsymprof sums only adv + open + close, so
    for a lunch-break name its shares total slightly over 1. See the README.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from core.session import Session, derive_session

MIN_BUCKET_MINUTE = 100
CUM_TOLERANCE = 0.01

ROW_ADV, ROW_OPEN, ROW_CLOSE, ROW_OPEN_PM = 0, 1, 2, 3

PHASE_OPEN = "open auction"
PHASE_CONTINUOUS = "continuous"
PHASE_PM = "pm auction"
PHASE_CLOSE = "close auction"


class ProfileError(ValueError):
    """The profile rows cannot be decoded into a usable curve."""


@dataclass(frozen=True)
class Profile:
    sym: str
    date: dt.date
    adv: float
    v_open: float
    v_close: float
    v_open_pm: float
    buckets: pd.DataFrame
    session: Session
    tz_offset_min: int = 0
    tz_label: str = ""

    @property
    def vtot(self) -> float:
        return self.adv + self.v_open + self.v_close + self.v_open_pm

    @property
    def continuous(self) -> pd.DataFrame:
        return self.buckets[self.buckets.phase == PHASE_CONTINUOUS]


def clock(minute, offset_min: int = 0) -> str:
    """A bucket minute as a wall clock, optionally shifted to local market time.

    DISPLAY ONLY. `minute` itself always stays on the region clock (HKT), which
    is what the profile, qatt and the order tables all share.
    """
    m = (int(minute) + int(offset_min)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _header_skip(raw: pd.DataFrame) -> int:
    """Where the buckets start: cc0 if the gateway returned it, else derived."""
    if "cc0" in raw.columns and len(raw):
        try:
            n = int(raw["cc0"].iloc[0])
            if 0 < n < len(raw):
                return n
        except (TypeError, ValueError):
            pass
    mask = (raw["time"] >= MIN_BUCKET_MINUTE).to_numpy()
    if not mask.any():
        raise ProfileError(
            f"no bucket rows: every `time` is below {MIN_BUCKET_MINUTE}")
    return int(np.argmax(mask))


def decode_profile(raw: pd.DataFrame, sym: str, date: dt.date,
                   tz_offset_min: int = 0, tz_label: str = "",
                   auctions: tuple | None = None) -> Profile:
    """Decode the rows. `auctions` is (open, close) print minutes on the
    region clock; omit it and the auctions are drawn beside the session."""
    if raw is None or len(raw) == 0:
        raise ProfileError(f"no rows returned for {sym} on {date}")

    raw = raw.sort_values("time").reset_index(drop=True)

    head = raw[raw["time"] < MIN_BUCKET_MINUTE]
    head = head.drop_duplicates(subset="time").set_index("time")["vmed"]
    missing = [r for r in (ROW_ADV, ROW_OPEN, ROW_CLOSE) if r not in head.index]
    if missing:
        raise ProfileError(
            f"missing header row(s) {missing} for {sym} on {date}; expected "
            "time=0/1/2 to carry adv / open auction / close auction")

    adv = float(head.get(ROW_ADV, 0.0))
    v_open = float(head.get(ROW_OPEN, 0.0))
    v_close = float(head.get(ROW_CLOSE, 0.0))
    v_open_pm = float(head.get(ROW_OPEN_PM, 0.0))

    body = raw.iloc[_header_skip(raw):]
    body = body[body["time"] >= MIN_BUCKET_MINUTE]

    # Drop the leading pre-open rows but keep the last one: it is the session
    # open, where the cumulative curve legitimately stands at zero. getsymprof
    # keeps exactly this row too, which is why its `n:10` lands on 09:30.
    positive = np.flatnonzero(body["vmed"].to_numpy() > 0.0)
    if len(positive) == 0:
        raise ProfileError(f"every bucket is zero for {sym} on {date}")
    body = body.iloc[max(0, int(positive[0]) - 1):]

    if len(body) < 2:
        raise ProfileError(
            f"only {len(body)} bucket(s) for {sym} on {date}; cannot form a curve")

    minutes = body["time"].astype("int64").tolist()
    cum = body["vmed"].astype(float).to_numpy()

    if np.any(np.diff(cum) < -1e-12):
        raise ProfileError(
            f"vmed is not non-decreasing for {sym} on {date}; it is read as a "
            "cumulative fraction, so a fall means the rows are not a profile")
    if abs(cum[-1] - 1.0) > CUM_TOLERANCE:
        raise ProfileError(
            f"vmed does not reach 1.0 for {sym} on {date} (ends at {cum[-1]:.4f})")

    session = derive_session(minutes, v_open_pm)

    share = np.diff(cum, prepend=cum[0])
    share[0] = 0.0

    vtot = adv + v_open + v_close + v_open_pm
    if vtot <= 0:
        raise ProfileError(f"total volume is {vtot} for {sym} on {date}")

    cont = pd.DataFrame({
        "minute": minutes,
        "phase": PHASE_CONTINUOUS,
        "cum_frac": cum,
        "share": share,
        "share_of_day": share * (adv / vtot),
    })

    uniq = sorted(set(minutes))
    step = int(np.median(np.diff(uniq))) if len(uniq) > 1 else 1
    step = max(step, 1)

    auction_open, auction_close = auctions or (None, None)
    notes: list[str] = []

    def _seat(given, ok: bool, fallback: int, what: str) -> int:
        """The stated auction minute when it is consistent with the session we
        derived from the data, otherwise the bracketing position and a note."""
        if given is None:
            return fallback
        if ok:
            return int(given)
        notes.append(
            f"{what} auction is listed at {clock(given)} but the profile's "
            f"session does not agree; showing it beside the session instead")
        return fallback

    m_open = _seat(auction_open, auction_open is not None
                   and auction_open <= session.open_min,
                   session.open_min - step, "open")
    extras = [{"minute": m_open, "phase": PHASE_OPEN, "cum_frac": np.nan,
               "share": np.nan, "share_of_day": v_open / vtot}]

    if session.lunch is not None:
        # The afternoon reopen IS the end of the lunch gap - the rows say so,
        # no lookup needed.
        extras.append({"minute": session.lunch[1], "phase": PHASE_PM,
                       "cum_frac": np.nan, "share": np.nan,
                       "share_of_day": v_open_pm / vtot})

    m_close = _seat(auction_close, auction_close is not None
                    and auction_close >= session.close_min,
                    session.close_min + step, "close")
    extras.append({"minute": m_close, "phase": PHASE_CLOSE, "cum_frac": np.nan,
                   "share": np.nan, "share_of_day": v_close / vtot})

    if notes:
        session = replace(session, warnings=session.warnings + tuple(notes))

    buckets = pd.concat([cont, pd.DataFrame(extras)], ignore_index=True)
    buckets = buckets.sort_values("minute").reset_index(drop=True)
    buckets["cum_of_day"] = buckets["share_of_day"].cumsum()
    buckets["clock"] = buckets["minute"].map(
        lambda m: clock(m, tz_offset_min))
    buckets = buckets[["minute", "clock", "phase", "cum_frac", "share",
                       "share_of_day", "cum_of_day"]]

    return Profile(sym=sym, date=date, adv=adv, v_open=v_open, v_close=v_close,
                   v_open_pm=v_open_pm, buckets=buckets, session=session,
                   tz_offset_min=int(tz_offset_min), tz_label=tz_label)
