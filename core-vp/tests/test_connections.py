import datetime as dt

import pytest

from core.connections import (DEFAULT_PROFILE_TABLE, Connection, probe,
                              profile_query, resolve_kind)


def test_today_is_live_and_other_dates_are_historical():
    today = dt.date(2026, 9, 4)
    assert resolve_kind(today, today) == "rt"
    assert resolve_kind(today - dt.timedelta(days=1), today) == "hist"


def test_a_future_date_is_historical_so_clock_skew_cannot_hit_the_live_server():
    today = dt.date(2026, 9, 4)
    assert resolve_kind(today + dt.timedelta(days=5), today) == "hist"


def test_the_gateway_dataset_is_profile():
    """`profile` is a gateway dataset alias, not an HDB table name. The vst*
    tables are what the gateway maps from and are rejected if passed."""
    assert DEFAULT_PROFILE_TABLE == "profile"
    assert Connection(name="ap").profile_table == "profile"


def test_the_call_goes_as_one_string():
    """The gateway pattern-matches text. pykx's function-application form -
    h(fn, arg1, arg2) - is answered with 'Not a valid command'."""
    q = profile_query(Connection(name="ap"), dt.date(2026, 7, 29), "000001.C2")
    assert q == ("get_data_by_date[`profile;`date`sym`vmed`time`cc0;"
                 "2026.07.29;2026.07.29;`000001.C2]")


def test_profile_query_can_drop_cc0():
    q = profile_query(Connection(name="ap"), dt.date(2026, 7, 29),
                      "000001.C2", with_cc0=False)
    assert "cc0" not in q and "`date`sym`vmed`time;" in q


def test_endpoints_resolve_by_kind():
    c = Connection(name="ap", oms_rt_host="rt", oms_rt_port=1,
                   oms_hist_host="h", oms_hist_port=2)
    assert c.oms_endpoint("rt") == ("rt", 1)
    assert c.oms_endpoint("hist") == ("h", 2)


def test_market_endpoint_falls_back_to_the_order_server_when_unset():
    c = Connection(name="ap", oms_hist_host="oms", oms_hist_port=5010)
    assert c.market_endpoint("hist") == ("oms", 5010)
    assert not c.has_separate_market_data("hist")

    c.md_hist_host, c.md_hist_port = "qattl", 5020
    assert c.market_endpoint("hist") == ("qattl", 5020)
    assert c.has_separate_market_data("hist")


def test_round_trip_through_json(tmp_path, monkeypatch):
    import core.connections as m
    monkeypatch.setattr(m, "CONFIG_PATH", tmp_path / "connections.json")
    m.save_connections([Connection(name="ap", profile_host="p",
                                   profile_port=5000, profile_table="vst10d")])
    got = m.load_connections()[0]
    assert got.profile_host == "p" and got.profile_table == "vst10d"


def test_missing_config_file_is_not_an_error(tmp_path, monkeypatch):
    import core.connections as m
    monkeypatch.setattr(m, "CONFIG_PATH", tmp_path / "nope.json")
    assert m.load_connections() == []


def test_probe_checks_each_table_against_its_own_endpoint():
    """qatt on the order server is the silent misconfiguration, so the probe
    must not send it there."""
    seen = []

    class Fake:
        def __init__(self, host, port):
            self.endpoint = f"{host}:{port}"

        def query(self, expr):
            seen.append((self.endpoint, expr))
            return 1

    c = Connection(name="ap", profile_host="vprof", profile_port=5100,
                   oms_hist_host="oms", oms_hist_port=5010,
                   md_hist_host="qattl", md_hist_port=5020)
    report = probe(c, "hist", client_factory=Fake,
                   sample_date=dt.date(2026, 7, 29), sample_sym="000001.C2")

    assert all(r["ok"] for r in report)
    by_table = {r["table"]: r["endpoint"] for r in report}
    assert by_table["profile"] == "vprof:5100"
    assert by_table["target"] == "oms:5010"
    assert by_table["qatt"] == "qattl:5020"


def test_the_gateway_is_probed_with_a_real_call_not_count():
    """A restricted gateway answers `count profile` with "not a valid command",
    so counting would report a healthy endpoint as broken."""
    sent = []

    class Fake:
        def __init__(self, host, port):
            self.endpoint = f"{host}:{port}"

        def query(self, expr):
            sent.append(("query", self.endpoint, expr))
            return 1

    probe(Connection(name="ap", profile_host="vprof", profile_port=5100),
          "hist", client_factory=Fake, sample_date=dt.date(2026, 7, 29),
          sample_sym="000001.C2")
    gateway = [e for e in sent if e[1] == "vprof:5100"]
    assert len(gateway) == 1
    _, _, expr = gateway[0]
    assert expr.startswith("get_data_by_date[`profile;")
    assert not expr.startswith("count")


