"""CSM dashboard: read-only, multi-tenant, with trace-back from every number to its source.

    streamlit run app/dashboard.py        (in docker compose: http://localhost:8501)

Pages: My accounts (the ranked book), Account detail (score, reasons, agent brief, evidence -> source rows
-> bronze files), Team overview (managers only). Sign-in is a demo user picker; every query is scoped by
the signed-in user's tenant in app/data.py. Nothing here writes anywhere."""
import hmac
import json
import os
import sys

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
import data as D  # noqa: E402

RED, YELLOW = 0.25, 0.10  # band entry lines, as in pipeline/risk_model.py BANDS
ROUTE_LABEL = {"csm_task": "CSM task", "billing_queue": "Billing", "suppress": "Already in hand",
               "data_quality": "Check data", "no_action": "No action"}

st.set_page_config(page_title="Account Risk", layout="wide")


@st.cache_resource(max_entries=1)
def _con(mtime: float):
    # One entry: when a new snapshot is published the old connection drops out of the cache, and DuckDB
    # closes it once no rerun still holds it, releasing the replaced file instead of keeping it open.
    return D.connect()


def con():
    """A read-only connection to the current snapshot; reopens when a new snapshot is published."""
    try:
        return _con(os.path.getmtime(D.SNAPSHOT))
    except FileNotFoundError:
        st.error("No snapshot yet. It's published after each agent run (pipeline/snapshot.py).")
        st.stop()


def viewer() -> D.Viewer:
    return st.session_state["viewer"]


def pct(x) -> str:
    """Risk as a CSM reads it: below half a percent the model can't tell 0.1% from 0.4%, so say "<1%"."""
    return "" if pd.isna(x) else "<1%" if x < 0.005 else f"{x:.0%}"


NO_DATA = "no data"


def shown_band(band: str, status: str) -> str:
    """Unknown must never look healthy: an account with too little recent data that the model would call
    green shows "no data". One it flags red or yellow keeps that band; going dark can be the risk itself."""
    return NO_DATA if status == "insufficient_data" and band == "green" else band


def money(x) -> str:
    return f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.1f}k" if x >= 1e3 else f"${x:,.0f}"


def change(x) -> str:
    return "" if pd.isna(x) else "0%" if abs(x) < 0.005 else f"{x:+.0%}"


# ------------------------------------------------------------------ access gate (hosted demo only)

def _shared_password():
    """Set dashboard_password in Streamlit secrets (never in the repo) to keep a hosted demo to invited people."""
    try:
        return st.secrets.get("dashboard_password")
    except Exception:  # no secrets file: running locally, no gate
        return None


def gate() -> bool:
    expected = _shared_password()
    if not expected or st.session_state.get("unlocked"):
        return True
    st.title("Account Risk")
    entered = st.text_input("Access code", type="password")
    if entered:
        if hmac.compare_digest(entered, str(expected)):
            st.session_state["unlocked"] = True
            st.rerun()
        st.error("That code isn't right.")
    return False


# ------------------------------------------------------------------ sign-in

def sign_in():
    st.title("Account Risk")
    st.caption("Demo sign-in: pick a person. Production would use SSO; only this screen would change.")
    users = D.demo_users(con())
    tenant = st.selectbox("Organisation", users.tenant_name.unique())
    people = users[users.tenant_name == tenant]
    label = lambda r: f"{r.user_name} ({'CS manager' if r.role == 'manager' else f'CSM, {r.accounts} accounts'})"
    pick = st.selectbox("Person", list(people.itertuples()), format_func=label)
    if st.button("Sign in", type="primary"):
        st.session_state["viewer"] = D.Viewer(pick.tenant_id, pick.user_id, pick.user_name, pick.role)
        # The browser may still be on another page's URL (signed out from an account page, or the
        # session dropped there); land on My accounts, not on whatever account that page defaults to.
        st.session_state["land_on_accounts"] = True
        st.rerun()


