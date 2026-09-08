"""KdbProvider builds q strings. No server needed: a fake client records them."""
import datetime as dt

import pandas as pd

from core.connections import Connection
from core.provider_kdb import KdbProvider

DATE = dt.date(2026, 7, 29)
TODAY = dt.date(2026, 9, 4)


class FakeClient:
    def __init__(self, result=None):
        self.sent = []
        self.result = pd.DataFrame() if result is None else result

    def query(self, expr):
        self.sent.append(expr)
        return self.result


def provider(**kw):
    conn = Connection(name="t", **kw)
    p = KdbProvider(conn, today=TODAY)
    p._profile_client = FakeClient()
    p._oms_clients = {"rt": FakeClient(), "hist": FakeClient()}
    p._md_clients = {"rt": FakeClient(), "hist": FakeClient()}
    return p


def test_profile_query_uses_the_configured_table_and_asks_for_cc0():
    p = provider()
    p.get_profile(DATE, "000001.C2")
    q = p._profile_client.sent[0]
    assert "get_data_by_date[`profile;" in q
    assert "`date`sym`vmed`time`cc0" in q
    assert "2026.07.29;2026.07.29" in q
    assert "`000001.C2" in q


def test_profile_query_retries_without_cc0_when_the_gateway_rejects_it():
    class Picky(FakeClient):
        def query(self, expr):
            self.sent.append(expr)
            if "cc0" in expr:
                raise RuntimeError("not_a_valid_column")
            return pd.DataFrame({"time": [0], "vmed": [1.0]})

    p = provider()
    p._profile_client = Picky()
    out = p.get_profile(DATE, "000001.C2")
    assert len(p._profile_client.sent) == 2
    assert "cc0" not in p._profile_client.sent[1]
    assert len(out) == 1


def test_the_profile_function_name_is_configurable():
    p = provider(profile_fn="get_profile_rows")
    p.get_profile(DATE, "000001.C2")
    assert p._profile_client.sent[0].startswith("get_profile_rows[`profile;")


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
