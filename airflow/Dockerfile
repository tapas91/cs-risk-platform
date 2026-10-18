# Airflow with DuckDB for bronze loads, plus two isolated virtualenvs so their dependencies never
# fight Airflow's pinned constraints: dbt for silver/gold, and an ML env for the risk model.
FROM apache/airflow:2.11.0-python3.11

USER root
# LightGBM needs the OpenMP runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
USER airflow

RUN pip install --no-cache-dir "apache-airflow==2.11.0" "duckdb==1.4.5"

RUN python -m venv /home/airflow/dbt-venv \
 && /home/airflow/dbt-venv/bin/pip install --no-cache-dir "dbt-core==1.11.16" "dbt-duckdb==1.11.0" "duckdb==1.4.5"

RUN python -m venv /home/airflow/ml-venv \
 && /home/airflow/ml-venv/bin/pip install --no-cache-dir "lightgbm==4.6.0" "scikit-learn==1.7.2" \
      "pandas==2.3.3" "pyarrow==21.0.0" "duckdb==1.4.5" "anthropic==1.15.0"

# Bake the DuckDB extensions into the image so runs never download at start-up.
RUN python -c "import duckdb; c = duckdb.connect(); c.execute('INSTALL httpfs'); c.execute('INSTALL json')"

ENV DBT_BIN=/home/airflow/dbt-venv/bin/dbt
ENV ML_PYTHON=/home/airflow/ml-venv/bin/python