def test_without_a_sample_the_gateway_row_is_not_checked_rather_than_guessed():
    class Fake:
        def __init__(self, host, port):
            pass

        def query(self, expr):
            return 1

    report = probe(Connection(name="ap"), "hist", client_factory=Fake)
    row = [r for r in report if r["role"] == "profile"][0]
    assert row["ok"] is None
    assert "not checked" in row["detail"]


def test_probe_reports_a_dead_endpoint_instead_of_raising():
    class Dead:
        def __init__(self, host, port):
            pass

        def query(self, expr):
            raise ConnectionRefusedError("no listener")

    report = probe(Connection(name="ap"), "hist", client_factory=Dead,
                   sample_date=dt.date(2026, 7, 29), sample_sym="000001.C2")
    assert all(r["ok"] is False for r in report)
    assert "no listener" in report[0]["detail"]


# ---------------------------------------------------------------- transport
CONTEXT_ERROR = AttributeError(
    "'CharVector' object has no attribute '_context_keys'")


class _FakeKx:
    """Stands in for pykx.

    ctx_bomb reproduces the VPROF gateway: pykx resolves `q` on the remote,
    finds the gateway's own char vector, and dies building its context - and
    it does that even when no_ctx=True was passed, which is what the real
    traceback showed.
    """

    def __init__(self, accepts_no_ctx=True, ctx_bomb=False, raw_works=False):
        self.accepts_no_ctx = accepts_no_ctx
        self.ctx_bomb = ctx_bomb
        self.calls = []
        if raw_works:
            self.RawQConnection = self._raw

    def SyncQConnection(self, host, port, **kw):   # noqa: N802
        self.calls.append(kw)
        if "no_ctx" in kw and not self.accepts_no_ctx:
            raise TypeError("__init__() got an unexpected keyword argument "
                            "'no_ctx'")
        if self.ctx_bomb:
            raise CONTEXT_ERROR
        return ("handle", host, port)

    def _raw(self, host, port, **kw):
        self.calls.append(dict(kw, raw=True))
        if "no_ctx" in kw:
            raise TypeError("__init__() got an unexpected keyword argument "
                            "'no_ctx'")
        return ("raw", host, port)


def _with_fake_pykx(monkeypatch, fake):
    import sys
    monkeypatch.setitem(sys.modules, "pykx", fake)


def test_the_first_strategy_is_the_least_invasive_one(monkeypatch):
    import core.connections as m
    fake = _FakeKx()
    _with_fake_pykx(monkeypatch, fake)
    m.open_connection("vprof", 5100)
    assert fake.calls == [{"no_ctx": True}]
    assert m.LAST_STRATEGY[("vprof", 5100)] == "SyncQConnection(no_ctx=True)"


def test_raw_connections_are_not_used(monkeypatch):
    """RawQConnection opens against the gateway and then fails every query
    with "Cannot load requested context object in unlicensed mode", so
    accepting it would trade a clear error for an obscure one per read."""
    import core.connections as m
    fake = _FakeKx(raw_works=True)
    _with_fake_pykx(monkeypatch, fake)
    m.open_connection("vprof", 5100)
    assert "Raw" not in m.LAST_STRATEGY[("vprof", 5100)]


def test_an_older_pykx_without_the_flag_still_connects(monkeypatch):
    import core.connections as m
    fake = _FakeKx(accepts_no_ctx=False)
    _with_fake_pykx(monkeypatch, fake)
    assert m.open_connection("vprof", 5100) == ("handle", "vprof", 5100)


def test_a_refused_connection_is_raised_at_once_not_retried(monkeypatch):
    """Four attempts at a dead port would turn one clear error into noise."""
    import core.connections as m

    class Dead(_FakeKx):
        def SyncQConnection(self, host, port, **kw):   # noqa: N802
            self.calls.append(kw)
            raise ConnectionRefusedError("no listener on 5100")

    fake = Dead()
    _with_fake_pykx(monkeypatch, fake)
    with pytest.raises(ConnectionRefusedError, match="no listener"):
        m.open_connection("vprof", 5100)
    assert len(fake.calls) == 1


def test_when_nothing_works_the_error_lists_what_was_tried(monkeypatch):
    import core.connections as m
    fake = _FakeKx(ctx_bomb=True, raw_works=False)
    _with_fake_pykx(monkeypatch, fake)
    with pytest.raises(RuntimeError, match="context interface") as caught:
        m.open_connection("vprof", 5100)
    assert "SyncQConnection(no_ctx=True)" in str(caught.value)
