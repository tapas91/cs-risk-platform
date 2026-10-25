"""Tenant-scoped, read-only data access for the dashboard. The only module that queries the snapshot.

Every function takes a Viewer, built from the signed-in user, and puts the viewer's tenant_id into every
WHERE clause. The tenant never comes from a widget, a URL or another function's argument. CSMs see their
own book; managers see their whole tenant; nobody sees another tenant. tests/test_tenant_isolation.py
calls each function across tenants and expects nothing back.

The snapshot is opened read-only (it's a copy published after each agent run; see pipeline/snapshot.py)."""
import os
from dataclasses import dataclass
from typing import Optional

import duckdb
import pandas as pd

# SNAPSHOT_PATH is set in docker compose (the full snapshot the pipeline publishes). Without it - e.g. on
# Streamlit Community Cloud - the app reads the slim snapshot committed in dashboard_data/.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = os.environ.get("SNAPSHOT_PATH") or os.path.join(_REPO, "dashboard_data", "snapshot.duckdb")


@dataclass(frozen=True)
class Viewer:
    tenant_id: str
    user_id: str
    name: str
    role: str  # "csm" | "manager"

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"


class NotVisible(Exception):
    """The record exists but not for this viewer (another tenant, or another CSM's book)."""


def connect(path: str = SNAPSHOT) -> duckdb.DuckDBPyConnection:
    """A read-only view of one published snapshot. duckdb.connect(path) would reuse the process's existing
    database instance for that path, and the pipeline replaces the snapshot by renaming a new file over it,
    so a long-running dashboard would keep reading the replaced file. Attaching it to a fresh in-memory
    database opens whatever file is at the path now."""
    con = duckdb.connect(config={"TimeZone": "UTC"})
    con.execute(f"attach '{path.replace(chr(39), chr(39) * 2)}' as snapshot (read_only)")
    con.execute("use snapshot")
    return con


def _df(con, sql: str, params: list) -> pd.DataFrame:
    return con.execute(sql, params).df()


# ------------------------------------------------------------------ sign-in (demo)

def demo_users(con) -> pd.DataFrame:
    """Every active CSM and CS manager, across tenants, for the demo sign-in picker. Names and roles only."""
    return _df(con, """
        select u.tenant_id, t.tenant_name, u.user_id, u.user_name,
               case when u.user_role = 'CS Manager' then 'manager' else 'csm' end as role,
               (select count(*) from ml.risk_scores s where s.tenant_id = u.tenant_id and s.owner_id = u.user_id
                  and s.as_of = (select max(as_of) from ml.risk_scores)) as accounts
        from silver.dim_user u join reference.tenants t using (tenant_id)
        where u.is_active and u.user_role in ('CSM', 'CS Manager')
        order by t.tenant_name, role desc, u.user_name""", [])


def snapshot_info(con) -> dict:
    return con.execute("select * from app.snapshot_info").df().iloc[0].to_dict()


# ------------------------------------------------------------------ worklist

def csm_options(con, v: Viewer) -> pd.DataFrame:
    """CSMs a manager can switch between (just the viewer for a CSM)."""
    if not v.is_manager:
        return pd.DataFrame([{"user_id": v.user_id, "user_name": v.name}])
    return _df(con, """select user_id, user_name from silver.dim_user
                       where tenant_id = ? and user_role = 'CSM' and is_active order by user_name""", [v.tenant_id])


def worklist(con, v: Viewer, owner_id: Optional[str] = None) -> pd.DataFrame:
    """The ranked book on the latest score date, with last week's risk and the agent's case if any."""
    owner = v.user_id if not v.is_manager else owner_id
    return _df(con, """
        with cur as (select * from ml.risk_scores where tenant_id = ? and as_of = (select max(as_of) from ml.risk_scores)),
        prev as (select account_id, risk_prob from ml.risk_scores where tenant_id = ?
                 and as_of = (select max(as_of) from ml.risk_scores where as_of < (select max(as_of) from ml.risk_scores)))
        select c.rank_in_book as rank, c.account_id, c.account_name, c.band, c.risk_prob,
               c.risk_prob - p.risk_prob as change, c.arr_usd, c.days_to_renewal, c.status, c.notices, c.owner_id,
               a.route, a.headline, a.priority as agent_priority
        from cur c
        left join prev p using (account_id)
        left join agent.cases a on a.tenant_id = c.tenant_id and a.account_id = c.account_id and a.as_of = c.as_of
        where (? is null or c.owner_id = ?)
        order by c.rank_in_book""", [v.tenant_id, v.tenant_id, owner, owner])


