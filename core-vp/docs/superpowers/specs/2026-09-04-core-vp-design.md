# core-vp — Volume Profile vs Execution — Design

**Date:** 2026-09-04
**Status:** approved, ready for an implementation plan

A Streamlit app that answers one question: **is this VWAP order tracking the volume
profile, and is the day itself tracking it?**

Three things on one shared time axis:

1. the symbol's volume profile (the kdbmonitor graph + table layout);
2. a selected live VWAP order's execution against the schedule that profile implies;
3. today's realised volume from `qatt` against the profile's median shape.

---

## 1. Where the knowledge came from

Nothing here is invented. The decoding rules are read out of the existing q code, and
this section records which line said what, so a future reader can re-check it.

| Fact | Source |
|---|---|
| Profile row layout, the 10-min grid, auction normalisation | `ai3/src/com/kas/ai/kdb/vproflib.q` → `getsymprof` |
| Header rows named: `adv`/`vopen`/`vclose`/`vopenpm` at `time` 0/1/2/3 | `ai3/src/com/kas/ai/kdb/idxprof.q:37-42` |
| Header-row count lives in `cc0` on row 0 | `ai3/src/com/kas/ai/kdb/load_equity_special.q:128` |
| Realised volume from `qatt`, and re-seating the opening print | `vproflib.q` → `getsymprof_realRT` / `getsymprof_realHist` |
| Order tables: `target`, `target_state`, `execution` columns | `ai3/ORDER-MONITOR-DATA-MODEL.md` §2 |
| `qatt` columns | `ai3/ORDER-MONITOR-DATA-MODEL.md` §3.1 |
| Order server and market-data server are different processes | `algo-order-monitor/core/connections.py` |
| Panel-1 layout (KPI → cumulated line → per-bucket bar → table) | `kdbmonitor/docs/examples/volume_profile_dashboard.json` |

### 1.1 The profile dataset