def header():
    v, info = viewer(), D.snapshot_info(con())
    with st.sidebar:
        st.markdown(f"**{v.name}**  \n{'CS manager' if v.is_manager else 'CSM'} · {v.tenant_id}")
        if st.button("Sign out"):
            st.session_state.clear()
            st.rerun()
        st.divider()
        when = lambda t: "not yet" if pd.isna(t) else f"{pd.Timestamp(t):%Y-%m-%d %H:%M} UTC"
        st.caption(f"Scores as of **{info['scores_as_of']:%Y-%m-%d}**  \nModel `{info['model_version']}`  \n"
                   f"Agent last ran {when(info['agent_run_at'])}  \nSnapshot {when(info['published_at'])}")
    stale = D.stale_feeds(con(), v)
    stale = stale[stale.freshness_status == "stale"]
    if not stale.empty:
        feeds = ", ".join(f"{r.source_table.replace('__', ' ')} ({r.hours_behind:.0f}h behind)" for r in stale.itertuples())
        st.warning(f"Some data hasn't arrived: {feeds}. Scores that depend on it may be out of date.")


# ------------------------------------------------------------------ page: my accounts

def page_accounts():
    v = viewer()
    st.header("My accounts" if not v.is_manager else "Accounts")
    owner = None
    if v.is_manager:
        opts = D.csm_options(con(), v)
        choice = st.selectbox("CSM", ["Everyone"] + opts.user_name.tolist())
        owner = None if choice == "Everyone" else opts.loc[opts.user_name == choice, "user_id"].iloc[0]
    book = D.worklist(con(), v, owner)
    book["band"] = [shown_band(b, s) for b, s in zip(book.band, book.status)]
    no_data = book.band == NO_DATA

    c = st.columns(6)
    c[0].metric("Accounts", len(book))
    c[1].metric("Red", int((book.band == "red").sum()))
    c[2].metric("Yellow", int((book.band == "yellow").sum()))
    c[3].metric("Customer notices", int((book.status == "customer_notice").sum()))
    c[4].metric("Too little data", int(no_data.sum()), help="Not enough recent usage, support or email data to judge. "
                "Not the same as healthy: check why the data is missing.")
    c[5].metric("Revenue at risk", money((book.risk_prob * book.arr_usd)[~no_data].sum()))

    f1, f2 = st.columns([2, 1])
    bands = f1.multiselect("Band", ["red", "yellow", NO_DATA, "green"], default=["red", "yellow"])
    reviewed = f2.toggle("Only accounts the agent reviewed", value=False)
    view = book[book.band.isin(bands)] if bands else book
    if reviewed:
        view = view[view.route.notna()]

    unknown = view.band == NO_DATA
    table = view.assign(
        risk=(view.risk_prob * 100).round().mask(unknown), change=view.change.map(change).mask(unknown, ""),
        agent=view.route.map(ROUTE_LABEL).fillna(""), status=view.status.str.replace("_", " "))
    st.caption("Select a row to open the account.")
    event = st.dataframe(
        table[["rank", "account_name", "band", "risk", "change", "arr_usd", "days_to_renewal", "status", "agent", "headline"]],
        hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        column_config={
            "rank": st.column_config.NumberColumn("#", width="small"),
            "account_name": "Account",
            "band": "Band",
            "risk": st.column_config.ProgressColumn("Risk (90 days)", min_value=0, max_value=100, format="%d%%"),
            "change": "vs last week",
            "arr_usd": st.column_config.NumberColumn("ARR", format="$%d"),
            "days_to_renewal": st.column_config.NumberColumn("Renews in (days)"),
            "status": "Status", "agent": "Agent route", "headline": st.column_config.TextColumn("Agent headline", width="large"),
        })
    if event.selection.rows:
        st.session_state["account_id"] = view.iloc[event.selection.rows[0]].account_id
        st.switch_page(PAGES["detail"])


# ------------------------------------------------------------------ page: account detail

def risk_chart(hist: pd.DataFrame):
    base = alt.Chart(hist).encode(x=alt.X("as_of:T", title=None))
    zones = pd.DataFrame({"y": [YELLOW, RED], "label": ["yellow line", "red line"]})
    rules = alt.Chart(zones).mark_rule(strokeDash=[4, 4], opacity=0.5).encode(y="y:Q", tooltip=["label"])
    line = base.mark_line(point=True).encode(
        y=alt.Y("risk_prob:Q", title="Risk", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, max(0.4, hist.risk_prob.max() * 1.1)])),
        tooltip=[alt.Tooltip("as_of:T"), alt.Tooltip("risk_prob:Q", format=".0%"), "band", "band_note"])
    return (rules + line).properties(height=220)