# ------------------------------------------------------------------ account detail

def _visible_account(con, v: Viewer, account_id: str) -> dict:
    row = con.execute("""select * from ml.risk_scores where tenant_id = ? and account_id = ?
                         and as_of = (select max(as_of) from ml.risk_scores)""", [v.tenant_id, account_id]).df()
    if row.empty:
        raise NotVisible(account_id)
    row = row.iloc[0].to_dict()
    if not v.is_manager and row["owner_id"] != v.user_id:
        raise NotVisible(account_id)
    return row


def account_header(con, v: Viewer, account_id: str) -> dict:
    return _visible_account(con, v, account_id)


def risk_history(con, v: Viewer, account_id: str) -> pd.DataFrame:
    _visible_account(con, v, account_id)
    return _df(con, """select as_of, risk_prob, band, band_note from ml.risk_scores
                       where tenant_id = ? and account_id = ? order by as_of""", [v.tenant_id, account_id])


def reasons(con, v: Viewer, account_id: str) -> pd.DataFrame:
    acc = _visible_account(con, v, account_id)
    return _df(con, """select reason_rank, reason, feature, feature_value, contribution from ml.risk_reasons
                       where tenant_id = ? and account_id = ? and as_of = ? order by reason_rank""",
               [v.tenant_id, account_id, acc["as_of"]])


def features(con, v: Viewer, account_id: str) -> pd.DataFrame:
    """The exact model input row behind today's score, as feature / value pairs."""
    acc = _visible_account(con, v, account_id)
    row = _df(con, """select * exclude (purpose, tenant_id, account_id, account_name, owner_id, currency)
                      from gold.account_features where tenant_id = ? and account_id = ? and as_of = ? and purpose = 'score'""",
              [v.tenant_id, account_id, acc["as_of"]])
    if row.empty:
        return row
    return row.T.reset_index().set_axis(["feature", "value"], axis=1).astype({"value": str})


def agent_case(con, v: Viewer, account_id: str) -> Optional[dict]:
    acc = _visible_account(con, v, account_id)
    df = _df(con, """select * from agent.cases where tenant_id = ? and account_id = ? and as_of = ?""",
             [v.tenant_id, account_id, acc["as_of"]])
    return None if df.empty else df.iloc[0].to_dict()


def evidence(con, v: Viewer, case_id: str) -> pd.DataFrame:
    tenant, account_id, _ = case_id.split("|")
    if tenant != v.tenant_id:
        raise NotVisible(case_id)
    _visible_account(con, v, account_id)
    return _df(con, """select e.evidence_id, e.fact, e.value, e.source_table, e.source_key
                       from agent.evidence e join agent.cases c using (case_id)
                       where c.tenant_id = ? and e.case_id = ? order by cast(substr(e.evidence_id, 2) as integer)""",
               [v.tenant_id, case_id])


def tool_calls(con, v: Viewer, case_id: str) -> pd.DataFrame:
    tenant, account_id, _ = case_id.split("|")
    if tenant != v.tenant_id:
        raise NotVisible(case_id)
    _visible_account(con, v, account_id)  # a CSM sees only cases on their own accounts, as with evidence()
    return _df(con, """select t.seq, t.tool, t.input, t.result_chars, t.ms from agent.tool_calls t join agent.cases c using (case_id)
                       where c.tenant_id = ? and t.case_id = ? order by t.seq""", [v.tenant_id, case_id])


# ------------------------------------------------------------------ trace-back: evidence -> source rows

