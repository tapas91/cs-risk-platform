"""Airflow Datasets that chain the DAGs: bronze_ingest -> BRONZE -> silver_build -> SILVER -> risk_model -> RISK -> account_agent."""
from airflow.datasets import Dataset

BRONZE = Dataset("duckdb://warehouse/bronze")
SILVER = Dataset("duckdb://warehouse/silver")
RISK = Dataset("duckdb://warehouse/ml/risk_scores")
