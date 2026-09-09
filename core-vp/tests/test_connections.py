import datetime as dt

from core.connections import (DEFAULT_PROFILE_TABLE, Connection, probe,
                              profile_call, profile_call_repr, qsym,
                              resolve_kind)


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


def test_a_symbol_goes_as_bytes_not_str():
    """pykx turns a Python str into a CHAR VECTOR, not a symbol. Passing a str
    where q wants a symbol is what produced 'CharVector' object has no
    attribute '_context_keys'."""
    assert qsym("000001.C2") == b"000001.C2"
    assert isinstance(qsym("profile"), bytes)


def test_profile_call_passes_arguments_not_a_string():
    fn, args = profile_call(Connection(name="ap"), dt.date(2026, 7, 29),
                            "000001.C2")
    assert fn == "get_data_by_date"
    dataset, columns, d_from, d_to, sym = args
    assert dataset == b"profile"
    assert columns == [b"date", b"sym", b"vmed", b"time", b"cc0"]
    assert d_from == d_to == dt.date(2026, 7, 29)
    assert sym == b"000001.C2"
    # nothing is hand-formatted into q text
    assert not any(isinstance(a, str) for a in args)


def test_profile_call_can_drop_cc0():
    _, args = profile_call(Connection(name="ap"), dt.date(2026, 7, 29),
                           "000001.C2", with_cc0=False)
    assert args[1] == [b"date", b"sym", b"vmed", b"time"]


def test_the_repr_is_for_humans_only():
    r = profile_call_repr(Connection(name="ap"), dt.date(2026, 7, 29),
                          "000001.C2")
    assert r == ("get_data_by_date[`profile;`date`sym`vmed`time`cc0;"
                 "2026.07.29;2026.07.29;`000001.C2]")


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

        def call(self, fn, *args):
            seen.append((self.endpoint, fn))
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

        def call(self, fn, *args):
            sent.append(("call", self.endpoint, fn, args))
            return 1

    probe(Connection(name="ap", profile_host="vprof", profile_port=5100),
          "hist", client_factory=Fake, sample_date=dt.date(2026, 7, 29),
          sample_sym="000001.C2")
    gateway = [e for e in sent if e[1] == "vprof:5100"]
    assert len(gateway) == 1
    kind, _, fn, args = gateway[0]
    assert kind == "call"                      # never a query string
    assert fn == "get_data_by_date"
    assert args[0] == b"profile" and args[-1] == b"000001.C2"


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

        def call(self, fn, *args):
            raise ConnectionRefusedError("no listener")

    report = probe(Connection(name="ap"), "hist", client_factory=Dead,
                   sample_date=dt.date(2026, 7, 29), sample_sym="000001.C2")
    assert all(r["ok"] is False for r in report)
    assert "no listener" in report[0]["detail"]
