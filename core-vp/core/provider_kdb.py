"""The real backend. Builds q, sends it down the right handle, returns frames.

pykx is never imported here - KdbClient does that lazily - so this module
imports cleanly on a machine without it, which is what makes the query-building
testable with a fake client.

Two things this module is careful about:

* `date` is constrained first in every query against a partitioned table. It is
  the single most important performance rule in a partitioned kdb+ db.
* qatt goes to the market endpoint, never the order server. Sent to the wrong
  handle it returns nothing rather than raising.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from core.connections import (Connection, KdbClient, profile_call,
                             profile_call_repr, resolve_kind)
from core.provider import DataProvider

ORDER_SELECT = ("date,id_server,id_target,trader,basket,sym,side,size,algo,"
                "alpha,t_start,t_end,doopen,doclose")


def qdate(d: dt.date) -> str:
    return f"{d:%Y.%m.%d}"


class KdbProvider(DataProvider):
    def __init__(self, conn: Connection, today: dt.date | None = None):
        self.conn = conn
        self._today = today
        self._profile_client = None
        self._oms_clients: dict[str, KdbClient] = {}
        self._md_clients: dict[str, KdbClient] = {}

    @property
    def label(self) -> str:
        return f"{self.conn.name} ({self.conn.profile_table})"

    # -------------------------------------------------------------- handles
    def _profile(self) -> KdbClient:
        if self._profile_client is None:
            self._profile_client = KdbClient(*self.conn.profile_endpoint())
        return self._profile_client

    def _kind(self, date: dt.date) -> str:
        return resolve_kind(date, self._today)

    def _oms(self, date: dt.date) -> KdbClient:
        kind = self._kind(date)
        if kind not in self._oms_clients:
            self._oms_clients[kind] = KdbClient(*self.conn.oms_endpoint(kind))
        return self._oms_clients[kind]

    def _md(self, date: dt.date) -> KdbClient:
        kind = self._kind(date)
        if kind not in self._md_clients:
            self._md_clients[kind] = KdbClient(*self.conn.market_endpoint(kind))
        return self._md_clients[kind]

    # ---------------------------------------------------------------- meta
    def available_dates(self) -> list[dt.date]:
        today = self._today or dt.date.today()
        out, d = [], today
        while len(out) < 10:
            if d.weekday() < 5:
                out.append(d)
            d -= dt.timedelta(days=1)
        return sorted(out)

    def list_symbols(self) -> list[str]:
        return []          # the symbol is typed; the gateway is not searchable

    # ------------------------------------------------------------- profile
    def get_profile(self, date: dt.date, sym: str) -> pd.DataFrame:
        # cc0 carries the header-row count (load_equity_special.q:128). Ask for
        # it, and fall back only when the gateway objects to that COLUMN - any
        # other failure is reported as itself. Retrying blindly and reporting
        # the second error hid the first one, which is how a connection fault
        # came back looking like a column problem.
        fn, args = profile_call(self.conn, date, sym, with_cc0=True)
        try:
            return _frame(self._profile().call(fn, *args), self.conn, date, sym)
        except Exception as first:
            if not _looks_like_a_column_complaint(first):
                raise
            fn, args = profile_call(self.conn, date, sym, with_cc0=False)
            return _frame(self._profile().call(fn, *args), self.conn, date, sym)

    # -------------------------------------------------------------- orders
    def list_vwap_orders(self, date: dt.date, filters: dict) -> pd.DataFrame:
        where = [f"date={qdate(date)}", "algo=`VWAP"]
        for key in ("sym", "trader", "basket"):
            want = (filters or {}).get(key)
            if want and want != "All":
                where.append(f"{key}=`{want}")
        q = f"select {ORDER_SELECT} from target where " + ", ".join(where)
        return _frame(self._oms(date).query(q))

    def get_executions(self, date, id_server, id_target) -> pd.DataFrame:
        q = ("select time,cum_qty,cum_apr,fillsize,fillprice from execution "
             f"where date={qdate(date)}, id_server={int(id_server)}, "
             f"id_target={int(id_target)}")
        return _frame(self._oms(date).query(q))

    def get_target_state(self, date, id_server, id_target) -> pd.DataFrame:
        q = ("select t_algo,state,make,commit_open,commit_close,avg_fill_price "
             f"from target_state where date={qdate(date)}, "
             f"id_server={int(id_server)}, id_target={int(id_target)}")
        return _frame(self._oms(date).query(q))

    # --------------------------------------------------------- market data
    def get_qatt(self, date: dt.date, sym: str) -> pd.DataFrame:
        q = ("select tradeTime,size,price,totalVolume from qatt where "
             f"date={qdate(date)}, sym=`{sym}, size>0")
        return _frame(self._md(date).query(q))

    def get_open_print(self, date: dt.date, sym: str) -> tuple[int, float] | None:
        q = ("select time,size from open_print where "
             f"date={qdate(date)}, sym=`{sym}, iau=1")
        try:
            frame = _frame(self._md(date).query(q))
        except Exception:
            return None
        if frame is None or len(frame) == 0:
            return None
        from core.schedule import to_minute
        minute = to_minute(frame.iloc[0]["time"])
        if minute is None:
            return None
        return (minute, float(frame.iloc[0]["size"]))


COLUMN_COMPLAINTS = ("cc0", "not_a_valid_column", "not a valid column",
                     "invalid column", "column")


def _looks_like_a_column_complaint(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(token in text for token in COLUMN_COMPLAINTS)


def _frame(result, conn=None, date=None, sym=None) -> pd.DataFrame:
    """A DataFrame, or an error that says what came back instead.

    A restricted gateway answers a rejected call with a q STRING rather than a
    table. Returning an empty frame for that would report "no rows for this
    symbol" and bury the reason, so the message is raised instead.
    """
    if isinstance(result, pd.DataFrame):
        return result
    if result is None:
        return pd.DataFrame()

    text = _as_text(result)
    if text is not None:
        where = ""
        if conn is not None and date is not None and sym is not None:
            where = f"\n  call: {profile_call_repr(conn, date, sym)}"
        raise RuntimeError(
            f"the server returned a message rather than a table: {text}{where}")

    try:
        return result.pd()
    except Exception as exc:
        raise RuntimeError(
            f"could not read the reply as a table: "
            f"{type(exc).__name__}: {exc}") from exc


def _as_text(result) -> str | None:
    """The reply as text when it is a q string, else None.

    Checked by duck-typing rather than by importing pykx, which this module
    never does at import time.
    """
    if isinstance(result, (bytes, bytearray)):
        return bytes(result).decode("utf-8", "replace")
    if isinstance(result, str):
        return result
    if type(result).__name__ in ("CharVector", "CharAtom", "SymbolAtom"):
        try:
            value = result.py()
        except Exception:
            return str(result)
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode("utf-8", "replace")
        return str(value)
    return None
