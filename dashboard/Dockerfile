# The read-only CSM dashboard. Small image of its own: it never needs Airflow, dbt or the ML stack.
FROM python:3.11-slim
RUN pip install --no-cache-dir "streamlit==1.66.0" "altair==6.3.0" "duckdb==1.4.5" "pandas==2.3.3" "pytest==8.4.2"
WORKDIR /srv
ENV SNAPSHOT_PATH=/srv/warehouse/snapshot.duckdb PYTHONPATH=/srv/app
EXPOSE 8501
CMD ["streamlit", "run", "app/dashboard.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
