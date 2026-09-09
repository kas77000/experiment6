"""Where the data lives, and how to reach it.

THREE endpoints, because these are three different kdb+ processes:

  profile   the VPROF gateway   get_data_by_date -> vst / vst05d / vst10d /
                                vst20d / latest_vst
  oms       OMSR live / OMSH    target, target_state, execution
  market    QATTR / QATTL       qatt

Sending qatt down the order-server handle returns nothing rather than raising,
so getting that wrong looks like missing market data rather than a
misconfiguration. `probe` therefore checks each table against the endpoint that
is supposed to serve it.

The first argument of get_data_by_date is a gateway DATASET ALIAS - always
`profile` - not an HDB table name. The vst / vst05d / vst10d / vst20d tables
load_vprof.q builds are what the gateway maps *from*; passing one of those names
is rejected. It stays configurable in case another dataset is exposed later, but
`profile` is the value.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "connections.json"

REGIONS = ("AP", "EU", "US")

# The gateway's dataset alias. Always `profile`.
DEFAULT_PROFILE_TABLE = "profile"

PROFILE_COLUMNS = ("date", "sym", "vmed", "time", "cc0")
PROFILE_COLUMNS_NO_CC0 = ("date", "sym", "vmed", "time")
ORDER_TABLES = ("target", "target_state", "execution")
MARKET_TABLES = ("qatt",)

# Which construction actually worked, per endpoint. Reported in the UI so a
# fallback is never silent.
LAST_STRATEGY: dict[tuple, str] = {}


@dataclass
class Connection:
    name: str
    region: str = "AP"

    profile_host: str = ""
    profile_port: int = 0
    profile_table: str = DEFAULT_PROFILE_TABLE
    profile_fn: str = "get_data_by_date"

    oms_rt_host: str = ""
    oms_rt_port: int = 0
    oms_hist_host: str = ""
    oms_hist_port: int = 0

    md_rt_host: str = ""
    md_rt_port: int = 0
    md_hist_host: str = ""
    md_hist_port: int = 0

    def key(self) -> str:
        return self.name.strip()

    def profile_endpoint(self) -> tuple[str, int]:
        return self.profile_host.strip(), int(self.profile_port or 0)

    def oms_endpoint(self, kind: str) -> tuple[str, int]:
        if kind == "rt":
            return self.oms_rt_host.strip(), int(self.oms_rt_port or 0)
        return self.oms_hist_host.strip(), int(self.oms_hist_port or 0)

    def market_endpoint(self, kind: str) -> tuple[str, int]:
        """qatt's endpoint, falling back to the order server when unset."""
        host, port = ((self.md_rt_host, self.md_rt_port) if kind == "rt"
                      else (self.md_hist_host, self.md_hist_port))
        if str(host).strip() and int(port or 0):
            return str(host).strip(), int(port)
        return self.oms_endpoint(kind)

    def has_separate_market_data(self, kind: str) -> bool:
        return self.market_endpoint(kind) != self.oms_endpoint(kind)


def resolve_kind(date: dt.date, today: dt.date | None = None) -> str:
    """'rt' for today, 'hist' for anything else.

    A future date is historical, so a clock skew cannot silently point the app
    at the live server.
    """
    today = today or dt.date.today()
    return "rt" if date == today else "hist"


# ------------------------------------------------------------- persistence
def load_connections() -> list[Connection]:
    if not CONFIG_PATH.exists():
        return []
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    fields = set(Connection.__dataclass_fields__)
    out = []
    for r in raw:
        try:
            out.append(Connection(**{k: v for k, v in r.items() if k in fields}))
        except (TypeError, ValueError):
            continue
    return out


def save_connections(conns: list[Connection]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps([asdict(c) for c in conns], indent=2),
                           encoding="utf-8")


def upsert_connection(conns: list[Connection], new: Connection) -> list[Connection]:
    return [c for c in conns if c.key() != new.key()] + [new]


def delete_connection(conns: list[Connection], name: str) -> list[Connection]:
    return [c for c in conns if c.key() != name.strip()]


# ---------------------------------------------------------------- transport
def pykx_available() -> bool:
    try:
        import pykx  # noqa: F401
        return True
    except Exception:
        return False


def open_connection(host: str, port: int):
    """A handle, opened by whichever construction this pykx and this server
    both tolerate.

    Building a connection, pykx sets up its context interface and evaluates
    `self.ctx.q` (pykx/__init__.py:129, reached from ipc.py `_init`). That
    resolves the name `q` in the REMOTE namespace. The VPROF gateway keeps a
    char vector under that name, so pykx gets a string where it expects its
    handle and dies IN THE CONSTRUCTOR, before any query is sent:

        pykx/__init__.py, line 129, in __init__
            *self.ctx.q._context_keys,
        AttributeError: 'CharVector' object has no attribute '_context_keys'

    The order and qatt servers define no global `q`, which is why only the
    gateway fails and why other pykx scripts on the same machine are fine.

    MEASURED against the gateway (scripts/probe_gateway.py, dc2nix2p424):

        SyncQConnection(no_ctx=True)   opens
        RawQConnection(...)            opens, but every call then fails with
                                       "Cannot load requested context object
                                       in unlicensed mode"
        SyncQConnection()              AttributeError, as above

    So no_ctx=True is the one to use, and it is first. The same call has also
    been seen to fail inside the running app while succeeding in a fresh
    process, which suggests pykx keeps some of this per-process rather than
    per-connection; the ordered list is therefore kept, and whichever
    construction won is recorded in LAST_STRATEGY so a fallback is never
    silent.

    SyncQConnection, matching every working script in kdb-queries: it needs no
    q licence and no QHOME, because evaluation happens on the server.
    """
    import pykx as kx

    attempts = []
    for name, build in _connection_strategies(kx):
        try:
            handle = build(host, int(port))
        except Exception as exc:  # noqa: BLE001
            if not (_is_context_failure(exc) or _is_unsupported_argument(exc)):
                raise          # a refused connection is the real answer
            attempts.append(f"{name} -> {type(exc).__name__}: {exc}")
            continue
        LAST_STRATEGY[(host, int(port))] = name
        return handle

    raise RuntimeError(
        "every way of opening a connection hit pykx's context interface, "
        "which this server breaks. Tried:\n  " + "\n  ".join(attempts))


