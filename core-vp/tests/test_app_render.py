"""The whole app renders on the demo provider, and one dead endpoint greys one
panel rather than taking the page down."""
import datetime as dt

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from core.profile import decode_profile
from core.provider_demo import DemoProvider
from tests.fixtures import raw_profile
from ui import panels
from ui.tables import COLUMNS, bucket_table

PROFILE = decode_profile(raw_profile(), "000001.C2", dt.date(2026, 7, 29))


def run():
    return AppTest.from_file("app.py", default_timeout=90).run()


def test_app_renders_without_exception():
    at = run()
    assert not at.exception


def test_all_three_panels_are_present():
    heads = " ".join(h.value for h in run().subheader)
    assert "Volume profile" in heads
    assert "Order progression" in heads
    assert "Profile vs today" in heads


def test_the_sources_tab_exists_alongside_the_charts():
    at = run()
    assert not at.exception
    assert any("Sources" in str(t) for t in at.tabs)


def test_bucket_table_columns():
    t = bucket_table(PROFILE)
    assert list(t.columns) == COLUMNS
    assert len(t) == len(PROFILE.buckets)


def test_guarded_reports_the_failure_instead_of_raising():
    class Broken(DemoProvider):
        def get_qatt(self, date, sym):
            raise ConnectionRefusedError("connection refused")

    provider = Broken()
    value, err = panels.guarded("qatt", provider.get_qatt,
                               dt.date(2026, 7, 29), "000001.C2")
    assert value is None
    assert "connection refused" in err and "qatt" in err


def test_guarded_passes_a_good_call_straight_through():
    provider = DemoProvider()
    date = provider.available_dates()[-1]
    value, err = panels.guarded("profile", provider.get_profile, date,
                                "000001.C2")
    assert err is None and len(value) > 0


def test_an_undecodable_profile_reports_the_reason_not_an_empty_chart():
    class Junk(DemoProvider):
        def get_profile(self, date, sym):
            return pd.DataFrame({"time": [0, 1, 2, 570, 580],
                                 "vmed": [1.0, 1.0, 1.0, 0.0, 0.4]})

    provider = Junk()
    profile, err = panels.load_profile(provider, provider.available_dates()[-1],
                                       "000001.C2")
    assert profile is None
    assert "reach 1.0" in err


def test_a_missing_symbol_reports_no_rows():
    provider = DemoProvider()
    profile, err = panels.load_profile(provider, provider.available_dates()[-1],
                                       "NOSUCH.XX")
    assert profile is None and "no rows" in err


def test_formatters_show_a_dash_rather_than_a_misleading_zero():
    assert panels.qty(None) == panels.DASH
    assert panels.pct(float("nan")) == panels.DASH
    assert panels.qty(1234567) == "1,234,567"
    assert panels.pct(0.1234) == "12.34%"


def test_selecting_the_reserving_symbol_explains_the_reserve():
    """The case the whole design exists for: an order that looks behind on the
    filled line while holding quantity for the close."""
    provider = DemoProvider()
    date = provider.available_dates()[-1]
    reserving = [
        o.sym for _, o in provider.list_vwap_orders(date, {}).iterrows()
        if provider.get_target_state(date, o.id_server,
                                     o.id_target)["commit_close"].max() > 0]
    assert reserving, "the demo data must contain a reserving order"

    at = AppTest.from_file("app.py", default_timeout=90).run()
    at.selectbox(key="symbol").select(reserving[0]).run()
    assert not at.exception

    body = " ".join(m.value for m in at.markdown) + \
           " ".join(i.value for i in at.info)
    assert "holding" in body, "the reserve must be explained, not left implicit"
    assert "Reserved for auctions" in " ".join(str(m) for m in at.metric)


def test_the_symbol_picker_offers_only_symbols_with_vwap_orders():
    provider = DemoProvider()
    date = provider.available_dates()[-1]
    at = AppTest.from_file("app.py", default_timeout=90).run()
    options = list(at.selectbox(key="symbol").options)
    assert options[:-1] == provider.list_vwap_symbols(date)
    assert options[-1] == "other..."
