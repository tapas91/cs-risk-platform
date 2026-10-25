"""risk_training: retrain the risk model once a month and promote it only if it wins.

    gold features (dbt) -> train + promotion gate

Monthly, not on every data change: a label needs 90 days to mature, so a week of new data adds
almost nothing to train on, and retraining on every sync would change the production model (and
every score) for no gain. Trigger it by hand after a backfill or when a drift check says so.

A new model replaces production only if it beats the hand-written rules baseline and doesn't lose to
production on the same test window; the decision is written to ml.model_registry either way. This
DAG never scores: risk_scoring picks up the new production model on its next run."""
import os
from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.bash import BashOperator

DBT = f'{os.environ.get("DBT_BIN", "dbt")} --no-use-colors'
PROJECT = os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt")
DBT_ARGS = f"--project-dir {PROJECT} --profiles-dir {PROJECT} --target-path /tmp/dbt-target-gold --log-path /tmp/dbt-logs"
ML = f'cd /opt/airflow && {os.environ.get("ML_PYTHON", "python")} -m pipeline.risk_model'


@dag(
    dag_id="risk_training",
    schedule="@monthly",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    default_args=dict(owner="data-platform", retries=1, retry_delay=timedelta(minutes=1), pool="duckdb"),
    tags=["gold", "ml"],
    doc_md=__doc__,
)
def risk_training():
    features = BashOperator(task_id="build_features", bash_command=f"{DBT} build --select path:models/gold {DBT_ARGS}")
    train = BashOperator(task_id="train_and_gate", bash_command=f"{ML} train")
    features >> train


risk_training()
