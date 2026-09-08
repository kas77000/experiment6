"""The bucket table - the kdbmonitor layout's fourth row."""
from __future__ import annotations

import pandas as pd

from ui.charts import even_pace

COLUMNS = ["Time", "Phase", "Cumulated", "This bucket", "Even pace",
           "Share of day"]


def bucket_table(profile) -> pd.DataFrame:
    """Every bucket, auctions included, with the even-pace reference."""
    pace = dict(zip(*even_pace(profile)))
    b = profile.buckets
    return pd.DataFrame({
        "Time": b["clock"],
        "Phase": b["phase"],
        "Cumulated": b["cum_frac"],
        "This bucket": b["share"],
        "Even pace": b["minute"].map(pace),
        "Share of day": b["share_of_day"],
    })[COLUMNS].reset_index(drop=True)


def order_label(order) -> str:
    return (f"{order['id_target']} - {order['sym']} {order['side']} "
            f"{float(order['size']):,.0f} ({order['trader']})")
