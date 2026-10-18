"""Produce the labeled sample that sets account-match confidence.

    .venv/bin/python scripts/label_matches.py            # writes dbt/seeds/identity_labels.csv

In a real team an analyst checks a sample of matches by hand. Here the generator's ground truth
plays the analyst: for each sampled record it supplies the account the record truly belongs to.

The sample is stratified by (source system, match rule), up to PER_RULE records each, so rare rules
such as name matching get enough labels to measure. It also labels a slice of quarantined records,
which shows what the matcher is missing. Run it while no Airflow task is writing to the warehouse
(it opens the warehouse read-only), then let silver rebuild to pick the labels up."""
import argparse
import csv
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PER_RULE = 150
QUARANTINE = 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-rule", type=int, default=PER_RULE)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    con = duckdb.connect(str(ROOT / "warehouse" / "warehouse.duckdb"), read_only=True)
    picks = con.execute("""
        select tenant_id, source_system, source_id, match_method as stratum
        from silver.account_xref where source_system <> 'salesforce.account'""").df()
    quarantined = con.execute("""
        select tenant_id, source_system, source_id, 'quarantine' as stratum from ops.quarantine_identity""").df()
    con.close()

    sample = pd.concat([
        picks.sample(frac=1, random_state=args.seed).groupby(["source_system", "stratum"]).head(args.per_rule),
        quarantined.sample(min(len(quarantined), QUARANTINE), random_state=args.seed),
    ])
    truth = pd.read_parquet(ROOT / "lake" / "_ground_truth" / "identity_truth.parquet").rename(
        columns={"tenant": "tenant_id", "account_id": "true_account_id"})
    labels = sample.merge(truth, on=["tenant_id", "source_system", "source_id"], how="inner")
    labels["labeled_by"] = "synthetic ground truth"

    out = ROOT / "dbt" / "seeds" / "identity_labels.csv"
    labels[["tenant_id", "source_system", "source_id", "true_account_id", "stratum", "labeled_by"]] \
        .sort_values(["source_system", "stratum", "tenant_id", "source_id"]) \
        .to_csv(out, index=False, quoting=csv.QUOTE_MINIMAL)
    counts = labels.groupby(["source_system", "stratum"]).size()
    print(f"wrote {len(labels)} labels to {out.relative_to(ROOT)}")
    print(counts.to_string())


if __name__ == "__main__":
    main()
