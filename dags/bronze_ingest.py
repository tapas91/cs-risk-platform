"""bronze_ingest: load newly landed Parquet files into DuckDB bronze tables.

Runs every 15 minutes. If nothing new has landed it stops after the check and the silver DAG is
not triggered. Each source loads in its own task; all of them share the single-slot `duckdb` pool
because DuckDB allows one writer at a time. Files are tracked in bronze._ingested_files, so a
retried or overlapping run never loads a file twice."""
from datetime import datetime, timedelta

from airflow.decorators import dag, task

from pipeline import bronze
from pipeline.assets import BRONZE

DEFAULTS = dict(owner="data-platform", retries=2, retry_delay=timedelta(minutes=1), pool="duckdb")


@dag(
    dag_id="bronze_ingest",
    schedule="*/15 * * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULTS,
    tags=["bronze", "ingest"],
    doc_md=__doc__,
)
def bronze_ingest():
    @task.short_circuit
    def new_files_landed() -> bool:
        n = bronze.pending_files()
        print(f"{n} new files waiting")
        return n > 0

    @task
    def load(source: str) -> dict:
        loaded = bronze.load_source(source)
        print(f"{source}: {loaded}")
        return loaded

    @task(outlets=[BRONZE])
    def publish(results: list) -> int:
        rows = sum(sum(r.values()) for r in results)
        print(f"bronze advanced by {rows} rows")
        return rows

    gate = new_files_landed()
    loads = []
    for source in bronze.SOURCES:
        t = load.override(task_id=f"load_{source}")(source)
        gate >> t
        loads.append(t)
    publish(loads)


bronze_ingest()
