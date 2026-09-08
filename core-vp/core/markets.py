"""Which clock a symbol's times should be *displayed* on.

The profile server and qatt both report in the AP region's own clock, HKT
(UTC+8). Shenzhen sits on UTC+8 too, so 570 == 09:30 there is local time by
coincidence; Tokyo does not, so 7203.JP's session opens at 480 == 08:00 HKT,
which is 09:00 JST.

This module is DISPLAY ONLY. Every minute the app computes with stays on the
region clock, so profile buckets, qatt trades and order timestamps all share
one axis and join without conversion. Only the labels move.

The offset is resolved per date through the tz database rather than a static
table, so Sydney is +2h from Hong Kong in July and +3h in January instead of
being wrong for half the year.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REGION_ZONE = "Asia/Hong_Kong"

# Suffix as it appears after the final '.' in the symbol.
SUFFIX_ZONES = {
    "JP": "Asia/Tokyo",
    "KS": "Asia/Seoul", "KQ": "Asia/Seoul", "KR": "Asia/Seoul",
    "HK": "Asia/Hong_Kong",
    "C1": "Asia/Shanghai", "C2": "Asia/Shanghai",
    "SS": "Asia/Shanghai", "SZ": "Asia/Shanghai", "CH": "Asia/Shanghai",
    "TW": "Asia/Taipei",
    "SI": "Asia/Singapore", "SG": "Asia/Singapore",
    "MY": "Asia/Kuala_Lumpur", "KL": "Asia/Kuala_Lumpur",
    "PH": "Asia/Manila",
    "ID": "Asia/Jakarta", "JK": "Asia/Jakarta",
    "TH": "Asia/Bangkok", "BK": "Asia/Bangkok",
    "VN": "Asia/Ho_Chi_Minh",
    "IN": "Asia/Kolkata", "NS": "Asia/Kolkata", "BO": "Asia/Kolkata",
    "AU": "Australia/Sydney", "AX": "Australia/Sydney",
    "NZ": "Pacific/Auckland",
}


# When the auctions actually print, as minutes-of-day in the market's OWN local
# time. These are market facts and they do change - TSE moved its close from
# 15:00 to 15:30 in November 2024 - so they live in one editable place, and
# decode_profile validates them against the session it derived from the data:
# a stale entry falls back to the bracketing position and says so, rather than
# drawing an auction in the wrong place.
#
# `None` for the PM entry means the market has no lunch break. The reopen is
# not listed at all: it is exactly the end of the lunch gap, which the profile
# rows already give us.
MARKET_AUCTIONS = {
    #                          open print   close print
    "Asia/Tokyo":             (9 * 60,      15 * 60 + 30),   # Itayose 09:00, close 15:25-15:30
    "Asia/Shanghai":          (9 * 60 + 25, 15 * 60),        # call prints 09:25, close 14:57-15:00
    "Asia/Seoul":             (9 * 60,      15 * 60 + 30),
    "Asia/Taipei":            (9 * 60,      13 * 60 + 30),
}


def auction_minutes(sym: str, date: dt.date) -> tuple[int | None, int | None]:
    """(open print, close print) as REGION-clock minutes, or (None, None).

    None means "not known for this market" and the caller brackets the session
    instead. Being absent is fine; being wrong is not.
    """
    zone = market_zone(sym)
    if zone is None or zone not in MARKET_AUCTIONS:
        return (None, None)
    offset = display_offset_minutes(sym, date)
    local_open, local_close = MARKET_AUCTIONS[zone]
    return (local_open - offset, local_close - offset)


def suffix(sym: str) -> str:
    if not sym or "." not in sym:
        return ""
    return sym.rsplit(".", 1)[-1].strip().upper()


def market_zone(sym: str) -> str | None:
    """IANA zone for the symbol's exchange, or None when the suffix is unknown."""
    return SUFFIX_ZONES.get(suffix(sym))


def _offset(zone: str, date: dt.date) -> dt.timedelta | None:
    try:
        # midday, so a DST transition at either end of the day cannot land on
        # an ambiguous or non-existent local time
        return dt.datetime(date.year, date.month, date.day, 12,
                           tzinfo=ZoneInfo(zone)).utcoffset()
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return None


def display_offset_minutes(sym: str, date: dt.date) -> int:
    """Minutes to ADD to a region-clock minute to read it as local exchange
    time. 0 when the market is unknown or already on the region clock."""
    zone = market_zone(sym)
    if zone is None:
        return 0
    local, region = _offset(zone, date), _offset(REGION_ZONE, date)
    if local is None or region is None:
        return 0
    return int((local - region).total_seconds() // 60)


def _utc_label(zone: str, date: dt.date) -> str:
    off = _offset(zone, date)
    if off is None:
        return zone
    total = int(off.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total), 60)
    tail = f":{minutes:02d}" if minutes else ""
    return f"UTC{sign}{hours}{tail}"


def zone_label(sym: str, date: dt.date) -> str:
    """What the time axis is showing, said plainly."""
    zone = market_zone(sym)
    if zone is None:
        return f"{REGION_ZONE.split('/')[-1].replace('_', ' ')} server time " \
               f"({_utc_label(REGION_ZONE, date)}) - market unknown"
    name = zone.split("/")[-1].replace("_", " ")
    return f"{name} time ({_utc_label(zone, date)})"