def page_detail():
    v = viewer()
    book = D.worklist(con(), v)
    if book.empty:
        st.info("No accounts in your book.")
        return
    ids = book.account_id.tolist()
    current = st.session_state.get("account_id", ids[0])
    account_id = st.selectbox("Account", ids, index=ids.index(current) if current in ids else 0,
                              format_func=lambda i: book.loc[book.account_id == i, "account_name"].iloc[0])
    st.session_state["account_id"] = account_id
    try:
        acc = D.account_header(con(), v, account_id)
    except D.NotVisible:
        st.error("This account isn't in your book.")
        return

    band = shown_band(acc["band"], acc["status"])
    st.header(acc["account_name"])
    st.caption(f"{'No data' if band == NO_DATA else band.capitalize() + ' band'} · #{int(acc['rank_in_book'])} in the book · "
               f"{acc['status'].replace('_', ' ')}" + (f" · {acc['band_note']}" if acc["band_note"] else ""))
    c = st.columns(3)
    if band == NO_DATA:
        c[0].metric("Risk, next 90 days", "—", help="Too little recent usage, support or email data to judge this "
                    "account. That is not the same as healthy.")
    else:
        c[0].metric("Risk, next 90 days", pct(acc["risk_prob"]))
    c[1].metric("ARR", money(acc["arr_usd"]))
    c[2].metric("Renews in", f"{acc['days_to_renewal']} days")
    if acc["notices"]:
        st.error(f"Customer notice: {acc['notices']}")

    case = D.agent_case(con(), v, account_id)
    t_why, t_agent, t_usage, t_inputs = st.tabs(["Why this score", "Agent review", "Usage", "Model inputs"])

    with t_why:
        left, right = st.columns([3, 2])
        left.subheader("Risk over the last 13 weeks")
        left.altair_chart(risk_chart(D.risk_history(con(), v, account_id)), width="stretch")
        right.subheader("What pushed it up")
        r = D.reasons(con(), v, account_id)
        if band == NO_DATA:
            right.write("Too little recent data to explain a score. Check why usage, support and email data are "
                        "missing for this account.")
        elif acc["risk_prob"] < 0.01:
            # Reasons are pushes above an average account, so a near-zero score still has some; showing them
            # under "what pushed it up" would contradict the number above.
            right.write("Risk is under 1%: nothing in this account's recent data points to churn or a downsell in "
                        "the next 90 days.")
        elif r.empty:
            right.write("No features pushed this score above the baseline.")
        else:
            right.altair_chart(alt.Chart(r).mark_bar().encode(
                x=alt.X("contribution:Q", title="Contribution to the score (log-odds)"),
                y=alt.Y("reason:N", sort="-x", title=None), tooltip=["feature", "feature_value", "contribution"]
            ).properties(height=40 + 40 * len(r)), width="stretch")
            right.caption("Exact per-prediction contributions from the model's trees (TreeSHAP).")

    with t_agent:
        if case is None:
            st.info("The agent hasn't reviewed this account for this score date. It reviews newly flagged accounts after "
                    "each scoring run, a few per CSM at a time.")
        else:
            st.subheader(case["headline"])
            st.caption(f"Route: **{ROUTE_LABEL.get(case['route'], case['route'])}** · priority {case['priority']} · "
                       f"trigger {case['trigger'].replace('_', ' ')} · decided by {case['decided_by'].replace('_', ' ')}"
                       f"{' (' + case['model'] + ')' if case['model'] else ''} · validation {case['validation_status']}")
            ev = D.evidence(con(), v, case["case_id"])
            facts = dict(zip(ev.evidence_id, ev.fact))
            brief = json.loads(case["brief"])
            for s in brief:
                st.markdown(f"- {s['text']} " + " ".join(f"`{e}`" for e in s["evidence"]))
            st.markdown(f"**Recommended action:** {case['recommended_action']}")

            st.divider()
            st.subheader("Trace a fact")
            cited = sorted({e for s in brief for e in s["evidence"] if e in facts}, key=lambda e: int(e[1:]))
            if not cited:
                st.info("This brief cites no evidence recorded for the case, so there is nothing to trace.")
            else:
                pick = st.selectbox("Evidence", cited, format_func=lambda e: f"{e}: {facts.get(e, '?')}")
                row = ev[ev.evidence_id == pick].iloc[0]
                st.caption(f"Source `{row.source_table}` · key `{row.source_key}`")
                title, rows, files = D.source_rows(con(), v, account_id, row.source_table, row.source_key)
                st.markdown(f"**{title}**")
                st.dataframe(rows, hide_index=True, width="stretch")
                if not files.empty:
                    st.markdown("**Loaded from these landed files (bronze)**")
                    st.dataframe(files, hide_index=True, width="stretch")

            if case["outreach_body"]:
                st.divider()
                st.subheader("Outreach draft")
                st.caption("Drafted for you to review, edit and send from your own mailbox. Nothing has been sent.")
                st.markdown(f"**Subject:** {case['outreach_subject']}")
                st.code(case["outreach_body"], language=None, wrap_lines=True)

            with st.expander("How the agent investigated"):
                st.dataframe(D.tool_calls(con(), v, case["case_id"]), hide_index=True, width="stretch")
                st.dataframe(ev, hide_index=True, width="stretch")

    with t_usage:
        u = D.usage_weekly(con(), v, account_id)
        if u.empty:
            st.info("No product activity in the last 26 weeks.")
        else:
            st.altair_chart(alt.Chart(u).mark_bar().encode(x=alt.X("week:T", title=None), y=alt.Y("events:Q", title="Events"),
                                                           tooltip=["week:T", "events", "users"]).properties(height=240),
                            width="stretch")
    with t_inputs:
        st.caption(f"The exact row the model scored. Built from data received by {acc['feature_cutoff']:%Y-%m-%d %H:%M} UTC; "
                   f"model `{acc['model_version']}`.")
        st.dataframe(D.features(con(), v, account_id), hide_index=True, width="stretch", height=520)