def _connection_strategies(kx):
    """Ways to open a handle, least invasive first.

    pykx's API for skipping the context interface has moved between versions
    and `no_ctx=True` is accepted but not honoured on the one in use here, so
    the working path is found rather than assumed. Only a context failure or a
    rejected argument moves on to the next; anything else - a refused
    connection, a bad port - is raised immediately.
    """
    yield ("SyncQConnection(no_ctx=True)",
           lambda h, p: kx.SyncQConnection(host=h, port=p, no_ctx=True))
    yield ("SyncQConnection()",
           lambda h, p: kx.SyncQConnection(host=h, port=p))
    # RawQConnection is deliberately NOT here. Against the gateway it opens
    # and then fails every query with "Cannot load requested context object in
    # unlicensed mode", so accepting it would trade a clear connection error
    # for an obscure one on every read.


def _is_context_failure(exc: Exception) -> bool:
    """pykx building its context interface against a server that breaks it.

    On the VPROF gateway `self.ctx.q` resolves the name `q` in the REMOTE
    namespace, where the gateway keeps a char vector of its own, so pykx gets a
    string where it expects its handle:

        pykx/__init__.py, line 129, in __init__
            *self.ctx.q._context_keys,
        AttributeError: 'CharVector' object has no attribute '_context_keys'
    """
    return isinstance(exc, AttributeError) and "_context_keys" in str(exc)


def _is_unsupported_argument(exc: Exception) -> bool:
    return isinstance(exc, TypeError) and "unexpected keyword" in str(exc)


class KdbClient:
    """A pykx handle, opened on demand and reused. pykx is imported lazily."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = int(port or 0)
        self._q = None

    def _handle(self):
        if self._q is None:
            self._q = open_connection(self.host, self.port)
        return self._q

    def query(self, expr: str):
        """Send a q expression as TEXT.

        Not pykx's function-application form - `h(fn, arg1, arg2)` - which is
        what kdb-queries uses and what this code tried first. The VPROF gateway
        rejects it outright:

            h('get_data_by_date', b'profile', [...], d, d, b'000100.C2')
            -> b'Not a valid command.  Please note due to memory/resource
                 restrictions this port is for now only used for selecting
                 data. No logic and processing is allowed.'

        It pattern-matches the incoming text, so the call has to arrive as one
        string. The order and qatt servers take text too, so this is the single
        form for every endpoint.
        """
        return self._handle()(expr)

    def close(self) -> None:
        if self._q is not None:
            try:
                self._q.close()
            except Exception:
                pass
            self._q = None

    def __repr__(self) -> str:
        return f"{self.host}:{self.port}"


def profile_query(conn: Connection, date: dt.date, sym: str,
                  with_cc0: bool = True) -> str:
    """The gateway call, as the one string the gateway will accept.

    `profile` is a dataset alias, not an HDB table name.
    """
    cols = PROFILE_COLUMNS if with_cc0 else PROFILE_COLUMNS_NO_CC0
    joined = "".join("`" + c for c in cols)
    day = f"{date:%Y.%m.%d}"
    return (f"{conn.profile_fn}[`{conn.profile_table};{joined};"
            f"{day};{day};`{sym}]")


def probe(conn: Connection, kind: str = "hist", client_factory=KdbClient,
          sample_date: dt.date | None = None,
          sample_sym: str | None = None) -> list[dict]:
    """Check every table against the endpoint that should serve it.

    The profile endpoint is a restricted gateway: it accepts whitelisted call
    forms only, so `count <table>` is not a valid probe there and a bare
    identifier is answered with "not a valid command". The only meaningful
    check is a real get_data_by_date call, which needs a sample date and
    symbol. Without them that row reports "not checked" rather than a
    misleading pass or fail.
    """
    report = []

    endpoint = "%s:%d" % conn.profile_endpoint()
    if sample_date and sample_sym:
        try:
            client_factory(*conn.profile_endpoint()).query(
                profile_query(conn, sample_date, sample_sym))
            report.append(dict(table=conn.profile_table, role="profile",
                               endpoint=endpoint, ok=True, detail=""))
        except Exception as exc:  # noqa: BLE001
            report.append(dict(table=conn.profile_table, role="profile",
                               endpoint=endpoint, ok=False,
                               detail=f"{type(exc).__name__}: {exc}"))
    else:
        report.append(dict(table=conn.profile_table, role="profile",
                           endpoint=endpoint, ok=None,
                           detail="not checked - give a sample date and symbol"))

    oms_client = client_factory(*conn.oms_endpoint(kind))
    md_client = client_factory(*conn.market_endpoint(kind))
    plan = [(t, oms_client, "%s:%d" % conn.oms_endpoint(kind), "oms")
            for t in ORDER_TABLES]
    plan += [(t, md_client, "%s:%d" % conn.market_endpoint(kind), "market")
             for t in MARKET_TABLES]

    for table, client, where, role in plan:
        try:
            client.query(f"count {table}")
            report.append(dict(table=table, role=role, endpoint=where,
                               ok=True, detail=""))
        except Exception as exc:  # noqa: BLE001
            report.append(dict(table=table, role=role, endpoint=where,
                               ok=False, detail=f"{type(exc).__name__}: {exc}"))
    return report
