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
ORDER_TABLES = ("target", "target_state", "execution")
MARKET_TABLES = ("qatt",)


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


class KdbClient:
    """A pykx handle, opened on demand and reused. pykx is imported lazily."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = int(port or 0)
        self._q = None

    def _handle(self):
        if self._q is None:
            import pykx as kx
            self._q = kx.QConnection(host=self.host, port=self.port)
        return self._q

    def query(self, expr: str):
        result = self._handle()(expr)
        try:
            return result.pd()
        except Exception:
            return result

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
    """The gateway call. `profile` is a dataset alias, not an HDB table."""
    day = f"{date:%Y.%m.%d}"
    columns = "`date`sym`vmed`time`cc0" if with_cc0 else "`date`sym`vmed`time"
    return (f"{conn.profile_fn}[`{conn.profile_table};{columns};"
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
