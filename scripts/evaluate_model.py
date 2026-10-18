"""Judge the production risk model against the generator's hidden truth, then write MODEL_REPORT.md.

    .venv/bin/python scripts/evaluate_model.py

The model never sees the ground truth: it trains on outcomes the source systems recorded. This script
is the one place the two meet, answering the questions the business actually asked:
  * Would the at-risk accounts have been on their CSM's list in time? (the two lost renewals)
  * Which kinds of churn does it catch, and which can't it see?
  * Does it cry wolf on accounts that only look risky (seasonal dips, ticket-heavy loyal customers)?
Opens the warehouse read-only: run it when no Airflow task is writing."""
import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TOP_K = 10
con = duckdb.connect(str(ROOT / "warehouse" / "warehouse.duckdb"), read_only=True, config={"TimeZone": "UTC"})
truth = pd.read_parquet(ROOT / "lake" / "_ground_truth" / "account_truth.parquet")

reg = con.execute("select model_version, decision, metrics, train_rows, valid_rows, test_rows, best_iteration "
                  "from ml.model_registry where status = 'production' order by trained_at desc limit 1").df().iloc[0]
metrics = json.loads(reg.metrics)
version = reg.model_version
preds = con.execute("select * from ml.test_predictions where model_version = ?", [version]).df()
preds["as_of"] = pd.to_datetime(preds.as_of)
preds["owner_id"] = preds.owner_id.fillna("unassigned")
for col in ("risk_prob", "logistic_prob", "rules_score"):
    preds[f"rank_{col}"] = preds.groupby(["as_of", "tenant_id", "owner_id"])[col].rank(method="first", ascending=False)

L = ["# Risk model report", "", f"Production model **{version}**. {reg.decision}.", "",
     f"Training rows {reg.train_rows:,}, validation {reg.valid_rows:,}, test {reg.test_rows:,} "
     f"(test = monthly snapshots from {preds.as_of.min():%Y-%m} to {preds.as_of.max():%Y-%m}); "
     f"{reg.best_iteration} boosting rounds.", ""]

# 1. against the recorded outcomes
L += ["## 1. Test window: model vs baselines", "",
      "Positive = the account churned or downsized within 90 days, as recorded in Salesforce/Stripe.", "",
      "| Model | PR-AUC | ROC-AUC | Brier | Precision of each CSM's top 10 | Share of outcomes in a top-10 list |",
      "|---|---:|---:|---:|---:|---:|"]
for name, label in (("lightgbm", "LightGBM (production)"), ("logistic", "Logistic regression"), ("rules", "Hand-written rules")):
    m = metrics[name]
    L.append(f"| {label} | {m['pr_auc']:.3f} | {m['roc_auc']:.3f} | {m['brier']:.3f} | {m['precision_at_k']:.1%} | {m['recall_at_k']:.1%} |")
base = metrics["lightgbm"]["base_rate"]
L += ["", f"Base rate {base:.1%}: a random top 10 would contain {base * 10:.1f} real outcomes; the model's contains "
          f"{metrics['lightgbm']['precision_at_k'] * 10:.1f}.", ""]
L += ["### Calibration (test window)", "", "| Predicted band | Accounts | Mean predicted | Observed rate |", "|---|---:|---:|---:|"]
L += [f"| {c['bin']} | {c['rows']:,} | {c['predicted']:.1%} | {c['observed']:.1%} |" for c in metrics["calibration"]]
L += ["", f"Calibrated per tenant: {', '.join(metrics['calibrated_tenants']) or 'none'}; others use the pooled curve.", ""]

# 2. against the hidden truth: churn the model should have seen coming
t = truth[truth.lifecycle == "customer"].copy()
t["churn_date"] = pd.to_datetime(t.churn_date)
window_lo, window_hi = preds.as_of.min(), preds.as_of.max() + pd.Timedelta(days=90)
churners = t[(t.outcome == "churned") & t.churn_date.between(window_lo, window_hi)]
p = preds.merge(churners[["account_id", "archetype", "churn_date", "churn_type", "detectable"]], on="account_id")
p = p[(p.as_of < p.churn_date) & (p.as_of >= p.churn_date - pd.Timedelta(days=90))]


def caught(col):
    hit = p[p[f"rank_{col}"] <= TOP_K].groupby("account_id").agg(first=("as_of", "min"), churn=("churn_date", "first"))
    hit["lead_days"] = (hit.churn - hit["first"]).dt.days
    return hit


rows = []
for arch, g in p.groupby("archetype"):
    ids = g.account_id.unique()
    r = dict(archetype=arch, churners=len(ids))
    for col, key in (("risk_prob", "model"), ("rules_score", "rules")):
        h = caught(col)
        h = h[h.index.isin(ids)]
        r[key] = len(h)
        r[f"{key}_lead"] = h.lead_days.median() if len(h) else None
    rows.append(r)
