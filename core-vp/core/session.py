"""Session boundaries, derived from the profile's own buckets.

No per-market table to maintain: the lunch break is the largest gap between
consecutive bucket minutes that exceeds twice the median spacing. Shenzhen's
690 -> 780 is a 90-minute gap against a 10-minute median; a continuous market
has no such gap.

The derivation self-checks. A profile reporting a PM reopen auction (time=3,
`vopenpm` in idxprof.q) while showing no lunch break contradicts itself, and
that is recorded as a warning rather than silently drawn.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Sequence

LUNCH_GAP_FACTOR = 2.0


@dataclass(frozen=True)
class Session:
    open_min: int
    close_min: int
    lunch: tuple[int, int] | None
    has_pm_auction: bool
    warnings: tuple[str, ...] = field(default=())

    @property
    def is_two_session(self) -> bool:
        return self.lunch is not None


def derive_session(minutes: Sequence[int], v_open_pm: float) -> Session:
    """Open, close and any lunch break, read off the bucket minutes."""
    m = sorted(int(x) for x in minutes)
    if len(m) < 2:
        raise ValueError(
            f"need at least 2 buckets to derive a session, got {len(m)}")

    gaps = [b - a for a, b in zip(m, m[1:])]
    median_gap = statistics.median(gaps)
    widest = max(gaps)

    lunch = None
    if median_gap > 0 and widest > LUNCH_GAP_FACTOR * median_gap:
        i = gaps.index(widest)
        lunch = (m[i], m[i + 1])

    has_pm = float(v_open_pm) > 0.0
    warnings: list[str] = []
    if has_pm and lunch is None:
        warnings.append(
            "profile reports a PM reopen auction (time=3) but no lunch break "
            "was found in the buckets - the data disagrees with itself")

    return Session(open_min=m[0], close_min=m[-1], lunch=lunch,
                   has_pm_auction=has_pm, warnings=tuple(warnings))
