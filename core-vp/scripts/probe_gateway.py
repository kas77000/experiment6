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


def show_pykx_internals(kx) -> None:
    """The lines that raise, straight out of the installed pykx.

    The failure is in pykx's constructor, so what it does there is the whole
    question - and it cannot be read anywhere but on the machine that has it.
    """
    import inspect
    import pathlib

    print(DIVIDER)
    print("# pykx internals: what runs while a connection is constructed")

    root = pathlib.Path(inspect.getfile(kx)).parent
    for relative, around in (("__init__.py", 129), ("ipc.py", 654)):
        path = root / relative
        print(f"\n--- {path}  around line {around} ---")
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            print(f"  could not read: {exc}")
            continue
        lo = max(0, around - 16)
        hi = min(len(lines), around + 8)
        for n in range(lo, hi):
            marker = ">>" if n + 1 == around else "  "
            print(f"{marker} {n + 1:5d}  {lines[n]}")

    print("\n--- connection classes and their arguments ---")
    for name in ("QConnection", "SyncQConnection", "AsyncQConnection",
                 "RawQConnection", "SecureQConnection"):
        cls = getattr(kx, name, None)
        if cls is None:
            print(f"  {name:20s} absent")
            continue
        try:
            print(f"  {name:20s} {inspect.signature(cls.__init__)}")
        except (TypeError, ValueError) as exc:
            print(f"  {name:20s} signature unavailable: {exc}")


def attempt_connections(kx, host: str, port: int) -> None:
    """Which construction survives this server. The app does the same."""
    print(DIVIDER)
    print("# opening a connection")

    def sync_no_ctx():
        return kx.SyncQConnection(host=host, port=port, no_ctx=True)

    def sync_plain():
        return kx.SyncQConnection(host=host, port=port)

    candidates = [("SyncQConnection(no_ctx=True)", sync_no_ctx),
                  ("SyncQConnection()", sync_plain)]
    if hasattr(kx, "RawQConnection"):
        candidates[1:1] = [
            ("RawQConnection(no_ctx=True)",
             lambda: kx.RawQConnection(host=host, port=port, no_ctx=True)),
            ("RawQConnection()",
             lambda: kx.RawQConnection(host=host, port=port))]

    for name, build in candidates:
        attempt(name, build)


REFUSAL = b"Not a valid command"

# The gateway's own refusal says: "You can view the allowed commands/examples
# by looking at the debug table." It does not say what that table is called, so
# these are the plausible names. A wrong guess costs nothing - the gateway
# answers with the same refusal string.
DEBUG_TABLE_NAMES = ("debug", "debug_table", "debugtable", ".debug",
                     "help", "commands", "allowed", "examples", "usage",
                     "get_debug", "debug[]", "help[]", "tables[]")


def find_debug_table(conn) -> None:
    """Ask the gateway what it actually allows.

    Read only, and the gateway invites exactly this.
    """
    print(DIVIDER)
    print("# the gateway's debug table: what it says it allows")

    for name in DEBUG_TABLE_NAMES:
        try:
            value = conn(name)
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:16s} {type(exc).__name__}: {exc}")
            continue

        raw = None
        try:
            raw = value.py()
        except Exception:  # noqa: BLE001
            pass

        if isinstance(raw, (bytes, bytearray)) and REFUSAL in bytes(raw):
            print(f"  {name:16s} refused")
            continue

        print(f"  {name:16s} ANSWERED -> {describe(value)}")
        try:
            print("    .pd() ->")
            print(value.pd().to_string()[:4000])
        except Exception as exc:  # noqa: BLE001
            print(f"    .pd() failed: {type(exc).__name__}: {exc}")
            if raw is not None:
                print(f"    .py() -> {str(raw)[:2000]}")


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

    show_pykx_internals(kx)
    attempt_connections(kx, host, port)

    cols_bytes = [b"date", b"sym", b"vmed", b"time"]
    cols_str = ["date", "sym", "vmed", "time"]
    qday = f"{day:%Y.%m.%d}"
    expr = (f"get_data_by_date[`profile;`date`sym`vmed`time;"
            f"{qday};{qday};`{sym}]")

    # 1. Does the handle work at all, and does the gateway accept an
    #    expression? If even "1+1" fails, nothing below means anything.
    # no_ctx=True: pykx otherwise builds its context interface by evaluating
    # `q` on the REMOTE, and this gateway uses that name for a char vector of
    # its own, so the CONSTRUCTOR dies before any query is sent.
    try:
        conn = kx.SyncQConnection(host=host, port=port, no_ctx=True)
    except Exception:  # noqa: BLE001
        print(DIVIDER)
        print("Could not open a handle for the query tests; the connection "
              "section above is the part that matters.")
        print(traceback.format_exc())
        return 0
    find_debug_table(conn)

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
