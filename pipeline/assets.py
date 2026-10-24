"""Airflow Datasets that chain the DAGs: bronze_ingest -> BRONZE -> silver_build -> SILVER -> risk_scoring -> RISK -> account_agent.
risk_training runs on its own monthly schedule and only changes which model risk_scoring uses."""
from airflow.datasets import Dataset

BRONZE = Dataset("duckdb://warehouse/bronze")
SILVER = Dataset("duckdb://warehouse/silver")
RISK = Dataset("duckdb://warehouse/ml/risk_scores")
