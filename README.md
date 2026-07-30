# Volume Profile Viewer

A single-file HTML viewer for intraday volume profile CSVs. Open a file, pick an
instrument, and read its cumulated curve, its per-bucket shares, and the full
bucket table.

No build step, no dependencies, no network calls. One `.html` file you can mail
or drop into a chat, and it opens in any modern browser. The CSV is read locally
via `FileReader` and never leaves the machine.

## Use it

1. Open `volume-profile.html` in a browser.
2. Drop a CSV on the page, or click to browse.
3. Type an instrument code and press <kbd>Enter</kbd>.
4. Optionally narrow **Scale from / to** to the buckets the vertical axis should
   be read against.

`sample_india_volume_profile.csv` is included so you can try it immediately.

## Sending one to a client

Give the client the file **once**. It re-reads the data every time it is opened,
so it never has to be replaced.

Edit the `CONFIG` block at the top of the `<script>` in `volume-profile.html`:

```js
const CONFIG = {
  url: "https://data.example.com/profiles/{yyyy}-{mm}-{dd}.csv",
  select: "RELIANCE.IN",   // "" to land on the picker instead
  lookback: 5,
  timeoutMs: 15000
};
```

That is the whole setup. No build step, no tooling, nothing to install. Send the
file; publish a new CSV to that address each day and every client sees it on
their next open. The **Refresh** button re-pulls without reopening.

| Field | |
|---|---|
| `url` | where the CSV lives. `{yyyy}` `{mm}` `{dd}` `{yyyymmdd}` become today's date |
| `select` | instrument to open on. Empty lands on the picker, data already loaded |
| `lookback` | days to walk back when a date is not published yet (weekends, holidays, early mornings) |
| `timeoutMs` | how long to wait for a slow host |

The header always states which date is on screen, and marks it in red when it is
older than yesterday, so nobody reads stale data believing it is today's. If the
address cannot be reached the page says why and falls back to letting the user
open a file by hand.

### The one requirement

**The host must send `Access-Control-Allow-Origin: *`.**

A file opened by double-click runs on `file://`, whose origin is `null`. The
browser blocks it from reading anything unless the server explicitly allows any
origin. This is not something the page can work around.

- **Works**: S3, CloudFront, Azure Blob, Cloudflare R2, GitHub Pages, any
  nginx/Apache/IIS with the header configured.
- **Does not work**: SharePoint, OneDrive, Windows file shares (`\\server\path`),
  or any endpoint requiring a login. These reject a `null` origin, and no
  amount of loader code changes that.

That constraint is also why fetching a *local* CSV sitting next to the HTML is
impossible: `fetch()` does not implement the `file:` scheme at all, and
`XMLHttpRequest` to a local file is blocked without launching the browser behind
`--allow-file-access-from-files`.

Anything published at that URL is readable by anyone who has it, so use an
unguessable path or a signed URL if the profiles are not public.

### If the client has no network

There is a second slot, `<script id="embeddedProfile">` near the top of the file.
Paste a CSV between its tags and the page opens straight into it with no request
at all. Data is then fixed at the moment you paste, so this only suits a one-off
send. It is a plain text paste; no tooling involved.

## Input format

A metadata comment line, a header row (the leading `#` is optional), then one row
per time bucket:

```
#TimeZone=India Standard Time,format=V2,isweekly=false
#FidessaCode,ReutersCode,Venue,TimeZone,Time,CumulatedPercentage
ICICIBC.IN,ICBK.NS,NSI-MAIN,India Standard Time,9:15:00,0.0215
ICICIBC.IN,ICBK.NS,NSI-MAIN,India Standard Time,9:20:00,0.0431
```

`CumulatedPercentage` is cumulative, so each bucket's own share is the difference
from the previous row. The viewer computes that for you.

Parsing is deliberately tolerant, because these files get re-saved through Excel:

