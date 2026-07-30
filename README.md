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

`sample_india_volume_profile.csv` is included so you can try it immediately.

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
  reference. Where a closing auction dwarfs the intraday buckets, a
  **Full / Intraday** control appears and rescales the axis; a bar that runs off
  the top gets explicit break marks and its true value, so it can never be
  misread as shorter than it is.
- The shaded band at the left is the pre-open stretch, where the curve is flat by
  construction.

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