by = pd.DataFrame(rows).sort_values("churners", ascending=False)
tot_c, tot_m, tot_r = by.churners.sum(), by.model.sum(), by.rules.sum()
L += ["## 2. Real churn in the test window (hidden truth)", "",
      f"Accounts that truly churned between {window_lo:%Y-%m-%d} and {window_hi:%Y-%m-%d}, and whether they appeared in "
      f"their CSM's top {TOP_K} on a monthly snapshot in the 90 days before churning.", "",
      "| Why it churned (generator archetype) | Churned | On the list: model | Median warning (days) | On the list: rules |",
      "|---|---:|---:|---:|---:|"]
for r in by.itertuples():
    lead = f"{r.model_lead:.0f}" if r.model_lead == r.model_lead and r.model_lead is not None else "-"
    L.append(f"| {r.archetype} | {r.churners} | {r.model} ({r.model / r.churners:.0%}) | {lead} | {r.rules} ({r.rules / r.churners:.0%}) |")
L += [f"| **All** | **{tot_c}** | **{tot_m} ({tot_m / max(tot_c, 1):.0%})** | | **{tot_r} ({tot_r / max(tot_c, 1):.0%})** |", ""]
silent = by[by.archetype == "silent_churn"]
if len(silent):
    L += ["`silent_churn` accounts leave with no warning signs by design. The model still lists some of them because churn "
          "happens at renewal and renewal timing is its strongest input: that is \"renewal is close\", which a CSM already "
          "knows, not foresight. Read the other rows for the model's real early warning.", ""]

# 3. right now: the accounts heading for churn after the data ends
latest = con.execute("select max(as_of) from ml.risk_scores").fetchone()[0]
now = con.execute("select * from ml.risk_scores where as_of = ?", [latest]).df().merge(
    t[["account_id", "archetype", "outcome"]], on="account_id", how="left")
now = now.merge(t[["account_id", "outcome_date"]], on="account_id", how="left")
now["days_to_outcome"] = (pd.to_datetime(now.outcome_date) - pd.Timestamp(latest)).dt.days
at_risk = now[now.outcome == "at_risk"]
L += [f"## 3. Today's list ({latest:%Y-%m-%d})", "",
      f"{len(now):,} live customers scored: " + ", ".join(f"{k} {v:,}" for k, v in now.band.value_counts().items()) +
      f"; {int((now.status == 'insufficient_data').sum()):,} with too little recent data to judge; "
      f"{int((now.status == 'customer_notice').sum())} with a customer notice.", "",
      f"{len(at_risk)} accounts are truly heading for churn or downsell after the data ends. The model warns 90 days "
      f"ahead, so they are split by when the outcome lands:", "",
      "| Outcome lands | Accounts | On their CSM's top 10 | Flagged red/yellow | Undetectable by design |", "|---|---:|---:|---:|---:|"]
for label, g in (("within 90 days", at_risk[at_risk.days_to_outcome <= 90]),
                 ("91-180 days", at_risk[at_risk.days_to_outcome.between(91, 180)]),
                 ("later", at_risk[at_risk.days_to_outcome > 180])):
    if len(g):
        L.append(f"| {label} | {len(g)} | {int((g.rank_in_book <= TOP_K).sum())} ({(g.rank_in_book <= TOP_K).mean():.0%}) | "
                 f"{int(g.band.isin(['red', 'yellow']).sum())} ({g.band.isin(['red', 'yellow']).mean():.0%}) | "
                 f"{int((g.archetype == 'silent_churn').sum())} |")
L += ["", "Outcomes more than 90 days out are outside what the model is built to see; they should rise as renewal nears.", ""]

# 4. false alarms on accounts that only look risky
L += ["## 4. Does it cry wolf?", "", "Share of each healthy group flagged red or yellow today (no churn coming):", "",
      "| Group | Accounts | Flagged | On a top-10 list |", "|---|---:|---:|---:|"]
for arch in ("healthy", "expanding", "seasonal", "noisy_loyal", "dormant"):
    g = now[(now.archetype == arch) & (now.outcome.isin(["renewed", "recovered"]))]
    if len(g):
        L.append(f"| {arch} | {len(g):,} | {g.band.isin(['red', 'yellow']).mean():.1%} | {(g.rank_in_book <= TOP_K).mean():.1%} |")
L += ["", "Seasonal and noisy-but-loyal accounts are the traps: they look like churners on one signal (usage dip, ticket volume).", ""]

# 5. what drives it
L += ["## 5. What the model leans on", "", "Top features by total gain:", ""]
L += [f"{i}. `{f}`" for i, f in enumerate(metrics["top_features_by_gain"], start=1)]
L += ["", "Notices (cancellation requests, scheduled cancellations, agent risk flags) are deliberately not inputs: "
          "they are shown to the CSM as known risk. CSM save plays are excluded too, since they react to risk already seen.", ""]

out = ROOT / "MODEL_REPORT.md"
out.write_text("\n".join(L))
print("\n".join(L))
