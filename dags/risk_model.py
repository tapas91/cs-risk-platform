"""risk_model: rebuild point-in-time features, retrain, gate, and score, whenever silver changes.

    gold features (dbt) -> train + promotion gate -> score live customers

Triggered by the SILVER dataset, so nothing has to start it: new files land, bronze loads them,
silver rebuilds, and this DAG refreshes every account's score.

Training runs every time (seconds at this size). A new model only replaces the production model if it
beats the hand-written rules baseline and doesn't lose to production on the same test window; the
decision is written to ml.model_registry either way. Scoring always uses whichever model is in
production. The ML code runs in its own virtualenv (ML_PYTHON); every step uses the duckdb pool."""
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
    dag_id="risk_model",
    schedule=[SILVER],
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=dict(owner="data-platform", retries=1, retry_delay=timedelta(minutes=1), pool="duckdb"),
    tags=["gold", "ml"],
    doc_md=__doc__,
)
def risk_model():
    features = BashOperator(task_id="build_features", bash_command=f"{DBT} build --select path:models/gold {DBT_ARGS}")
    train = BashOperator(task_id="train_and_gate", bash_command=f"{ML} train")
    score = BashOperator(task_id="score_accounts", bash_command=f"{ML} score", outlets=[RISK])
    features >> train >> score


risk_model()
