"""KdbProvider builds calls. No server needed: a fake client records them.

The gateway call goes through KdbClient.call - function name plus arguments -
matching the pattern kdb-queries uses against these same servers
(liquidity_profile.py: `hq(".lp.profile", sym.encode(), dtq, bkt).pd()`).
Interpolating a symbol into a query string, or passing it as a Python str,
sends a q CHAR VECTOR where a symbol is wanted.
"""
import datetime as dt

import pandas as pd
import pytest

from core.connections import Connection
from core.provider_kdb import KdbProvider

DATE = dt.date(2026, 7, 29)
TODAY = dt.date(2026, 9, 4)


class FakeClient:
    def __init__(self, result=None):
        self.sent = []       # q expressions
        self.calls = []      # (fn, args)
        self.result = pd.DataFrame() if result is None else result

    def query(self, expr):
        self.sent.append(expr)
        return self.result

    def call(self, fn, *args):
        self.calls.append((fn, args))
        return self.result


def provider(**kw):
    conn = Connection(name="t", **kw)
    p = KdbProvider(conn, today=TODAY)
    p._profile_client = FakeClient()
    p._oms_clients = {"rt": FakeClient(), "hist": FakeClient()}
    p._md_clients = {"rt": FakeClient(), "hist": FakeClient()}
    return p


# ------------------------------------------------------------------ profile
def test_the_profile_call_sends_arguments_not_a_query_string():
    p = provider()
    p.get_profile(DATE, "000001.C2")
    assert p._profile_client.sent == []          # nothing interpolated
    fn, args = p._profile_client.calls[0]
    assert fn == "get_data_by_date"
    assert args == (b"profile",
                    [b"date", b"sym", b"vmed", b"time", b"cc0"],
                    DATE, DATE, b"000001.C2")


def test_symbols_are_bytes_so_q_receives_symbols():
    p = provider()
    p.get_profile(DATE, "7203.JP")
    _, args = p._profile_client.calls[0]
    assert isinstance(args[0], bytes) and isinstance(args[-1], bytes)
    assert not any(isinstance(a, str) for a in args)


def test_the_dataset_and_function_stay_configurable():
    p = provider(profile_fn="get_profile_rows", profile_table="profile2")
    p.get_profile(DATE, "000001.C2")
    fn, args = p._profile_client.calls[0]
    assert fn == "get_profile_rows" and args[0] == b"profile2"


def test_cc0_is_dropped_only_when_the_gateway_objects_to_that_column():
    class Picky(FakeClient):
        def call(self, fn, *args):
            self.calls.append((fn, args))
            if b"cc0" in args[1]:
                raise RuntimeError("not_a_valid_column: cc0")
            return pd.DataFrame({"time": [0], "vmed": [1.0]})

    p = provider()
    p._profile_client = Picky()
    out = p.get_profile(DATE, "000001.C2")
    assert len(p._profile_client.calls) == 2
    assert b"cc0" not in p._profile_client.calls[1][1][1]
    assert len(out) == 1


def test_any_other_failure_is_reported_as_itself_not_retried():
    """The bug this replaces: a blind retry reported the SECOND error, so a
    connection fault came back looking like a column problem."""
    class Broken(FakeClient):
        def call(self, fn, *args):
            self.calls.append((fn, args))
            raise ConnectionRefusedError("no listener on 5100")

    p = provider()
    p._profile_client = Broken()
    with pytest.raises(ConnectionRefusedError, match="no listener"):
        p.get_profile(DATE, "000001.C2")
    assert len(p._profile_client.calls) == 1       # not retried


def test_a_string_reply_is_raised_as_the_servers_message():
    """A restricted gateway answers a rejected call with a q string. Returning
    an empty frame would report 'no rows for this symbol' and bury the reason."""
    p = provider()
    p._profile_client = FakeClient(b"not_a_valid_table")
    with pytest.raises(RuntimeError, match="not_a_valid_table") as caught:
        p.get_profile(DATE, "000001.C2")
    assert "get_data_by_date[`profile;" in str(caught.value)


def test_a_charvector_reply_is_decoded_rather_than_repr_d():
    class CharVector:
        def py(self):
            return b"rejected: bad dataset"

    p = provider()
    p._profile_client = FakeClient(CharVector())
    with pytest.raises(RuntimeError, match="rejected: bad dataset"):
        p.get_profile(DATE, "000001.C2")


# ------------------------------------------------------------------- orders
def test_orders_query_filters_to_vwap_and_constrains_date_first():
    p = provider()
    p.list_vwap_orders(DATE, {})
    q = p._oms_clients["hist"].sent[0]
    assert q.index("date=2026.07.29") < q.index("algo=`VWAP")


def test_order_filters_are_appended_and_all_is_ignored():
    p = provider()
    p.list_vwap_orders(DATE, {"sym": "000001.C2", "trader": "All"})
    q = p._oms_clients["hist"].sent[0]
    assert "sym=`000001.C2" in q and "trader=" not in q


def test_qatt_goes_to_the_market_endpoint_never_the_order_server():
    p = provider()
    p.get_qatt(DATE, "000001.C2")
    assert p._md_clients["hist"].sent and not p._oms_clients["hist"].sent


def test_todays_date_uses_the_live_handles():
    p = provider()
    p.list_vwap_orders(TODAY, {})
    assert p._oms_clients["rt"].sent and not p._oms_clients["hist"].sent


def test_executions_and_state_are_keyed_by_server_and_target():
    p = provider()
    p.get_executions(DATE, 7, 1001)
    p.get_target_state(DATE, 7, 1001)
    ex, st = p._oms_clients["hist"].sent
    assert "id_server=7" in ex and "id_target=1001" in ex and "cum_qty" in ex
    assert "commit_close" in st and "target_state" in st


def test_open_print_returns_none_when_there_is_no_row():
    p = provider()
    assert p.get_open_print(DATE, "000001.C2") is None


def test_open_print_is_decoded_to_a_minute_and_size():
    p = provider()
    p._md_clients["hist"] = FakeClient(
        pd.DataFrame({"time": [pd.Timedelta(minutes=571)], "size": [445700.0]}))
    assert p.get_open_print(DATE, "000001.C2") == (571, 445700.0)
