# Volume Profile Viewer

Reads intraday volume profile CSVs and charts them: the cumulated curve, the
share traded in each bucket, and the full bucket table. No dependencies, no build
step, no network calls. Everything runs in the browser, and the data never leaves
the machine.

There are two things here.

## 1. `volume-profile.html`

Open it, drop a CSV on the page or click to browse, type an instrument code and
press <kbd>Enter</kbd>. One file, nothing to install, fine to mail or paste into
a chat.

`sample_india_volume_profile.csv` is included so you can try it straight away.

## 2. `Volume-Profile.bat`

One file the user double-clicks. It reads the profile from the share and opens
the charts: no file to locate, nothing to install, nothing on the share but the
CSV.

Build it:

```powershell
.\build-single-file.ps1 -Csv "\\server\team\profiles\profile.csv"
```

That produces `Volume-Profile.bat`, about 70 KB, with the whole viewer folded
inside it. Hand that one file out. Run the build again whenever
`volume-profile.html` changes.

The share path can also be edited afterwards: it is the first line of the file.

```bat
set "VP_CSV=\\server\team\profiles\profile.csv"
```

Keep the CSV name fixed and overwrite it whenever you like. Every click reads
whatever is there at that moment, so the file is handed out once and never
replaced. A mapped drive (`Z:\profiles\profile.csv`) works the same way.

If the share is unreachable, or the file is not a volume profile, the window
stays open with the reason.

### How it works

`cmd` runs the few lines at the top and exits before reaching the rest.
PowerShell then re-reads the file, takes its own section from between the
markers and the viewer from after the last one, drops the CSV in, writes the
result to `%LOCALAPPDATA%\VolumeProfile\volume-profile.html` and opens it.

A `<script>` tag is the only way a page opened by double-click can read another
local file, and it must be valid JavaScript, so a share holding nothing but CSVs
cannot be read by the browser alone. PowerShell has no such restriction. That is
the whole reason the launcher exists.

Neither file picks an instrument for you. Which one comes first depends on the
export, so both open on the list.

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
from the previous row. The viewer works that out.

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
and every bucket converted to the viewing machine's zone.

`India Standard Time` is a *Windows* zone name rather than an IANA id, so the
viewer carries a lookup table of ~140 Windows names, plus bare abbreviations
(`IST`, `CET`, `JST`) and literal offsets (`UTC+05:30`). Raw IANA ids pass
through untouched. Offsets are resolved through `Intl` at a reference date, so
daylight saving is computed rather than assumed. The date field lets you check a
different DST period.

Buckets landing on another calendar day are marked `-1d` / `+1d`, and rows stay
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

Hovering either chart syncs the crosshair, the bars and the table row. With a
chart focused, arrow keys, <kbd>Home</kbd> and <kbd>End</kbd> do the same. Table
columns sort, and **Export selection** writes the visible instrument out as CSV
with both source and converted times.

### Scale window

A closing auction can be 15-20% of the day, which flattens every intraday bar
against an axis tall enough to hold it. **Scale from / to** picks the stretch of
the session the vertical axis is computed from: leave the auction out and the
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
  says what that 100% is worth, and the hover lists the day figure and the window
  figure side by side.

The two dashed references therefore answer different questions. *Even pace*
follows the curve's units, so inside a window it is a flat schedule over the
window's own buckets. *Average bucket* stays the whole session's average,
matching the bars, which are still day shares; when a narrow window's ceiling
falls below it, the label says so rather than drawing it.

The table always lists the full session, so a row outside the window has nothing
to point at on either chart: both drop their crosshairs while the row itself
still highlights. **Export selection** is always the full session too.

The window survives a **Local / Source** flip, relabelled into the zone on show.
Picking another instrument starts again on the full session.

## Sample data

`sample_india_volume_profile.csv` is **synthetic**. The instrument codes are real
NSE constituents, but the volume curves are generated: a U-shaped intraday
profile with a heavy open, a midday lull and a closing-auction spike, each
normalised to close on exactly 1. It contains no real market or client data. It
exists to exercise the viewer, not to describe any actual trading day.