- delimiter auto-detected (`,` `;` tab `|`)
- decimal commas (`0,0215`)
- cumulated values as either `0..1` or `0..100`, detected from the data
- unpadded times (`9:15:00`), `HH:MM`, or Excel time serials
- a missing `#` on the header row, or a missing `ReutersCode` column
- instruments keyed by code **and** venue, so multi-venue files list them separately

Malformed rows are skipped and counted rather than failing the whole file.

## Time zones

The `TimeZone` column (falling back to the file's `#TimeZone=` line) is resolved
and every bucket is converted to the viewing machine's zone.

`India Standard Time` is a *Windows* zone name rather than an IANA id, so the
viewer carries a lookup table of ~140 Windows names, plus bare abbreviations
(`IST`, `CET`, `JST`) and literal offsets (`UTC+05:30`). Raw IANA ids pass
through untouched. Offsets are resolved through `Intl` at a reference date, so
daylight saving is computed rather than assumed. The date field lets you check a
different DST period.

Buckets that land on another calendar day are marked `-1d` / `+1d`, and rows stay
in session order rather than resorting around midnight. So 09:15 in Mumbai reads
as 05:45 in Paris, 13:45 in Sydney, and 23:45 `-1d` in New York.

A **Local / Source** toggle switches back to the file's own times. When the two
zones differ, the table shows both.

## Reading the charts

- **Cumulated volume**: share of the day traded up to each bucket. The dashed
  *even pace* line is what a flat, volume-blind schedule would trace, so
  front-loading and back-loading read at a glance.
- **Volume per bucket**: each bucket's own share, with a dashed *average bucket*
  reference.
- The shaded band at the left is the pre-open stretch, where the curve is flat by
  construction.

## Scale window

A closing auction can be 15-20% of the day, which flattens every intraday bar
against an axis tall enough to hold it. **Scale from / to** picks the stretch of
the session the vertical axis is computed from - leave the auction out and the
intraday shape gets the full height.

Both ends are dropdowns of the loaded instrument's own buckets, so the window can
only ever land on a real bucket; moving one end past the other pushes the other
along. **Full session** returns to the whole day.

Both charts are restricted to it: only the window's buckets are drawn and both
time axes narrow to them, so the two always cover the same period. Each captions
the window it is on and how far into the day it reaches.

- **Volume per bucket** takes its ceiling from the tallest bar on screen, so
  nothing there is ever off-scale. Bars stay shares *of the day*, so they can be
  compared between windows.
- **Cumulated volume** is rebased on the window: the curve still runs 0 to 100%,
  but of the volume traded inside the window rather than of the day. The caption
  says what that 100% is worth - "100% here is the 17.4% of the day that trades
  inside the window" - and the hover lists the day figure and the window figure
  side by side, so the crosshair reading is never ambiguous.

The two dashed references therefore answer different questions:

- *even pace* follows the curve's units. Inside a window it is a flat schedule
  over the window's own buckets, which is the only reference in the same units as
  a rebased curve; the day's pace line put through the same rebasing would usually
  leave the top of the axis. Read the window's share in the caption to see how the
  stretch sits against the day.
- *average bucket* stays the whole session's average, matching the bars, which are
  still day shares. When a narrow window's ceiling falls below it, the label says
  so rather than drawing it.

Hovering still syncs both charts and the table. The table always lists the full
session, so a row outside the window has nothing to point at on either chart:
both drop their crosshairs while the row itself still highlights. **Export
selection** is always the full session too.

The window survives a **Local / Source** flip, relabelled into the zone on show.
Picking another instrument starts again on the full session.

Hovering either chart syncs the crosshair, the bars, and the table row. With a
chart focused, arrow keys, <kbd>Home</kbd> and <kbd>End</kbd> do the same. Table
columns sort, and **Export selection** writes the visible instrument out as CSV
with both source and converted times.

## Sample data

`sample_india_volume_profile.csv` is **synthetic**. The instrument codes are real
NSE constituents, but the volume curves are generated: a U-shaped intraday
profile with a heavy open, a midday lull, and a closing-auction spike, each
normalised to close on exactly 1. It contains no real market or client data. It
exists to exercise the viewer, not to describe any actual trading day.