def source_rows(con, v: Viewer, account_id: str, source_table: str, source_key: str) -> tuple:
    """The rows behind one piece of evidence, plus the bronze files they were loaded from.
    Returns (title, rows, bronze_files). Scoped to the viewer's tenant and the case's account."""
    acc = _visible_account(con, v, account_id)
    t, a, cut = v.tenant_id, account_id, acc["feature_cutoff"]
    tail = source_key.split("/", 1)[1] if "/" in source_key else source_key
    if source_table == "silver.fct_ticket" and tail != a:
        # one timeline: the ticket itself, each status change, then the conversation
        rows = _df(con, """
            select created_at as happened_at, 'ticket opened' as event,
                   subject || ' (' || priority || ', ' || topic_tag || coalesce(', CSAT ' || satisfaction_rating, '') || ')' as detail
            from silver.fct_ticket where tenant_id = ? and account_id = ? and ticket_id = ?
            union all
            select changed_at, 'status: ' || coalesce(previous_status || ' -> ', '') || status, null
            from silver.fct_ticket_status_change where tenant_id = ? and ticket_id = ? and known_at <= ?
            union all
            select created_at, author_role || ' wrote', body from silver.fct_ticket_comment
            where tenant_id = ? and ticket_id = ? and known_at <= ?
            order by happened_at""", [t, a, tail, t, tail, cut, t, tail, cut])
        files = _df(con, """select distinct _source_file, _fivetran_synced, status, updated_at from bronze.zendesk__ticket
                            where _tenant_id = ? and cast(id as varchar) = ? order by _fivetran_synced""", [t, tail])
        return f"Ticket {tail}", rows, files
    if source_table == "silver.fct_ticket":
        rows = _df(con, """select ticket_id, subject, priority, created_at from silver.fct_ticket where tenant_id = ? and account_id = ?
                           and created_at <= ? and created_at > ?::timestamptz - interval 120 day order by created_at desc""", [t, a, cut, cut])
        return "Tickets, last 120 days", rows, pd.DataFrame()
    if source_table == "silver.fct_charge":
        rows = _df(con, """select charge_id, invoice_id, status, failure_code, amount_usd, created_at from silver.fct_charge
                           where tenant_id = ? and account_id = ? and created_at <= ? and created_at > ?::timestamptz - interval 90 day
                           order by created_at desc""", [t, a, cut, cut])
        files = _df(con, """select distinct b._source_file, b._fivetran_synced from bronze.stripe__charge b
                            join silver.fct_charge c on c.tenant_id = b._tenant_id and c.charge_id = b.id
                            where c.tenant_id = ? and c.account_id = ? and c.created_at > ?::timestamptz - interval 90 day""", [t, a, cut])
        return "Card payments, last 90 days", rows, files
    if source_table == "silver.dim_subscription_history":
        rows = _df(con, """select subscription_id, status, seats, cancel_at, valid_from, valid_to, known_at
                           from silver.dim_subscription_history where tenant_id = ? and account_id = ? and subscription_id = ?
                           order by valid_from""", [t, a, tail])
        files = _df(con, """select distinct _source_file, _fivetran_synced, status, quantity from bronze.stripe__subscription
                            where _tenant_id = ? and id = ? order by _fivetran_synced""", [t, tail])
        return f"Subscription {tail}, every version", rows, files
    if source_table == "silver.dim_contact_history":
        rows = _df(con, """select first_name, last_name, title, is_champion, email_bounced, inactive_date, valid_from, known_at
                           from silver.dim_contact_history where tenant_id = ? and account_id = ? and valid_from <= ?
                           qualify row_number() over (partition by contact_id order by valid_from desc) = 1""", [t, a, cut])
        return "Contacts as of the score date", rows, pd.DataFrame()
    if source_table == "silver.fct_email_message":
        rows = _df(con, """select sent_at, direction, mailbox, subject, has_reply, is_bounce from silver.fct_email_message
                           where tenant_id = ? and account_id = ? and sent_at <= ? and sent_at > ?::timestamptz - interval 90 day
                           order by sent_at desc""", [t, a, cut, cut])
        return "Emails, last 90 days", rows, pd.DataFrame()
    if source_table == "silver.fct_activity":
        rows = _df(con, """select activity_date, task_type, subject, owner_id, is_save_play from silver.fct_activity
                           where tenant_id = ? and account_id = ? and activity_date <= ? order by activity_date desc limit 20""",
                   [t, a, acc["as_of"]])
        return "CSM activity", rows, pd.DataFrame()
    if source_table == "silver.dim_opportunity_history":
        rows = _df(con, """select opportunity_type, stage_name, amount, close_date, valid_from, known_at
                           from silver.dim_opportunity_history where tenant_id = ? and account_id = ? and valid_from <= ?
                           order by valid_from desc limit 30""", [t, a, cut])
        return "Opportunity history", rows, pd.DataFrame()
    if source_table in ("ml.score_log", "ml.reason_log"):
        # key: <run_id>/<account>@<as_of>[#feature]. The logged row is the score as the CSM saw it then,
        # whatever later runs or models have done to the current table.
        run_id, as_of = source_key.split("/", 1)[0], source_key.split("@", 1)[1].split("#", 1)[0]
        if source_table == "ml.score_log":
            rows = _df(con, """select as_of, model_version, round(risk_prob, 4) as risk_prob, band, status, rank_in_book,
                                      arr_usd, days_to_renewal, scored_at from ml.score_log
                               where tenant_id = ? and account_id = ? and run_id = ?""", [t, a, run_id])
            return f"Score as shown on {as_of} (scoring run {run_id})", rows, pd.DataFrame()
        rows = _df(con, """select reason_rank, reason, feature, feature_value, round(contribution, 3) as contribution
                           from ml.reason_log where tenant_id = ? and account_id = ? and run_id = ? order by reason_rank""",
                   [t, a, run_id])
        return f"Reasons as shown on {as_of} (scoring run {run_id})", rows, pd.DataFrame()
    if source_table in ("gold.account_features", "ml.risk_scores", "ml.risk_reasons"):
        return "Model inputs behind today's score", features(con, v, account_id), pd.DataFrame()
    if source_table == "agent.cases":
        rows = _df(con, """select as_of, route, headline, decided_by from agent.cases where tenant_id = ? and account_id = ?
                           order by as_of desc""", [t, a])
        return "Earlier agent cases", rows, pd.DataFrame()
    return f"No viewer for {source_table}", pd.DataFrame(), pd.DataFrame()


