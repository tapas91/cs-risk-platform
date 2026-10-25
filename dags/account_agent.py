"""account_agent: review newly flagged accounts, route each one and write a cited brief.

Triggered by the RISK dataset, so it runs after every scoring run without anyone starting it. It reviews
at most AGENT_MAX_CASES accounts per run (a cost cap); accounts left over are picked up by the next run,
because an account is handled once per score date.

With ANTHROPIC_API_KEY set, Claude investigates each account through read-only tools and proposes a route
and brief, which code validates before anything is written. Without a key, or when the model's output
fails validation, the same routes come from rules. Results land in the `agent` schema; the agent never
changes a score and never contacts a customer. See pipeline/agent.py.

The last task publishes warehouse/snapshot.duckdb, the read-only copy the dashboard reads.

To review one account on demand, trigger this DAG with that account, so the run waits for the duckdb
pool instead of competing with the pipeline for the warehouse file:
    airflow dags trigger account_agent --conf '{"account": "northwind/001NW..."}'"""
import os
from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.bash import BashOperator

from pipeline.assets import RISK

AGENT = f'cd /opt/airflow && {os.environ.get("ML_PYTHON", "python")} -m pipeline.agent'


@dag(
    dag_id="account_agent",
    schedule=[RISK],
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=dict(owner="cs-platform", retries=1, retry_delay=timedelta(minutes=2), pool="duckdb",
                      execution_timeout=timedelta(minutes=30)),
    tags=["agent", "llm"],
    doc_md=__doc__,
)
def account_agent():
    # The account reaches the agent as an environment variable, never as shell text: no quoting or injection.
    review = BashOperator(task_id="review_accounts", bash_command=AGENT, append_env=True,
                          env={"AGENT_ACCOUNT": "{{ dag_run.conf.get('account', '') if dag_run.conf else '' }}"})
    # publish even if the review failed: the dashboard should still get the new scores
    publish = BashOperator(task_id="publish_snapshot", trigger_rule="all_done",
                           bash_command=f'cd /opt/airflow && {os.environ.get("ML_PYTHON", "python")} -m pipeline.snapshot')
    review >> publish


account_agent()
