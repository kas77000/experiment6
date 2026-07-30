#!/usr/bin/env python3
"""
Build a client-ready volume profile viewer with the data baked in.

Takes the viewer template and a profile CSV, and writes one self-contained HTML
file that opens straight into that profile. The client double-clicks it and sees
the charts: no file to locate, no picker, no server, no network request.

    python build-client-file.py --csv today.csv --out client/profile_2026-07-30.html
    python build-client-file.py --csv today.csv --out x.html --select RELIANCE.IN
    python build-client-file.py --csv today.csv --out x.html --only RELIANCE.IN,TCS.IN

Why baked in rather than fetched: a page opened by double-click runs on file://,
and browsers will not let it read anything else. fetch() does not implement the
file: scheme, XHR to a sibling file is blocked without a browser flag, and an
https:// call from file:// sends "Origin: null", which SharePoint, OneDrive and
Windows file shares refuse. Embedding removes the request entirely.

Exit codes: 0 ok, 1 bad input, 2 template problem.
"""

import argparse
import datetime as dt
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SLOT = re.compile(
    r'(<script id="embeddedProfile" type="text/plain")([^>]*)(></script>)',
    re.I,
)


def fail(msg, code=1):
    sys.stderr.write("error: %s\n" % msg)
    raise SystemExit(code)


def read_text(path):
    """Read a CSV whatever encoding the exporting system used."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8")
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    fail("could not decode %s as text" % path)


def filter_instruments(csv, keep):
    """Keep only the named codes, so a client file carries just their names."""
    want = {k.strip().upper() for k in keep.split(",") if k.strip()}
    if not want:
        return csv, 0

    out, kept, header_done = [], set(), False
    for line in csv.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # metadata and header lines pass through untouched
        if stripped.startswith("#") and not header_done:
            out.append(line)
            if "cumulated" in stripped.lower():
                header_done = True
            continue
        if not header_done and re.search(r"cumulated", stripped, re.I):
            out.append(line)
            header_done = True
            continue
        cells = re.split(r"[,;\t|]", stripped)
        code = cells[0].strip().upper()
        alt = cells[1].strip().upper() if len(cells) > 1 else ""
        if code in want or alt in want:
            out.append(line)
            kept.add(code)

    missing = want - {c.upper() for c in kept}
    if missing:
        # a silently missing instrument would ship an empty file to a client
        fail("not found in the CSV: %s" % ", ".join(sorted(missing)))
    return "\n".join(out) + "\n", len(kept)


def count_instruments(csv):
    codes, header_done = set(), False
    for line in csv.splitlines():
        s = line.strip()
        if not s:
            continue
        if not header_done:
            if re.search(r"cumulated", s, re.I):
                header_done = True
            continue
        if s.startswith("#"):
            continue
        codes.add(re.split(r"[,;\t|]", s)[0].strip())
    return len(codes)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, help="profile CSV to embed")
    ap.add_argument("--out", required=True, help="client HTML file to write")
    ap.add_argument("--template", default=os.path.join(HERE, "volume-profile.html"),
                    help="viewer template (default: volume-profile.html beside this script)")
    ap.add_argument("--select", default="",
                    help="instrument to open on load, e.g. RELIANCE.IN. "
                         "Omit to land on the picker with the data already loaded.")
    ap.add_argument("--only", default="",
                    help="comma-separated codes to keep; everything else is dropped")
    ap.add_argument("--title", default="", help="browser tab title override")
    args = ap.parse_args()

    if not os.path.isfile(args.csv):
        fail("no such CSV: %s" % args.csv)
    if not os.path.isfile(args.template):
        fail("no such template: %s" % args.template, 2)

    html = read_text(args.template)
    csv = read_text(args.csv)

    if not SLOT.search(html):
        fail("the template has no embeddedProfile slot; is it the right file?", 2)
    if not re.search(r"cumulated", csv, re.I):
        fail("%s has no CumulatedPercentage column" % args.csv)

    if args.only:
        csv, kept = filter_instruments(csv, args.only)
        total = kept
    else:
        total = count_instruments(csv)

    # A <script> element is raw text: entities are not decoded, so the CSV goes
    # in verbatim. The one sequence that would end the element early is "</script".
    if re.search(r"</script", csv, re.I):
        fail("the CSV contains the text '</script', which cannot be embedded")

    name = os.path.basename(args.csv)
    attrs = ' data-name="%s" data-select="%s"' % (
        name.replace('"', "&quot;"), args.select.replace('"', "&quot;"))
    built = SLOT.sub(
        lambda m: m.group(1) + attrs + ">\n" + csv.rstrip("\n") + "\n</script>",
        html, count=1)

    if args.title:
        built = re.sub(r"<title>.*?</title>",
                       "<title>%s</title>" % args.title.replace("<", ""),
                       built, count=1, flags=re.S)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(built)

    size = os.path.getsize(args.out)
    print("wrote %s" % args.out)
    print("  %d instrument%s, %.0f KB" % (total, "" if total == 1 else "s", size / 1024.0))
    if args.select:
        print("  opens on %s" % args.select)
    if size > 15 * 1024 * 1024:
        print("  note: over 15 MB, past most mail attachment limits. "
              "Use --only to ship fewer instruments.")
    print("  built %s" % dt.datetime.now().strftime("%Y-%m-%d %H:%M"))


if __name__ == "__main__":
    main()
