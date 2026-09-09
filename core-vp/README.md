# core-vp

Is this VWAP order tracking the volume profile, and is the day itself tracking it?

A read-only Streamlit app over the Argo platform's profile, order and market-data
servers. Three panels on **one shared minutes-of-day axis**, so they read as a single
picture rather than three charts that happen to be stacked.

It runs out of the box on **demo data** — no kdb+, no pykx — so the UI can be explored
immediately, then pointed at real servers on the Sources tab.

## Quick start

```bash
cd core-vp
python -m venv .venv && .venv\Scripts\activate       # Windows
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501.

## The three panels

**Volume profile** — ADV, the three auctions, and the bucket count as KPIs; the
cumulated curve against an even-pace reference; the share traded in each bucket
against the average bucket; the full bucket table.

**Order progression** — pick a VWAP order for the date, and see three lines:

| Line | Source | Reads as |
|---|---|---|
| expected | profile × `size`, clipped to `t_start`/`t_end` | where the schedule says it should be |
| filled | `execution.cum_qty` | where it actually is |
| filled + committed | `+ commit_open + commit_close` | including what is reserved for the auctions |

The third line is the point. A VWAP order reserving quantity for the close reads as
*behind schedule* on a naive filled-vs-expected chart while doing exactly what it was
told. The gap between `filled` and `filled + committed` is that reserve, shown rather
than left to be misread as slippage — and the band between expected and filled is
deliberately **neutral grey, not red**, for the same reason.

**Profile vs today** — the median profile against today's realised `qatt` volume,
cumulative and per bucket.

Two normalisations, and the default matters. Measuring today against **a median day
(ADV)** lets a heavy day end above 100%, so level and shape are both readable, and an
intraday curve simply stops where it has got to. Measuring it against **the day's own
volume** compares shape alone — and forces both curves to meet at 100%, so the
divergence at the close is zero *by construction*. The first is the default for that
reason; the second is one click away when only shape is of interest.

## Picking the symbol

The sidebar lists the symbols with a **VWAP order working on that date**, read from
`target`, rather than asking for a code to be typed blind. All three panels then
describe one symbol — which is what makes them comparable on a shared axis — and the
order list in panel 2 is scoped to it, so an order can never be measured against
another symbol's profile. `other...` takes a free-text code for a symbol with no order.

## How the profile is decoded

The gateway call is:

```q
get_data_by_date[`profile;`date`sym`vmed`time`cc0;2026.07.29;2026.07.29;`000001.C2]
```

Row layout, per `ai3/src/com/kas/ai/kdb/idxprof.q:37-42`:

| `time` | meaning |
|---|---|
| 0 | `adv` — median daily **continuous** volume |
| 1 | `vopen` — open auction volume |
| 2 | `vclose` — close auction volume |
| 3 | `vopenpm` — **PM reopen auction** volume (lunch-break markets) |
| ≥ 100 | minutes-of-day; `vmed` is a **cumulative fraction** |

`getsymprof` in `vproflib.q` takes `deltas` of `vmed`, which is what establishes it as
cumulative rather than per-bucket.

**The header-row count comes from `cc0` on row 0** (`load_equity_special.q:128`), not
from a constant. `getsymprof`'s `n:10` and `idxprof`'s `11_` both hard-code it, and
neither survives a symbol with a different number of pre-open rows. When the gateway
will not serve `cc0`, the app retries without it and falls back to "the first row with
`time >= 100`", then keeps the last zero row — that row is the session open, where the
cumulative curve legitimately stands at zero.

### One deliberate difference from the q code

`getsymprof` computes `vtot_regular: adv_regular + open_regular + close_regular` —
three terms. It omits `vopenpm`. For a lunch-break name its shares therefore total
slightly more than 1.

**This app includes `v_open_pm` in the total.** Percentages will differ from the q
report by `v_open_pm / vtot` — about **0.002%** for `000001.C2` (2,000 against a
106,403,529 total). Immaterial in size, but correct, and worth knowing about before
someone chases the discrepancy.

The session — open, close, and any lunch break — is **derived from the bucket minutes**
(the largest gap exceeding twice the median spacing), not from a per-market table. It is
verified against two very different real profiles: Shenzhen's 90-minute lunch and
Tokyo's 60-minute one. A profile reporting a PM auction with no lunch gap contradicts
itself, and the app says so rather than drawing it.

### Times are on the region clock

The gateway **and** `qatt` both report in HKT (UTC+8), whatever the symbol's own market.
Shenzhen is on UTC+8, so `570 == 09:30` there is local time by coincidence. Tokyo is
not: `7203.JP` opens at `480` (08:00 HKT = **09:00 JST**) and breaks `630`→`690`
(10:30–11:30 HKT = **11:30–12:30 JST**, the TSE lunch, exactly).

Because both sources share that clock, **`minute` stays on the region clock everywhere** —
profile buckets, `qatt` trades and order timestamps join with no conversion, and one
shared axis stays meaningful. Only the **labels** are shifted, by
`core/markets.py`, which maps the symbol suffix to an IANA zone and resolves the offset
**per date through the tz database**. That is why it is not a static table: Sydney is
+2h from Hong Kong in July and +3h in January, and a fixed number would be wrong for
half the year. An unknown suffix shifts nothing and says so.

The header caption names the clock on screen — *"times shown in Tokyo time (UTC+9)"* —
so a shifted axis is never silent.

### Where the auction buckets sit

The three auctions are drawn at the minute they actually print:

| Auction | Where it comes from |
|---|---|
| PM reopen | **Derived** — it *is* the end of the lunch gap, which the rows give us |
| Open | `MARKET_AUCTIONS` in `core/markets.py` |
| Close | `MARKET_AUCTIONS` in `core/markets.py` |

So `7203.JP` shows **09:00 / 12:30 / 15:30** and `000001.C2` shows **09:25 / 13:00 /
15:00**, in each market's own local time.

Open and close print times are market facts that are not in the profile rows, so they
are the one hand-maintained table here — and **they change**: TSE moved its close from
15:00 to 15:30 in November 2024. `decode_profile` therefore validates every listed time
against the session it derived from the data (the open must not fall after the session
opens, the close must not fall before it ends). A stale entry is **not drawn**: the
auction falls back to sitting beside the session and the panel shows a warning saying
so. Markets not listed get that same bracketing behaviour with no warning — being
absent is fine, being wrong is not.

## The three servers

These are three different kdb+ processes and they fail independently. One being down
greys its own panel and leaves the other two working.

| Endpoint | Serves | Live / historical |
|---|---|---|
| Volume profile | `get_data_by_date` → the VPROF tables | one host |
| Orders | `target`, `target_state`, `execution` | `OMSR` / `OMSH` |
| Market data | `qatt`, `open_print` | `QATTR` / `QATTL` |

The date decides which: today is live, anything else is historical. A *future* date is
treated as historical, so a clock skew cannot silently point at the live server.

`qatt` sent down the order-server handle **returns nothing rather than raising**, so
that misconfiguration looks like missing market data. Sources → Test therefore probes
each table against the endpoint that is supposed to serve it, and reports per table.

### The profile dataset

The first argument of `get_data_by_date` is a gateway **dataset alias** — always
`` `profile ``. It is **not** an HDB table name: the `vst` / `vst05d` / `vst10d` /
`vst20d` tables that `load_vprof.q` builds, and the `latest_vst` that `vproflib.q`
maintains, are what the gateway maps *from*, and passing one of them is rejected.

The value stays editable on the Sources tab in case another dataset is exposed later,
but there is nothing to choose today.

The gateway accepts whitelisted call forms only — a bare identifier is answered with
"not a valid command" — so `count profile` is **not** a valid health check there.
Sources → Test therefore probes it with a real `get_data_by_date` call, which is why
that tab asks for a test symbol and date. Without them the profile row reports *not
checked* rather than a misleading pass or fail.

### How a query is sent

Arguments go as **arguments**, never interpolated into a query string, following the
pattern the working scripts in `kdb-queries` use against these same servers — e.g.
`liquidity_profile.py`:

```python
prof = hq(".lp.profile", sym.encode(), dtq, bkt).pd()
```

Three things matter there, and all three are load-bearing:

| | Why |
|---|---|
| `SyncQConnection(no_ctx=True)` | What every working script here uses, plus the context interface **off** — see below. No q licence and no `QHOME` are needed, because all evaluation happens on the server. |
| arguments, not a string | Interpolating means hand-formatting dates and symbols and hoping q parses them back into the right types. Passing them lets pykx convert. |
| **`sym.encode()`** | pykx turns a Python `str` into a q **char vector**, *not* a symbol. Bytes is what makes it a symbol. |

That last one has a signature failure: passing a `str` where q wants a symbol surfaces
as `AttributeError: 'CharVector' object has no attribute '_context_keys'`, which names
neither the symbol nor the argument. `core.connections.qsym()` exists so the conversion
is never left to chance.

#### The context interface must be off

`no_ctx=True` is not optional against this gateway. Building a connection, pykx sets
up its context interface and evaluates `self.ctx.q` — which resolves the name **`q` in
the remote namespace**. The VPROF gateway already uses `q` for a char vector of its
own, so pykx gets a string where it expects its handle and dies **in the constructor**,
before any query is sent:

```
pykx/ipc.py, line 654, in _init          super().__init__()
pykx/__init__.py, line 129, in __init__  *self.ctx.q._context_keys,
AttributeError: 'CharVector' object has no attribute '_context_keys'
```

The order and qatt servers do not define a global `q`, which is why only the gateway
fails and why other pykx scripts on the same machine are unaffected. Nothing here uses
the context interface — every call names its function explicitly — so turning it off
costs nothing and removes a whole class of failure from names on the server colliding
with pykx's own.

A reply that is a q **string** rather than a table — which is how a restricted gateway
reports a rejected call — is raised with the server's own message attached, rather than
being converted into an empty frame that would read as "no rows for this symbol".

## Layout

```
core/       profile · session · schedule · realized   pure, DataFrame in/out
            markets                                   display timezone only
            provider · provider_demo · provider_kdb · connections
ui/         charts · panels · tables
app.py
```

Nothing under `core/` imports streamlit or plotly, and `pykx` is only ever imported
inside a function. `tests/test_layering.py` enforces both. That is what lets the whole
decoding layer — the part where correctness actually lives — be tested with none of
them installed.

## Tests

```bash
python -m pytest -q
```

No kdb+, no pykx, no network. Two fixtures are transcribed from real gateway results
and the decoder is tested against both:

| Fixture | Exercises |
|---|---|
| `000001.C2` (Shenzhen) | 90-minute lunch, tiny PM auction (2,000), `cc0` present |
| `7203.JP` (Tokyo) | 60-minute lunch, large PM auction (247,700), **no `cc0`**, one extra pre-open row, a closing auction worth 23% of the day, and a non-UTC+8 clock |

The second is why the `cc0` fallback matters: that result has seven pre-open rows to
Shenzhen's six, so `getsymprof`'s hard-coded `n:10` would be off by one on it.

## Colour

The dataviz reference palette, dark steps, slots 1–3 only (blue `#3987e5`, orange
`#d95926`, aqua `#199e70`) — the set documented as clearing every pair gate in both
modes. Reference lines are muted grey and dashed: a reference is not a competing
identity. No chart has a second y-axis.
