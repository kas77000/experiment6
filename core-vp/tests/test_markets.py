"""Display-only timezone mapping. Never touches a computed minute."""
import datetime as dt

from core.markets import (REGION_ZONE, auction_minutes,
                          display_offset_minutes, market_zone, suffix,
                          zone_label)

JULY = dt.date(2026, 7, 15)
JANUARY = dt.date(2026, 1, 15)


def test_suffix_extraction():
    assert suffix("7203.JP") == "JP"
    assert suffix("000001.C2") == "C2"
    assert suffix("NOSUFFIX") == ""


def test_the_region_clock_is_hong_kong():
    assert REGION_ZONE == "Asia/Hong_Kong"


def test_markets_already_on_the_region_clock_need_no_shift():
    for sym in ("000001.C2", "0005.HK", "2330.TW", "D05.SI"):
        assert display_offset_minutes(sym, JULY) == 0


def test_tokyo_and_seoul_are_an_hour_ahead():
    assert display_offset_minutes("7203.JP", JULY) == 60
    assert display_offset_minutes("005930.KS", JULY) == 60


def test_india_is_two_and_a_half_hours_behind():
    assert display_offset_minutes("RELIANCE.IN", JULY) == -150


def test_bangkok_is_an_hour_behind():
    assert display_offset_minutes("PTT.TH", JULY) == -60


def test_sydney_follows_dst_instead_of_a_fixed_guess():
    """The reason this resolves through the tz database rather than a table:
    a static offset would be wrong for half the year."""
    assert display_offset_minutes("BHP.AU", JULY) == 120      # AEST, UTC+10
    assert display_offset_minutes("BHP.AU", JANUARY) == 180   # AEDT, UTC+11


def test_an_unknown_market_does_not_guess():
    assert display_offset_minutes("FOO.ZZ", JULY) == 0
    assert display_offset_minutes("NOSUFFIX", JULY) == 0
    assert market_zone("FOO.ZZ") is None


def test_the_label_says_which_clock_is_on_screen():
    assert "Tokyo" in zone_label("7203.JP", JULY)
    assert "UTC+9" in zone_label("7203.JP", JULY)
    assert "UTC+5:30" in zone_label("RELIANCE.IN", JULY)
    unknown = zone_label("FOO.ZZ", JULY)
    assert "server time" in unknown and "market unknown" in unknown


def test_auction_prints_convert_to_region_minutes():
    """TSE prints at 09:00 and 15:30 JST, which on the HKT region clock the
    profile uses are 08:00 (480) and 14:30 (870)."""
    assert auction_minutes("7203.JP", JULY) == (480, 870)


def test_shanghai_auctions_need_no_conversion():
    assert auction_minutes("000001.C2", JULY) == (9 * 60 + 25, 15 * 60)


def test_an_unlisted_market_says_it_does_not_know():
    assert auction_minutes("FOO.ZZ", JULY) == (None, None)
    assert auction_minutes("0005.HK", JULY) == (None, None)
