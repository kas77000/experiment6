#!/usr/bin/env python3
"""Find out what the VPROF gateway actually accepts.

Nothing in core-vp reproduces on a machine without pykx and without a route to
the gateway, so this asks the gateway directly. It sends the same call in
several forms and prints, for each, what came back or exactly where it failed.

Every query here is READ ONLY.

    python scripts/probe_gateway.py <host> <port> [symbol] [YYYY-MM-DD]

    python scripts/probe_gateway.py vprof-host 5100 000100.C2 2026-09-09

Run it and send the output. The form that returns a table is the one the app
should use; the traceback on the ones that fail names the pykx frame that
raises, which a one-line error message in the UI does not.
"""
from __future__ import annotations

import datetime as dt
import sys
import traceback

DIVIDER = "-" * 72


def describe(value) -> str:
    """What came back, in a line, without assuming it is any particular type."""
    kind = type(value).__name__
    try:
        text = repr(value)
    except Exception as exc:  # noqa: BLE001
        return f"{kind} (repr failed: {type(exc).__name__})"
    if len(text) > 300:
        text = text[:300] + " ..."
    extra = ""
    try:
        extra = f", {len(value)} items"
    except Exception:  # noqa: BLE001
        pass
    return f"{kind}{extra}: {text}"


def attempt(name: str, thunk) -> None:
    print(DIVIDER)
    print(f"# {name}")
    try:
        value = thunk()
    except Exception:  # noqa: BLE001
        print("FAILED")
        print(traceback.format_exc())
        return
    print("OK  ", describe(value))
    for conversion in ("pd", "py"):
        try:
            out = getattr(value, conversion)()
            print(f"  .{conversion}() ->", describe(out))
        except Exception as exc:  # noqa: BLE001
            print(f"  .{conversion}() failed: {type(exc).__name__}: {exc}")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    host = sys.argv[1]
    port = int(sys.argv[2])
    sym = sys.argv[3] if len(sys.argv) > 3 else "000100.C2"
    day = (dt.date.fromisoformat(sys.argv[4]) if len(sys.argv) > 4
           else dt.date.today())

    try:
        import pykx as kx
    except ImportError:
        print("pykx is not installed.  pip install pykx")
        return 2

    print(f"pykx {getattr(kx, '__version__', '?')}  "
          f"licensed={getattr(kx, 'licensed', '?')}")
    print(f"target {host}:{port}   sym={sym}   date={day}")

    cols_bytes = [b"date", b"sym", b"vmed", b"time"]
    cols_str = ["date", "sym", "vmed", "time"]
    qday = f"{day:%Y.%m.%d}"
    expr = (f"get_data_by_date[`profile;`date`sym`vmed`time;"
            f"{qday};{qday};`{sym}]")

    # 1. Does the handle work at all, and does the gateway accept an
    #    expression? If even "1+1" fails, nothing below means anything.
    conn = kx.SyncQConnection(host=host, port=port)
    attempt("h('1+1')                       plain expression",
            lambda: conn("1+1"))
    attempt("h('.z.D')                      server date",
            lambda: conn(".z.D"))

    # 2. The string form - what the app sent originally.
    attempt("h('get_data_by_date[...]')     one interpolated string",
            lambda: conn(expr))

    # 3. The call form, symbols as BYTES - what the app sends now, and what
    #    kdb-queries uses (liquidity_profile.py: hq('.lp.profile', sym.encode(), ...)).
    attempt("h('get_data_by_date', b'profile', [b'..'], d, d, b'sym')",
            lambda: conn("get_data_by_date", b"profile", cols_bytes,
                         day, day, sym.encode()))

    # 4. The call form with plain str, to see whether str-vs-bytes is what
    #    produces the CharVector.
    attempt("h('get_data_by_date', 'profile', ['..'], d, d, 'sym')  str args",
            lambda: conn("get_data_by_date", "profile", cols_str,
                         day, day, sym))

    # 5. Explicit pykx types, leaving no conversion to guesswork.
    def typed():
        return conn("get_data_by_date",
                    kx.SymbolAtom("profile"),
                    kx.SymbolVector(["date", "sym", "vmed", "time"]),
                    kx.DateAtom(day), kx.DateAtom(day),
                    kx.SymbolAtom(sym))
    attempt("h('get_data_by_date', kx.SymbolAtom(...), ...)  explicit types",
            typed)

    # 6. A Torq-style gateway answers with a DEFERRED response: the reply does
    #    not arrive on the synchronous round trip. QStudio's own error for this
    #    server suggested exactly that. wait=False sends without blocking for
    #    the sync reply.
    attempt("h(expr, wait=False)            deferred response",
            lambda: conn(expr, wait=False))

    # 7. With the context interface off. `_context_keys` belongs to that
    #    machinery, so if the gateway confuses it, this is the switch.
    def no_ctx():
        c = kx.SyncQConnection(host=host, port=port, no_ctx=True)
        try:
            return c(expr)
        finally:
            c.close()
    attempt("SyncQConnection(no_ctx=True)    context interface off", no_ctx)

    print(DIVIDER)
    print("Send this whole output back.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