Reached through a gateway function. The first argument is **always `` `profile ``**:

```q
get_data_by_date[`profile;`date`sym`vmed`time`cc0;<from>;<to>;`<sym>]
```

`profile` is a gateway **dataset alias**, not an HDB table name. The `vst` / `vst05d` /
`vst10d` / `vst20d` tables `load_vprof.q` builds, and the `latest_vst` that `vproflib.q`
maintains, are what the gateway maps *from*; passing one of those names is rejected.

> An earlier draft of this section had it backwards — it named `` `vst `` as the argument
> and claimed `` `profile `` was the rejected one. That inference came from
> `load_vprof.q` while the gateway itself had a bug that answered `not_a_valid_table`
> to a correct call. `` `profile `` is the answer.

Rows for one `(date, sym)`:

| `time` | meaning | example (`000001.C2`, 2026.07.29) |
|---|---|---|
| 0 | ADV — median daily **continuous** volume | 105,156,029 |
| 1 | open auction volume | 445,700 |
| 2 | close auction volume | 799,800 |
| 3 | **PM reopen auction** volume (lunch-break markets) | 2,000 |
| ≥ 100 | minutes-of-day; `vmed` = **cumulative fraction** | 570 → 0, 571 → 0.0216089, … |

`getsymprof` takes `deltas` of `vmed`, which is what establishes it as cumulative and
not per-bucket.

### 1.2 A deliberate deviation

`getsymprof` computes `vtot_regular: adv_regular + open_regular + close_regular` — three
terms. It omits `vopenpm`. For a lunch-break name the resulting shares therefore sum to
slightly more than 1.

**This app includes `v_open_pm` in the total.** Percentages will differ from the q
report by roughly `v_open_pm / vtot` for such names (about 0.002% for the example above —
immaterial in size, but correct). The README states this so a discrepancy against the q
report is never a mystery.

---

## 2. Placement and boundaries

`core-vp/` is a **standalone** Streamlit app: its own venv, its own `requirements.txt`,
no imports into `algo-order-monitor` or `kdbmonitor`. Those are separate git repos in the
same parent directory; a cross-repo import breaks the moment either one moves. Patterns
are **copied and adapted**, not depended on.

```
core-vp/
  app.py                  sidebar (date · symbol · refresh) + three panels
  core/
    profile.py            raw vst rows        -> Profile          pure
    session.py            buckets             -> Session          pure
    schedule.py           target + Profile    -> expected/actual  pure
    realized.py           qatt ticks          -> realised curve   pure
    provider.py           DataProvider ABC + make_provider()
    provider_kdb.py       pykx implementation
    provider_demo.py      synthetic implementation
    connections.py        endpoint registry + KdbClient
  ui/
    charts.py             plotly figure builders
    panels.py             the three panels
    tables.py             the bucket table
  config/
    connections.json      gitignored
  tests/
  README.md
```

The four modules above `provider` take DataFrames and return DataFrames, with no I/O and
no Streamlit import. That is what makes them testable on a machine with no kdb and no
pykx, which is the machine this is being built on.

---

## 3. Components

### 3.1 `core/profile.py`

```python
@dataclass(frozen=True)
class Profile:
    sym: str
    date: dt.date
    adv: float          # time=0
    v_open: float       # time=1
    v_close: float      # time=2
    v_open_pm: float    # time=3
    buckets: pd.DataFrame   # minute, clock, cum_frac, share, share_of_day
    session: Session

def decode_profile(raw: pd.DataFrame, sym: str, date: dt.date) -> Profile
```

Rules:

- **Header skip**: `int(raw.cc0.iloc[0])` when `cc0` is present; otherwise the index of
  the first row with `time >= 100`. Neither `getsymprof`'s `n:10` nor `idxprof`'s `11_`
  survives a symbol with a different number of pre-open rows. `cc0` is the value that
  actually says, and the fallback is derived from the data rather than assumed.
- `clock = minute × 60000 ms`, matching `getsymprof`'s `"t"$60000*time`.
- `share = cum_frac.diff()`, first bucket `0` — `getsymprof`'s `deltas`, kept explicit.
- **Auction normalisation**: `vtot = adv + v_open + v_close + v_open_pm`; continuous
  shares scaled by `adv/vtot`; each auction becomes its own bucket. `share_of_day`
  sums to exactly 1.
- **Auction placement**: the PM reopen is derived — it is the end of the lunch gap.
  The open and close print times are market facts absent from the rows, so they come
  from `MARKET_AUCTIONS` in `core/markets.py` and are validated against the derived
  session; an entry that disagrees is not drawn, the auction falls back to bracketing
  the session, and a warning is raised. TSE moved its close in Nov 2024, so this table
  must be assumed to drift.

Rejects, loudly, rather than producing a misleading chart: an empty frame; a
`cum_frac` that is not non-decreasing; a final `cum_frac` not within tolerance of 1.

### 3.2 `core/session.py`

```python
@dataclass(frozen=True)
class Session:
    open_min: int
    close_min: int
    lunch: tuple[int, int] | None
    has_pm_auction: bool
```

`derive_session(buckets, v_open_pm)`. The lunch break is the largest gap between
consecutive bucket minutes exceeding **2× the median spacing** (China: 690 → 780, a
90-minute gap against a 10-minute median; Tokyo: 630 → 690, 60 minutes against the
same median — both confirmed against real gateway results).
`has_pm_auction = v_open_pm > 0`.

**Clock.** The gateway and `qatt` both report in HKT (UTC+8) regardless of the
symbol's market, confirmed for `7203.JP`. `minute` therefore stays on the region
clock throughout, so all three sources join without conversion; `core/markets.py`
shifts **labels only**, resolving the offset per date through the tz database so
DST markets stay correct.

No per-market table to maintain, and it self-checks: `v_open_pm > 0` with no detected
gap means the data contradicts itself, and the app says so instead of drawing it.

### 3.3 `core/schedule.py`

```python
def expected_curve(profile: Profile, order: pd.Series) -> pd.DataFrame
def actual_curve(executions: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame
```

**Expected** — the profile clipped to `[t_start, t_end]`, renormalised over that window,
multiplied by `size`. `doopen` / `doclose` decide whether each auction bucket is part of
the schedule.

**Actual** — three series, because two of them are routinely confused:

| Series | Source | Reads as |
|---|---|---|
| `filled` | `execution.cum_qty` | where the order actually is |
| `committed` | `target_state.commit_open + commit_close` | quantity **reserved** for the auctions |
| `filled_plus_committed` | sum of the two | where it is including what it is holding back |

`execution.cum_qty` is already cumulative per fill, so the curve is a step line off one
column — exact, and needing no re-aggregation. `target_state.make` moves only on state
changes and so sits flat between fills; it is the cross-check, not the primary.

The `committed` series exists because a VWAP order reserving quantity for the close
reads as *behind schedule* on a naive filled-vs-expected chart when it is doing exactly
what it was told. The gap between `filled` and `filled_plus_committed` makes the reserve
visible rather than leaving it to be misread as slippage.

### 3.4 `core/realized.py`

```python
def realized_curve(qatt: pd.DataFrame, profile: Profile,
                   open_print_size: float | None) -> pd.DataFrame
```

Buckets `qatt` trade sizes onto the profile's own grid, then follows
`getsymprof_realRT`: subtract the opening print from whichever bucket contains it and
seat it in the first bucket instead, so the auction is not double-counted into the
continuous curve. Returns cumulative and per-bucket, both raw and normalised.

### 3.5 `core/provider.py`

An ABC with a demo and a pykx implementation, and `make_provider(conn, force_demo)`:

```python
get_profile(date, sym)            -> pd.DataFrame   # raw vst rows
list_vwap_orders(date, filters)   -> pd.DataFrame   # target where algo=`VWAP
get_order(date, id_server, id_target)
get_executions(date, id_server, id_target)
get_target_state(date, id_server, id_target)
get_qatt(date, sym)
available_dates()
```

`provider_demo` generates a plausible two-session profile, a handful of VWAP orders at
various states of completion (including one visibly reserving for the close), and `qatt`
ticks that run ahead of the profile in the morning. It is what the app runs on here, and
what the render tests exercise.

### 3.6 `core/connections.py`

Three independently-reachable endpoints, since they are three different processes:

| Endpoint | Serves | Live / historical |
|---|---|---|
| Volume Profile gateway | `get_data_by_date` → `vst` / `latest_vst` | one host |
| OMS | `target`, `target_state`, `execution` | `OMSR` / `OMSH` |
| Market data | `qatt` | `QATTR` / `QATTL` |

The selected date decides live-vs-historical, as in `algo-order-monitor`: today → the
real-time process, any other date → the historical one. A future date is treated as
historical, so clock skew cannot silently point at the live server.

---

## 4. The three panels

One shared minutes-of-day x-axis across all three, so they read as a single picture.
Pre-open, lunch and auction windows drawn as bands on every chart.

**Panel 1 — Profile.** KPI row (ADV · open · close · PM · buckets · busiest bucket) →
cumulated line against an even-pace reference → per-bucket bar against the average-bucket
reference → the bucket table (`Time | cumulated | this bucket | even pace`). This is the
`volume_profile_dashboard.json` layout.

**Panel 2 — Order progression.** Search `target` for the date where ``algo=`VWAP``,
filter by sym / trader / basket, pick one. Then expected vs filled vs
filled-plus-committed, with an ahead/behind band between expected and filled. KPIs:
filled %, schedule %, ahead/behind in shares and in % of order, participation, reserved
for close.

**Panel 3 — Profile vs today.** The median profile against today's realised `qatt`
volume, cumulative and per-bucket, both normalised. KPIs: today's volume vs ADV, and how
far ahead or behind the day is running.

---

## 5. Error handling

The rule is `algo-order-monitor`'s: **a gap is a gap.** Missing data breaks the line
rather than running flat through it, and an unavailable metric shows an em dash with the
reason rather than `0`.

- Each panel degrades on its own. One endpoint down greys that panel with the endpoint
  and the error; the other two keep working.
- A symbol with no profile says so, rather than drawing an empty axis.
- `qatt` queried down the order-server handle **returns nothing rather than raising** —
  the silent misconfiguration `connections.py` warns about. The config page therefore
  probes each table against the endpoint that should serve it, and reports per table.
- A profile failing the `decode_profile` checks in §3.1 reports which check failed.

---

## 6. Testing

Everything below runs with no kdb and no pykx.

- `decode_profile` against a fixture built from the exact rows photographed for
  `000001.C2` — header values, the cumulative-to-share step, and the normalisation.
- `derive_session` for a lunch-break market and a continuous one, plus the
  contradiction case (`v_open_pm > 0`, no gap).
- `expected_curve` for `doopen`/`doclose` on and off, and for a window narrower than
  the session.
- `actual_curve` — that `committed` is separated from `filled`, and that an order
  reserving for the close is not reported as behind.
- `realized_curve` — the opening print is re-seated into the first bucket and not
  counted twice.
- A render smoke test over the demo provider, mirroring
  `algo-order-monitor/tests/test_all_pages_render.py`.

---

## 7. Out of scope

- Writing anything back to kdb. The app is read-only.
- Multi-symbol or basket-level profiles (`getregprof`, `getindexprof`,
  `getMultiSymProf` exist in `vproflib.q` and are a later step).
- Non-VWAP algos in panel 2.
- Any change to `avon-vp/`, which stays exactly as it is.

---

## 8. Open items for implementation

1. ~~**The gateway's real signature.**~~ RESOLVED: the dataset alias is always
   `profile`, and the argument order is as written above. The gateway had a bug
   that reported `not_a_valid_table`; introspection is closed on that handler, so
   `count`-style probes are invalid and Sources -> Test issues a real call instead.
2. **Whether `cc0` is selectable through the gateway.** If it is not, the header skip
   falls back to the `time >= 100` rule, which is already the specified fallback.
3. **Whether VWAP orders in practice use `t_start`/`t_end`.** If they always run the
   full day, the clipping in `expected_curve` is dead weight and comes out.
