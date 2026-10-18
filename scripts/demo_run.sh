#!/usr/bin/env bash
# Replay the whole history through the running stack, the way it would arrive in production:
# first files up to Dec 2024, then the first half of 2025 (a new Zendesk column appears), then the rest.
#   scripts/demo_run.sh            # assumes `docker compose up -d` is running
# Each step lands files, triggers bronze_ingest and waits for the silver build it sets off.
set -euo pipefail
cd "$(dirname "$0")/.."

af() { docker compose exec -T airflow-scheduler airflow "$@" 2>/dev/null; }
finished_silver_runs() { af dags list-runs -d silver_build | grep -cE 'success|failed' || true; }

step() {
  local before; before=$(finished_silver_runs)   # count first: the 15-minute schedule may load the files before our trigger does
  python3 scripts/land.py "$@"
  af dags trigger bronze_ingest >/dev/null
  for _ in $(seq 1 60); do
    [ "$(finished_silver_runs)" -gt "$before" ] && break
    sleep 5
  done
  [ "$(finished_silver_runs)" -gt "$before" ] || { echo "  no silver run after 5 minutes: check the bronze_ingest logs"; exit 1; }
  af dags list-runs -d silver_build | grep -E 'success|failed' | head -1 | awk -F'|' '{print "  silver_build:" $3}'
}

echo "Resetting warehouse and landing zone"
af dags pause bronze_ingest >/dev/null
rm -rf warehouse/warehouse.duckdb warehouse/warehouse.duckdb.wal .landing-staging
# empty landing/ in place: deleting the folder itself would detach the containers' bind mount
mkdir -p landing && find landing -mindepth 1 -delete
af dags unpause bronze_ingest >/dev/null
# A paused DAG queues every update and never runs. Pausing is an operator's decision, so stop rather than override it.
for d in silver_build risk_model; do
  if af dags list | grep -E "^$d " | grep -q True; then
    echo "$d is paused in Airflow. Unpause it (UI or: docker compose exec airflow-scheduler airflow dags unpause $d) and rerun."
    exit 1
  fi
done

wait_for_silver() {
  local before=$1
  for _ in $(seq 1 60); do
    [ "$(finished_silver_runs)" -gt "$before" ] && break
    sleep 5
  done
  [ "$(finished_silver_runs)" -gt "$before" ] || { echo "  no silver run after 5 minutes"; exit 1; }
  af dags list-runs -d silver_build | grep -E 'success|failed' | head -1 | awk -F'|' '{print "  silver_build:" $3}'
}

step --until 2024-12
step --until 2025-06
step --all

echo "Labeling a sample of account matches, then rebuilding silver with measured confidence"
.venv/bin/python scripts/label_matches.py | head -1
before=$(finished_silver_runs)
af dags trigger silver_build >/dev/null
wait_for_silver "$before"
echo "Done. Check: .venv/bin/python scripts/verify_warehouse.py"