def usage_weekly(con, v: Viewer, account_id: str) -> pd.DataFrame:
    acc = _visible_account(con, v, account_id)
    return _df(con, """select date_trunc('week', event_time)::date as week, count(*) as events, count(distinct user_hash) as users
                       from silver.fct_product_event where tenant_id = ? and account_id = ? and event_time <= ? and known_at <= ?
                         and event_time > ?::timestamptz - interval 182 day group by 1 order by 1""",
               [v.tenant_id, account_id, acc["feature_cutoff"], acc["feature_cutoff"], acc["feature_cutoff"]])


# ------------------------------------------------------------------ team overview (managers)

def team_overview(con, v: Viewer) -> pd.DataFrame:
    if not v.is_manager:
        raise NotVisible("team overview")
    return _df(con, """
        select coalesce(u.user_name, 'Unassigned') as csm, count(*) as accounts,
               count(*) filter (where s.band = 'red') as red, count(*) filter (where s.band = 'yellow') as yellow,
               count(*) filter (where s.status = 'customer_notice') as notices,
               count(*) filter (where s.status = 'insufficient_data') as no_data,
               count(*) filter (where s.band = 'red' and a.case_id is null) as red_not_reviewed,
               round(sum(s.risk_prob * s.arr_usd)) as revenue_at_risk_usd
        from ml.risk_scores s
        left join silver.dim_user u on u.tenant_id = s.tenant_id and u.user_id = s.owner_id
        left join agent.cases a on a.tenant_id = s.tenant_id and a.account_id = s.account_id and a.as_of = s.as_of
        where s.tenant_id = ? and s.as_of = (select max(as_of) from ml.risk_scores)
        group by 1 order by revenue_at_risk_usd desc""", [v.tenant_id])


def agent_activity(con, v: Viewer) -> pd.DataFrame:
    if not v.is_manager:
        raise NotVisible("agent activity")
    return _df(con, """select c.as_of, c.account_name, coalesce(u.user_name, 'Unassigned') as csm, c.trigger, c.route,
                              c.priority, c.headline, c.decided_by
                       from agent.cases c left join silver.dim_user u on u.tenant_id = c.tenant_id and u.user_id = c.owner_id
                       where c.tenant_id = ? order by c.created_at desc""", [v.tenant_id])


def data_health(con, v: Viewer) -> pd.DataFrame:
    return _df(con, """select source_table, freshness_status, hours_behind, last_synced_at, files, rows_landed
                       from ops.source_freshness where tenant_id = ? order by hours_behind desc""", [v.tenant_id])


def stale_feeds(con, v: Viewer) -> pd.DataFrame:
    return _df(con, """select source_table, hours_behind, freshness_status from ops.source_freshness
                       where tenant_id = ? and freshness_status in ('warn', 'stale') order by hours_behind desc""", [v.tenant_id])


def quarantine_counts(con, v: Viewer) -> pd.DataFrame:
    if not v.is_manager:
        raise NotVisible("quarantine")
    return _df(con, """select source_system, reason, count(*) as records from ops.quarantine_identity
                       where tenant_id = ? group by 1, 2 order by 3 desc""", [v.tenant_id])
