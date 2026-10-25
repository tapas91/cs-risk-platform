"""risk_scoring: rebuild point-in-time features and score every live customer, whenever silver changes.

    gold features (dbt) -> score with the production model -> RISK

Triggered by the SILVER dataset, so nothing has to start it: new files land, bronze loads them,
silver rebuilds, and this DAG refreshes every account's score. It never trains: scoring always uses
whichever model is in production, so a failed or rejected retrain (risk_training) can't stop new
data being scored, and scores only change when the data does.

Before the first model is promoted there is nothing to score with: score_accounts exits 99, Airflow
marks it skipped, and RISK doesn't fire. The ML code runs in its own virtualenv (ML_PYTHON); every
step uses the duckdb pool."""
import os
from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.bash import BashOperator

from pipeline.assets import RISK, SILVER

DBT = f'{os.environ.get("DBT_BIN", "dbt")} --no-use-colors'
PROJECT = os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt")
DBT_ARGS = f"--project-dir {PROJECT} --profiles-dir {PROJECT} --target-path /tmp/dbt-target-gold --log-path /tmp/dbt-logs"
ML = f'cd /opt/airflow && {os.environ.get("ML_PYTHON", "python")} -m pipeline.risk_model'


@dag(
    dag_id="risk_scoring",
    schedule=[SILVER],
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    default_args=dict(owner="data-platform", retries=1, retry_delay=timedelta(minutes=1), pool="duckdb"),
    tags=["gold", "ml"],
    doc_md=__doc__,
)
def risk_scoring():
    features = BashOperator(task_id="build_features", bash_command=f"{DBT} build --select path:models/gold {DBT_ARGS}")
    score = BashOperator(task_id="score_accounts", bash_command=f"{ML} score", skip_on_exit_code=99, outlets=[RISK])
    features >> score


risk_scoring()
