"""core-vp - volume profile vs execution.

Is this VWAP order tracking the volume profile, and is the day itself tracking
it? Three panels on one shared minutes-of-day axis answer that.

Runs on demo data with no kdb and no pykx. Point it at the real VPROF / OMS /
qatt servers on the Sources page.
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from core.connections import (DEFAULT_PROFILE_TABLE, Connection,
                              load_connections, pykx_available, probe,
                              save_connections, upsert_connection)
from core.provider import make_provider
from ui import panels

st.set_page_config(page_title="core-vp", page_icon="~", layout="wide")


def sidebar():
    st.sidebar.title("core-vp")

    conns = load_connections()
    names = ["demo data"] + [c.name for c in conns]
    chosen = st.sidebar.selectbox("Source", names, key="source")
    conn = next((c for c in conns if c.name == chosen), None)
    provider = make_provider(conn, force_demo=(conn is None))

    if conn is not None and not pykx_available():
        st.sidebar.warning("pykx is not installed - showing demo data.")

    dates = provider.available_dates()
    date = st.sidebar.selectbox("Date", dates, index=len(dates) - 1,
                                format_func=lambda d: d.isoformat())

    # The symbol comes from what is actually being worked, not typed blind.
    # All three panels then describe one symbol, which is what makes them
    # comparable on a shared axis.
    working, _ = panels.guarded("target", provider.list_vwap_symbols, date)
    options = list(working or []) + ["other..."]
    choice = st.sidebar.selectbox(
        "Symbol", options, key="symbol",
        help="Symbols with a VWAP order working on this date.")
    if choice == "other...":
        sym = st.sidebar.text_input("Symbol code", value="000001.C2")
    else:
        sym = choice
    if not working:
        st.sidebar.caption("No VWAP orders found for this date.")

    st.sidebar.divider()
    st.sidebar.caption("Order filters")
    filters = {
        "trader": st.sidebar.text_input("Trader", value="") or "All",
        "basket": st.sidebar.text_input("Basket", value="") or "All",
    }
    return provider, date, sym.strip(), filters


def sources_page():
    st.subheader("Sources")
    st.caption(
        "Three endpoints, because these are three different kdb+ processes. "
        "qatt sent to the order server returns nothing rather than raising, so "
        "Test checks each table against the endpoint that should serve it.")

    conns = load_connections()
    existing = {c.name: c for c in conns}
    name = st.text_input("Name", value=next(iter(existing), "ap"))
    current = existing.get(name, Connection(name=name))

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Volume profile (VPROF)**")
        p_host = st.text_input("Host", current.profile_host, key="p_host")
        p_port = st.number_input("Port", value=int(current.profile_port),
                                 step=1, key="p_port")
        table = st.text_input("Dataset", current.profile_table
                              or DEFAULT_PROFILE_TABLE)
        fn = st.text_input("Gateway function", current.profile_fn)
        st.caption("A gateway dataset alias - always `profile`. The vst / "
                   "vst05d / vst10d / vst20d tables are what the gateway maps "
                   "from, and are rejected if passed here.")
    with c2:
        st.markdown("**Orders (OMSR / OMSH)**")
        o_rt_h = st.text_input("Live host", current.oms_rt_host, key="o_rt_h")
        o_rt_p = st.number_input("Live port", value=int(current.oms_rt_port),
                                 step=1, key="o_rt_p")
        o_h_h = st.text_input("Historical host", current.oms_hist_host,
                              key="o_h_h")
        o_h_p = st.number_input("Historical port",
                                value=int(current.oms_hist_port), step=1,
                                key="o_h_p")
    with c3:
        st.markdown("**Market data (QATTR / QATTL)**")
        m_rt_h = st.text_input("Live host", current.md_rt_host, key="m_rt_h")
        m_rt_p = st.number_input("Live port", value=int(current.md_rt_port),
                                 step=1, key="m_rt_p")
        m_h_h = st.text_input("Historical host", current.md_hist_host,
                              key="m_h_h")
        m_h_p = st.number_input("Historical port",
                                value=int(current.md_hist_port), step=1,
                                key="m_h_p")
        st.caption("Leave blank to fall back to the order server.")

    updated = Connection(
        name=name, profile_host=p_host, profile_port=int(p_port),
        profile_table=table, profile_fn=fn,
        oms_rt_host=o_rt_h, oms_rt_port=int(o_rt_p),
        oms_hist_host=o_h_h, oms_hist_port=int(o_h_p),
        md_rt_host=m_rt_h, md_rt_port=int(m_rt_p),
        md_hist_host=m_h_h, md_hist_port=int(m_h_p))

    # The gateway accepts whitelisted call forms only, so the only meaningful
    # check is a real get_data_by_date call - which needs a date and a symbol.
    s1, s2 = st.columns(2)
    sample_sym = s1.text_input("Test symbol", value="000001.C2")
    sample_date = s2.date_input("Test date", value=dt.date.today())

    left, right = st.columns(2)
    if left.button("Save"):
        save_connections(upsert_connection(conns, updated))
        st.success(f"Saved {name}.")
    if right.button("Test", disabled=not pykx_available()):
        st.dataframe(probe(updated, sample_date=sample_date,
                           sample_sym=sample_sym.strip()),
                     use_container_width=True, hide_index=True)
    if not pykx_available():
        st.info("pykx is not installed here, so Test is unavailable and the "
                "app runs on demo data.")


def main():
    provider, date, sym, filters = sidebar()
    profile_tab, sources_tab = st.tabs(["Profile & execution", "Sources"])

    with profile_tab:
        profile, err = panels.load_profile(provider, date, sym)
        if err:
            st.caption(f"{sym} - {date.isoformat()} - {provider.label}")
            panels.show_error(err, "profile")
        else:
            st.caption(f"{sym} - {date.isoformat()} - {provider.label} - "
                       f"times shown in {profile.tz_label}")
            panels.profile_panel(profile)
            st.divider()
            panels.progression_panel(provider, profile, date, filters)
            st.divider()
            panels.realized_panel(provider, profile, date)

    with sources_tab:
        sources_page()


main()
