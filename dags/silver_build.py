"""silver_build: rebuild the silver and ops layers with dbt whenever bronze advances.

Triggered by the BRONZE dataset, not by a clock, so it runs exactly when there is new data.
`dbt build` runs models and tests in dependency order; a failing test fails the run, so bad data
never reaches silver silently. Silver tables are rebuilt in full: at this volume it takes seconds,
and it keeps late identity matches correct (a workspace linked today re-attributes its old events)."""
import os
from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.bash import BashOperator

from pipeline.assets import BRONZE, SILVER

DBT = f'{os.environ.get("DBT_BIN", "dbt")} --no-use-colors'
PROJECT = os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt")
ARGS = f"--project-dir {PROJECT} --profiles-dir {PROJECT} --target-path /tmp/dbt-target --log-path /tmp/dbt-logs"


@dag(
    dag_id="silver_build",
    schedule=[BRONZE],
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=dict(owner="data-platform", retries=1, retry_delay=timedelta(minutes=1), pool="duckdb"),
    tags=["silver", "dbt"],
    doc_md=__doc__,
)
def silver_build():
    seed = BashOperator(task_id="dbt_seed", bash_command=f"{DBT} seed {ARGS}")
    build = BashOperator(task_id="dbt_build", bash_command=f"{DBT} build --exclude resource_type:seed path:models/gold {ARGS}",
                         outlets=[SILVER])
    seed >> build


silver_build()