# ------------------------------------------------------------------ page: team overview

def page_team():
    v = viewer()
    st.header("Team overview")
    team = D.team_overview(con(), v)
    c = st.columns(4)
    c[0].metric("Accounts", int(team.accounts.sum()))
    c[1].metric("Red", int(team.red.sum()))
    c[2].metric("Red, not yet reviewed by the agent", int(team.red_not_reviewed.sum()))
    c[3].metric("Revenue at risk", money(team.revenue_at_risk_usd.sum()))
    st.subheader("By CSM")
    st.dataframe(team, hide_index=True, width="stretch", column_config={
        "csm": "CSM", "accounts": "Accounts", "red": "Red", "yellow": "Yellow", "notices": "Customer notices",
        "no_data": "Too little data", "red_not_reviewed": "Red, not reviewed",
        "revenue_at_risk_usd": st.column_config.NumberColumn("Revenue at risk", format="$%d")})
    st.subheader("Agent reviews")
    st.dataframe(D.agent_activity(con(), v), hide_index=True, width="stretch")
    failed = D.agent_failures(con(), v)
    if not failed.empty:
        st.subheader("Reviews that failed")
        st.caption("The agent couldn't review these accounts. Each is retried on the next run, up to 3 times per score date.")
        st.dataframe(failed, hide_index=True, width="stretch")
    left, right = st.columns(2)
    left.subheader("Data freshness")
    left.dataframe(D.data_health(con(), v), hide_index=True, width="stretch")
    right.subheader("Records not matched to an account")
    right.dataframe(D.quarantine_counts(con(), v), hide_index=True, width="stretch")


# ------------------------------------------------------------------ navigation

PAGES = {
    "accounts": st.Page(page_accounts, title="My accounts", url_path="accounts", default=True),
    "detail": st.Page(page_detail, title="Account detail", url_path="account"),
    "team": st.Page(page_team, title="Team overview", url_path="team"),
}

if not gate():
    st.stop()
elif "viewer" not in st.session_state:
    sign_in()
else:
    header()
    pages = [PAGES["accounts"], PAGES["detail"]] + ([PAGES["team"]] if viewer().is_manager else [])
    page = st.navigation(pages)
    if st.session_state.pop("land_on_accounts", False) and page.title != PAGES["accounts"].title:
        st.switch_page(PAGES["accounts"])
    page.run()
