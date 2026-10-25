"""Publish a read-only snapshot of the warehouse for the dashboard.

    python -m pipeline.snapshot                 # full copy -> warehouse/snapshot.duckdb (after each agent run)
    python -m pipeline.snapshot --slim          # dashboard tables only -> dashboard_data/snapshot.duckdb
                                                # (the file committed for Streamlit Community Cloud)

DuckDB allows one writer, and the DAGs own it. The dashboard never opens the live file: after each agent
run this copies the warehouse to SNAPSHOT_PATH, stamps it with what it contains, and swaps it in with an
atomic rename, so a reader sees either the old snapshot or the new one, never a half-written file.
Everything on screen therefore comes from one consistent moment, shown in the dashboard header."""
import os
import shutil
from datetime import datetime, timezone

import sys

import duckdb

WAREHOUSE = os.environ.get("WAREHOUSE_PATH", "warehouse/warehouse.duckdb")
SNAPSHOT = os.environ.get("SNAPSHOT_PATH", os.path.join(os.path.dirname(WAREHOUSE), "snapshot.duckdb"))


def publish():
    con = duckdb.connect(WAREHOUSE)
    con.execute("CHECKPOINT")  # fold the write-ahead log into the file so the copy is complete
    con.close()
    tmp = SNAPSHOT + ".tmp"
    shutil.copyfile(WAREHOUSE, tmp)
    snap = duckdb.connect(tmp)
    snap.execute("create schema if not exists app")
    snap.execute("""create or replace table app.snapshot_info as select
        ?::timestamptz as published_at,
        (select max(as_of) from ml.risk_scores) as scores_as_of,
        (select max(data_as_of) from ml.risk_scores) as data_as_of,
        (select model_version from ml.model_registry where status = 'production' order by trained_at desc limit 1) as model_version,
        (select max(finished_at) from agent.runs) as agent_run_at""", [datetime.now(timezone.utc)])
    snap.execute("CHECKPOINT")
    snap.close()
    os.replace(tmp, SNAPSHOT)
    print(f"published {SNAPSHOT} ({os.path.getsize(SNAPSHOT) / 1e6:.0f} MB)")


# What the dashboard reads (app/data.py), and nothing else. Bronze keeps only the lineage columns the
# trace-back shows; gold keeps only today's scoring rows. The full dataset stays in lake/.
SLIM_TABLES = {
    "reference.tenants": "select * from reference.tenants",
    "silver.dim_user": "select * from silver.dim_user",
    "ml.risk_scores": "select * from ml.risk_scores",
    "ml.risk_reasons": "select * from ml.risk_reasons",
    "gold.account_features": "select * from gold.account_features where purpose = 'score' and as_of = data_as_of",
    # Only the logged scores and reasons agent evidence cites; the full log stays in the warehouse.
    "ml.score_log": "select * from w.ml.score_log where run_id in (select split_part(source_key, '/', 1) from w.agent.evidence where source_table = 'ml.score_log')",
    "ml.reason_log": "select * from w.ml.reason_log where run_id in (select split_part(source_key, '/', 1) from w.agent.evidence where source_table = 'ml.reason_log')",
    "agent.cases": "select * from agent.cases",
    "agent.evidence": "select * from agent.evidence",
    "agent.tool_calls": "select * from agent.tool_calls",
    "agent.failures": "select * from agent.failures",
    "ops.source_freshness": "select * from ops.source_freshness",
    "ops.quarantine_identity": "select * from ops.quarantine_identity",
    "silver.fct_ticket": "select * from silver.fct_ticket",
    "silver.fct_ticket_status_change": "select * from silver.fct_ticket_status_change",
    "silver.fct_ticket_comment": "select * from silver.fct_ticket_comment",
    "silver.fct_charge": "select * from silver.fct_charge",
    "silver.dim_subscription_history": "select * from silver.dim_subscription_history",
    "silver.dim_contact_history": "select * from silver.dim_contact_history",
    "silver.fct_email_message": "select * from silver.fct_email_message",
    "silver.fct_activity": "select * from silver.fct_activity",
    "silver.dim_opportunity_history": "select * from silver.dim_opportunity_history",
    "silver.fct_product_event": "select tenant_id, account_id, event_id, event_time, known_at, user_hash, event_name from silver.fct_product_event",
    "bronze.zendesk__ticket": "select _tenant_id, id, _source_file, _fivetran_synced, status, updated_at from bronze.zendesk__ticket",
    "bronze.stripe__charge": "select _tenant_id, id, _source_file, _fivetran_synced from bronze.stripe__charge",
    "bronze.stripe__subscription": "select _tenant_id, id, _source_file, _fivetran_synced, status, quantity from bronze.stripe__subscription",
}
SLIM = os.environ.get("SLIM_SNAPSHOT_PATH", "dashboard_data/snapshot.duckdb")


def publish_slim():
    os.makedirs(os.path.dirname(SLIM), exist_ok=True)
    tmp = SLIM + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = duckdb.connect(tmp)
    con.execute(f"attach '{WAREHOUSE}' as w (read_only)")
    for name, sql in SLIM_TABLES.items():
        schema, table = name.split(".")
        con.execute(f"create schema if not exists {schema}")
        if not con.execute("select count(*) from duckdb_tables() where database_name = 'w' and schema_name = ? and table_name = ?",
                           [schema, table]).fetchone()[0]:
            continue  # a table newer than this warehouse (agent.failures before the agent's first run since it was added)
        sql = sql if " w." in sql else sql.replace(" from ", " from w.", 1)  # entries with subqueries name w. themselves
        con.execute(f"create table {name} as {sql}")
    con.execute("create schema if not exists app")
    con.execute("""create table app.snapshot_info as select
        ?::timestamptz as published_at,
        (select max(as_of) from ml.risk_scores) as scores_as_of,
        (select max(data_as_of) from ml.risk_scores) as data_as_of,
        (select model_version from w.ml.model_registry where status = 'production' order by trained_at desc limit 1) as model_version,
        (select max(finished_at) from w.agent.runs) as agent_run_at""", [datetime.now(timezone.utc)])
    con.execute("detach w")
    con.execute("CHECKPOINT")
    con.close()
    os.replace(tmp, SLIM)
    print(f"published slim snapshot {SLIM} ({os.path.getsize(SLIM) / 1e6:.0f} MB, {len(SLIM_TABLES)} tables)")


if __name__ == "__main__":
    publish_slim() if "--slim" in sys.argv else publish()
