"""What the app needs from a data source, and how one is chosen.

Two implementations: `DemoProvider` (synthetic, always available) and
`KdbProvider` (pykx, imported lazily so the app runs with pykx absent).

Every method returns a DataFrame in the shape the kdb tables use, so the pure
modules above cannot tell the two apart.
"""
from __future__ import annotations

import abc
import datetime as dt

import pandas as pd

# Columns list_vwap_orders must return, whatever the backend.
ORDER_COLUMNS = ("date", "id_server", "id_target", "trader", "basket", "sym",
                 "side", "size", "algo", "alpha", "t_start", "t_end",
                 "doopen", "doclose")


class DataProvider(abc.ABC):
    """A source of profiles, VWAP orders and market data."""

    label: str = "provider"

    @abc.abstractmethod
    def available_dates(self) -> list[dt.date]:
        ...

    @abc.abstractmethod
    def list_symbols(self) -> list[str]:
        ...

    @abc.abstractmethod
    def get_profile(self, date: dt.date, sym: str) -> pd.DataFrame:
        """Raw vst rows: date, sym, time, vmed and cc0 when available."""

    @abc.abstractmethod
    def list_vwap_orders(self, date: dt.date, filters: dict) -> pd.DataFrame:
        """`target` rows where algo=`VWAP, with ORDER_COLUMNS present."""

    def list_vwap_symbols(self, date: dt.date) -> list[str]:
        """Symbols with a VWAP order working on `date`.

        The page is about one symbol, so this is how that symbol gets chosen:
        from what is actually being executed, rather than typed blind.
        """
        orders = self.list_vwap_orders(date, {})
        if orders is None or len(orders) == 0:
            return []
        return sorted({str(s) for s in orders["sym"]})

    @abc.abstractmethod
    def get_executions(self, date: dt.date, id_server, id_target) -> pd.DataFrame:
        """`execution` rows; must carry `time` and `cum_qty`."""

    @abc.abstractmethod
    def get_target_state(self, date: dt.date, id_server, id_target) -> pd.DataFrame:
        """`target_state` rows; must carry `t_algo`, `commit_open`, `commit_close`."""

    @abc.abstractmethod
    def get_qatt(self, date: dt.date, sym: str) -> pd.DataFrame:
        """`qatt` rows; must carry a time column and `size`."""

    @abc.abstractmethod
    def get_open_print(self, date: dt.date, sym: str) -> tuple[int, float] | None:
        """(minute-of-day, size) of the opening auction print, or None."""


def make_provider(conn=None, force_demo: bool = False) -> DataProvider:
    """The demo backend unless a connection is configured and pykx is present."""
    from core.provider_demo import DemoProvider

    if force_demo or conn is None:
        return DemoProvider()
    try:
        import pykx  # noqa: F401
    except Exception:
        return DemoProvider()
    from core.provider_kdb import KdbProvider
    return KdbProvider(conn)
