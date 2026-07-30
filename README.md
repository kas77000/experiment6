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

## Publishing it to users

Hand the file over **once**. It re-reads its data every time it is opened, so it
never has to be replaced. Edit the `CONFIG` block at the top of the `<script>`
and send it.

### From a shared drive

Put `volume-profile.html` on the share, with the profiles in a folder beside it:

```
\\server\team\volume-profile.html
\\server\team\profiles\2026-07-30.js
```

```js
const CONFIG = {
  dataFile: "profiles/{yyyy}-{mm}-{dd}.js",
  select: "RELIANCE.IN",   // "" to land on the picker instead
  lookback: 5,
  timeoutMs: 15000
};
```

Keep the path **relative** and the same file works from `\\server\share` or a
mapped `Z:\` without change. Drop a new file on the share each morning and
everyone sees it next time they open the page. No server, no network, no install.

The data has to be published as **JavaScript, not raw CSV**: one line wrapping
the CSV text.

```js
VP_PROFILE = "…the whole CSV as a JSON string…";
```

Built-in PowerShell writes it, so there is nothing to install:

```powershell
"VP_PROFILE = " + (ConvertTo-Json ([IO.File]::ReadAllText("today.csv"))) + ";" |
    Set-Content -Encoding utf8 "\\server\team\profiles\2026-07-30.js"
```

`make-profile-js.ps1` in this repo does the same with argument checking:

```powershell
.\make-profile-js.ps1 -Csv today.csv -OutDir \\server\team\profiles
```

Add that line to whatever job already drops the CSV on the share.

> **Why JavaScript and not the CSV directly.** A page opened by double-click runs
> on `file://`, and browsers refuse to let it read a neighbouring file: `fetch()`
> does not implement the `file:` scheme at all, `XMLHttpRequest` is blocked, and
> reading an `<iframe>` is blocked. A `<script>` tag is the one exception, since
> script loading is exempt from the same-origin check. That is the whole reason
> for the wrapper, and it is why the earlier auto-load could not work.

### From a web host

If the profiles are on a web server instead, point `url` at the CSV directly and
skip the wrapper:

```js
url: "https://data.example.com/profiles/{yyyy}-{mm}-{dd}.csv",
```

**That host must send `Access-Control-Allow-Origin: *`**, because a
double-clicked page has origin `null`. S3, CloudFront, Azure Blob, Cloudflare R2,
GitHub Pages and configured nginx/Apache/IIS qualify. SharePoint, OneDrive and
anything behind a login do not: use `dataFile` for those. Anything at that URL is
readable by whoever has it, so use an unguessable path or a signed URL if the
profiles are not public.

### Either way

| Field | |
|---|---|
| `dataFile` | path to the `.js` wrapper, relative to the HTML. For shared drives |
| `url` | http(s) address of a CSV. Needs the CORS header above |
| `select` | instrument to open on. Empty lands on the picker, data already loaded |
| `lookback` | days to walk back when a date is not published: weekends, holidays, mornings before the job runs |
| `timeoutMs` | how long to wait before giving up |

`{yyyy}` `{mm}` `{dd}` `{yyyymmdd}` in either path become the date at the moment
the page opens.

The header states which date is on screen and turns it red once it is older than
yesterday, so stale data is never mistaken for today's. **Refresh** re-reads
without hunting for the file again. If nothing can be loaded the page says
exactly what it looked for and why it failed, then falls back to letting the user
open a file by hand.

### One-off sends

There is also `<script id="embeddedProfile">` near the top of the file. Paste a
CSV between its tags and the page opens straight into it, carrying its own data
and reading nothing. Fixed at the moment you paste, so it suits a single send
rather than a daily one.

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
