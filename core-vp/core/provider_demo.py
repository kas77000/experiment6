"""Synthetic data, so the app runs and is testable with no kdb and no pykx.

The header values for 000001.C2 are the ones photographed from the emailed
result on 2026.07.29, so the demo profile has the real magnitudes rather than
invented ones. The session is Shenzhen-shaped: 09:30-11:30, 13:00-15:00, with
auctions at each end and a PM reopen after lunch.

The four orders are chosen to show the four readings the app has to make
legible: ahead, on schedule, behind, and reserving quantity for the close.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from core.provider import DataProvider

SEED = 20260729

MORNING = [570, 571, 572] + list(range(580, 700, 10))   # 09:30 - 11:30
# Shanghai/Shenzhen trade continuously to 14:57, then auction 14:57-15:00,
AFTERNOON = list(range(780, 900, 10)) + [897]            # 13:00 - 14:57
GRID = MORNING + AFTERNOON
PRE_OPEN = [540, 550, 560, 565, 568, 569]

# adv, open auction, close auction, PM reopen auction
HEADERS = {
    "000001.C2": (105156029.0, 445700.0, 799800.0, 2000.0),
    "600519.C1": (3120400.0, 21800.0, 48600.0, 900.0),
    "000858.C2": (28450900.0, 118200.0, 244100.0, 1500.0),
}


def _cumulative(rng: np.random.Generator) -> np.ndarray:
    """A U-shaped intraday curve, returned cumulative and ending at 1.0."""
    t = np.array(GRID[1:], dtype=float)
    open_min, close_min = float(GRID[0]), float(GRID[-1])
    w = (1.0
         + 2.4 * np.exp(-(t - open_min) / 25.0)      # the open is busy
         + 1.8 * np.exp(-(close_min - t) / 35.0))    # so is the close
    w = w * (1.0 + 0.10 * rng.standard_normal(len(t)))
    w[t >= 780] *= 1.15                              # the afternoon reopen
    w = np.clip(w, 0.05, None)
    cum = np.cumsum(w) / w.sum()
    return np.concatenate([[0.0], cum])


class DemoProvider(DataProvider):
    label = "demo data"

    def __init__(self, today: dt.date | None = None):
        self._today = today or dt.date(2026, 9, 4)
        self._rng = np.random.default_rng(SEED)
        self._profiles = {s: _cumulative(np.random.default_rng(SEED + i))
                          for i, s in enumerate(HEADERS)}

    # ------------------------------------------------------------------ meta
    def available_dates(self) -> list[dt.date]:
        out, d = [], self._today
        while len(out) < 5:
            if d.weekday() < 5:
                out.append(d)
            d -= dt.timedelta(days=1)
        return sorted(out)

    def list_symbols(self) -> list[str]:
        return list(HEADERS)

    # --------------------------------------------------------------- profile
    def get_profile(self, date: dt.date, sym: str) -> pd.DataFrame:
        if sym not in HEADERS:
            return pd.DataFrame(columns=["date", "sym", "time", "vmed", "cc0"])
        adv, v_open, v_close, v_pm = HEADERS[sym]
        cum = self._profiles[sym]

        times = [0, 1, 2, 3] + PRE_OPEN + GRID
        vmed = [adv, v_open, v_close, v_pm] + [0.0] * len(PRE_OPEN) + list(cum)
        skip = 4 + len(PRE_OPEN)

        return pd.DataFrame({
            "date": [date] * len(times),
            "sym": sym,
            "time": times,
            "vmed": vmed,
            "cc0": [float(skip)] + [0.0] * (len(times) - 1),
        })

    # ---------------------------------------------------------------- orders
    def _orders(self, date: dt.date) -> pd.DataFrame:
        rows = [
            # id_target, sym, side, size, behaviour, t_start, t_end
            (1001, "000001.C2", "buy", 4_000_000, "ahead", None, None),
            (1002, "000001.C2", "sell", 2_500_000, "on_schedule", None, None),
            (1003, "600519.C1", "buy", 180_000, "behind",
             pd.Timedelta(minutes=600), pd.Timedelta(minutes=880)),
            (1004, "000858.C2", "buy", 900_000, "reserve_close", None, None),
        ]
        return pd.DataFrame([{
            "date": date,
            "id_server": 7,
            "id_target": t,
            "trader": ["AOKI", "CHEN", "SY", "MORGAN"][i],
            "basket": ["ARROWST01", "ARROWST01", "MANUAL", "ARROWST02"][i],
            "sym": sym,
            "side": side,
            "size": size,
            "algo": "VWAP",
            "alpha": [1.0, 0.6, 1.4, 1.0][i],
            "t_start": t0,
            "t_end": t1,
            "doopen": 1,
            "doclose": 1,
            "behaviour": how,
        } for i, (t, sym, side, size, how, t0, t1) in enumerate(rows)])

    def list_vwap_orders(self, date: dt.date, filters: dict) -> pd.DataFrame:
        o = self._orders(date)
        for key in ("sym", "trader", "basket"):
            want = (filters or {}).get(key)
            if want and want != "All":
                o = o[o[key] == want]
        return o.drop(columns=["behaviour"]).reset_index(drop=True)

    def _order_row(self, date, id_server, id_target):
        o = self._orders(date)
        hit = o[(o.id_target == int(id_target)) & (o.id_server == int(id_server))]
        return None if len(hit) == 0 else hit.iloc[0]

    def _pace(self, order) -> tuple[np.ndarray, np.ndarray]:
        """Grid minutes and the cumulative fraction filled at each."""
        cum = self._profiles[order.sym]
        minutes = np.array(GRID, dtype=int)
        how = order.behaviour
        if how == "ahead":
            pace = np.clip(cum ** 0.72, 0, 1)
        elif how == "behind":
            pace = np.clip(cum ** 1.6, 0, 1)
        elif how == "reserve_close":
            # works two thirds through the day and holds the rest for the close
            pace = np.clip(cum, 0, 1) * (2.0 / 3.0)
        else:
            pace = np.clip(cum, 0, 1)
        return minutes, pace

    def get_executions(self, date, id_server, id_target) -> pd.DataFrame:
        order = self._order_row(date, id_server, id_target)
        if order is None:
            return pd.DataFrame(columns=["time", "cum_qty", "fillprice", "fillsize"])
        minutes, pace = self._pace(order)
        qty = np.round(pace * float(order["size"])).astype("int64")
        keep = qty > 0
        minutes, qty = minutes[keep], qty[keep]
        price = 12.40 + 0.02 * np.cumsum(
            np.random.default_rng(SEED + int(id_target)).standard_normal(len(qty)))
        return pd.DataFrame({
            "time": [pd.Timedelta(minutes=int(m)) for m in minutes],
            "cum_qty": qty,
            "fillsize": np.diff(qty, prepend=0),
            "fillprice": np.round(price, 3),
        })

    def get_target_state(self, date, id_server, id_target) -> pd.DataFrame:
        order = self._order_row(date, id_server, id_target)
        if order is None:
            return pd.DataFrame(columns=["t_algo", "commit_open", "commit_close",
                                         "make"])
        minutes, pace = self._pace(order)
        size = float(order["size"])
        commit_close = np.zeros(len(minutes), dtype=float)
        if order.behaviour == "reserve_close":
            # the reserve appears once the afternoon session opens
            commit_close[np.array(minutes) >= 780] = round(size / 3.0)
        return pd.DataFrame({
            "t_algo": [pd.Timedelta(minutes=int(m)) for m in minutes],
            "commit_open": np.zeros(len(minutes), dtype=float),
            "commit_close": commit_close,
            "make": np.round(pace * size),
        })

    # ----------------------------------------------------------- market data
    def get_qatt(self, date: dt.date, sym: str) -> pd.DataFrame:
        if sym not in HEADERS:
            return pd.DataFrame(columns=["tradeTime", "size", "price"])
        adv, v_open, _, _ = HEADERS[sym]
        cum = self._profiles[sym]
        rng = np.random.default_rng(SEED + len(sym))

        # the day runs ~15% heavy in the morning and settles back by the close
        share = np.diff(cum, prepend=0.0)
        tilt = np.where(np.array(GRID) < 690, 1.15, 0.95)
        volume = share * tilt * adv

        rows = []
        for minute, vol in zip(GRID, volume):
            if vol <= 0:
                continue
            parts = rng.dirichlet(np.ones(3)) * vol
            for part in parts:
                rows.append((minute, float(part)))
        frame = pd.DataFrame(rows, columns=["_m", "size"])
        # the opening auction print, which realized_curve re-seats
        frame = pd.concat([pd.DataFrame([(571, float(v_open))],
                                        columns=["_m", "size"]), frame])
        frame["tradeTime"] = [pd.Timedelta(minutes=int(m)) for m in frame["_m"]]
        frame["price"] = np.round(
            12.40 + 0.02 * rng.standard_normal(len(frame)), 3)
        return frame.drop(columns=["_m"]).reset_index(drop=True)

    def get_open_print(self, date: dt.date, sym: str) -> tuple[int, float] | None:
        if sym not in HEADERS:
            return None
        return (571, HEADERS[sym][1])
