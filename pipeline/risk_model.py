"""Account risk model: train, gate, and score.

    $ML_PYTHON -m pipeline.risk_model train   # fit, evaluate against baselines, promote if it wins
    $ML_PYTHON -m pipeline.risk_model score   # score live customers with the production model

Reads gold.account_features / gold.account_labels (built by dbt) and writes to the `ml` schema:
    ml.model_registry     every trained model, its metrics and whether it was promoted
    ml.test_predictions   held-out predictions per model, for evaluation and audits
    ml.risk_scores        one row per (as-of date, account) in the current score window: probability,
                          band, priority, lineage. Each scoring run replaces the whole window
    ml.risk_reasons       the features that pushed each score up, with their values
Model files live in MODEL_DIR/<version>/.

Design choices worth knowing:
  * Time-based split with a purge gap: training rows whose 90-day outcome window overlaps the
    validation period are dropped, so the model never learns from outcomes it is validated on.
  * Notices (cancellation requests, scheduled cancellations, agent risk flags) and CSM save plays are
    not inputs. They are known risk, shown to the CSM separately; the model is for early warning.
  * The probability is calibrated (isotonic, on validation), per tenant where a tenant has enough
    positives, so 0.30 means roughly 30% of such accounts churn or downsell within 90 days.
  * Reasons are exact per-prediction feature contributions from the trees (TreeSHAP, built into LightGBM).
"""
import json
import os
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

WAREHOUSE = os.environ.get("WAREHOUSE_PATH", "warehouse/warehouse.duckdb")
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "models_store"))

NUMERIC = [
    "tenure_days", "days_to_renewal", "arr",
    "usage_events_30d", "usage_events_prior_60d", "usage_trend", "active_users_30d", "seat_utilisation",
    "active_user_trend", "exports_30d", "export_share_30d", "failed_exports_30d", "value_events_90d",
    "seat_removals_90d", "admin_changes_90d", "days_since_last_usage",
    "tickets_30d", "tickets_90d", "urgent_tickets_90d", "incident_tickets_90d", "open_tickets", "bad_csat_90d",
    "good_csat_90d", "avg_resolution_hours_90d", "data_export_tickets_60d", "pricing_tickets_60d",
    "emails_out_90d", "emails_in_90d", "email_response_ratio_90d", "email_bounces_90d", "days_since_customer_email",
    "failed_charges_60d", "subscribed_seats", "seat_trend_90d",
    "active_contacts", "active_champions", "champions_lost", "days_since_csm_activity", "csm_activities_90d",
    "sources_with_signal_90d",
]
BOOLEAN = ["is_new_customer", "renewal_date_missing", "is_past_due", "owner_missing"]
CATEGORICAL = ["tier", "tenant_id"]
FEATURES = NUMERIC + BOOLEAN + CATEGORICAL
NOTICES = ["notice_cancellation_request", "notice_cancel_scheduled", "notice_agent_flagged_risk"]

# What a CSM reads next to a score. {v} is the feature's value on that date.
REASON_TEXT = {
    "usage_trend": "Usage at {v:.0%} of its prior level", "active_user_trend": "Active users at {v:.0%} of prior level",
    "seat_utilisation": "Only {v:.0%} of paid seats active", "usage_events_30d": "{v:.0f} product events in 30 days",
    "days_since_last_usage": "No product use for {v:.0f} days", "export_share_30d": "{v:.0%} of activity is data export",
    "exports_30d": "{v:.0f} data exports in 30 days", "failed_exports_30d": "{v:.0f} failed exports in 30 days",
    "seat_removals_90d": "{v:.0f} seat removals in 90 days", "admin_changes_90d": "{v:.0f} admin changes in 90 days",
    "urgent_tickets_90d": "{v:.0f} urgent/high tickets in 90 days", "incident_tickets_90d": "{v:.0f} incident tickets in 90 days",
    "tickets_90d": "{v:.0f} tickets in 90 days", "open_tickets": "{v:.0f} open tickets",
    "bad_csat_90d": "{v:.0f} bad CSAT ratings in 90 days", "avg_resolution_hours_90d": "Tickets take {v:.0f}h to resolve",
    "data_export_tickets_60d": "Asked for a data export", "pricing_tickets_60d": "Questioned renewal pricing",
    "email_response_ratio_90d": "Replies to {v:.0%} of our emails", "emails_in_90d": "{v:.0f} emails from the customer in 90 days",
    "email_bounces_90d": "{v:.0f} bounced emails in 90 days", "days_since_customer_email": "No email from the customer for {v:.0f} days",
    "failed_charges_60d": "{v:.0f} failed payments in 60 days", "is_past_due": "Subscription past due",
    "seat_trend_90d": "Seats at {v:.0%} of 90 days ago", "subscribed_seats": "{v:.0f} paid seats", "champions_lost": "Champion has left",
    "active_champions": "{v:.0f} active champions", "active_contacts": "{v:.0f} active contacts",
    "days_since_csm_activity": "No CSM activity for {v:.0f} days", "owner_missing": "No CSM assigned",
    "days_to_renewal": "Renewal in {v:.0f} days", "tenure_days": "Customer for {v:.0f} days",
    "is_new_customer": "In first 90 days", "sources_with_signal_90d": "Signal from only {v:.0f} of 3 sources",
}

# Context, not causes: shown in their own columns (renewal date, ARR) or not actionable at all.
NOT_A_REASON = set(CATEGORICAL) | {"days_to_renewal", "tenure_days", "arr", "admin_changes_90d"}
# Text when the value is missing: for "days since" features, no record inside the 180-day window.
MISSING_TEXT = {"days_since_last_usage": "No product use in 180+ days",
                "days_since_customer_email": "No email from the customer in 180+ days",
                "days_since_csm_activity": "No CSM activity on record in a year",
                "usage_trend": "No usage baseline to compare", "active_user_trend": "No active-user baseline",
                "seat_utilisation": "No paid-seat data", "export_share_30d": "No product activity in 30 days",
                "email_response_ratio_90d": "We sent no email in 90 days", "seat_trend_90d": "No seat history",
                "avg_resolution_hours_90d": "No tickets solved in 90 days", "subscribed_seats": "No subscription on record"}

SPLIT = dict(valid_start="2025-07-01", test_start="2026-01-01", horizon_days=90)
BANDS = dict(red_enter=0.25, red_exit=0.18, yellow_enter=0.10, yellow_exit=0.07, red_confirm_runs=2)
PER_TENANT_MIN_POSITIVES = 50
PROMOTION = dict(min_gain_over_rules=0.0, max_loss_vs_production=0.005)


# ------------------------------------------------------------------ data

def connect(read_only=False):
    return duckdb.connect(WAREHOUSE, read_only=read_only, config={"TimeZone": "UTC"})


def load_training() -> pd.DataFrame:
    with connect(read_only=True) as con:
        return con.execute("""
            select f.*, l.label, l.next_event_type, l.next_event_at
            from gold.account_features f
            join gold.account_labels l using (as_of, tenant_id, account_id)
            where f.purpose = 'train' and l.label_complete
            order by f.as_of""").df()


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    X = df[FEATURES].copy()
    for c in BOOLEAN:
        X[c] = X[c].astype(float)
    for c in CATEGORICAL:
        X[c] = X[c].astype("category")
    return X


def split(df: pd.DataFrame):
    """Train / validation / test by as-of date, purging training rows whose outcome window reaches validation."""
    as_of = pd.to_datetime(df.as_of)
    valid_start, test_start = pd.Timestamp(SPLIT["valid_start"]), pd.Timestamp(SPLIT["test_start"])
    purge = pd.Timedelta(days=SPLIT["horizon_days"])
    train = df[as_of + purge <= valid_start]
    valid = df[(as_of >= valid_start) & (as_of + purge <= test_start)]
    test = df[as_of >= test_start]
    return train, valid, test


# ------------------------------------------------------------------ models

def rules_baseline(df: pd.DataFrame) -> np.ndarray:
    """What a CS team would write by hand: count of classic warning signs. The bar to beat."""
    hits = (
        (df.usage_trend.fillna(1) < 0.5).astype(int)
        + (df.failed_charges_60d > 0).astype(int)
        + (df.champions_lost > 0).astype(int)
        + (df.urgent_tickets_90d >= 2).astype(int)
        + (df.bad_csat_90d > 0).astype(int)
        + (df.days_since_customer_email.fillna(999) > 60).astype(int)
        + df.is_past_due.astype(int)
    )
    return hits / 7.0


def fit_logistic(train):
    num = NUMERIC + BOOLEAN
    pre = ColumnTransformer([
        ("num", Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)), ("scale", StandardScaler())]), num),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
    ])
    model = Pipeline([("pre", pre), ("lr", LogisticRegression(max_iter=2000, class_weight="balanced", C=0.5))])
    X = train[FEATURES].copy()
    X[BOOLEAN] = X[BOOLEAN].astype(float)
    model.fit(X, train.label.astype(int))
    return model


def predict_logistic(model, df):
    X = df[FEATURES].copy()
    X[BOOLEAN] = X[BOOLEAN].astype(float)
    return model.predict_proba(X)[:, 1]


def fit_lightgbm(train, valid):
    params = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_data_in_leaf=60, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=42, deterministic=True,
                  num_threads=2)
    dtrain = lgb.Dataset(prepare(train), train.label.astype(int))
    dvalid = lgb.Dataset(prepare(valid), valid.label.astype(int), reference=dtrain)
    return lgb.train(params, dtrain, num_boost_round=2000, valid_sets=[dvalid],
                     callbacks=[lgb.early_stopping(100, verbose=False)])


class Calibrator:
    """Isotonic calibration on validation predictions; per tenant when a tenant has enough positives."""

    def __init__(self):
        self.global_ = None
        self.by_tenant = {}

    def fit(self, raw, y, tenants):
        self.global_ = IsotonicRegression(out_of_bounds="clip").fit(raw, y)
        for t in np.unique(tenants):
            m = tenants == t
            if y[m].sum() >= PER_TENANT_MIN_POSITIVES:
                self.by_tenant[t] = IsotonicRegression(out_of_bounds="clip").fit(raw[m], y[m])
        return self

    def transform(self, raw, tenants):
        out = self.global_.predict(raw)
        for t, iso in self.by_tenant.items():
            m = tenants == t
            if m.any():
                out[m] = iso.predict(raw[m])
        return out


# ------------------------------------------------------------------ evaluation

def top_k_per_csm(df: pd.DataFrame, score: np.ndarray, k: int = 10):
    """The metric that matches the job: each CSM works ~k accounts a week. Of the k each CSM would
    see per as-of date, how many were real? And what share of all real outcomes made a top-k list?"""
    d = df[["as_of", "tenant_id", "owner_id", "label"]].copy()
    d["score"] = score
    d["owner_id"] = d.owner_id.fillna("unassigned")
    d["rank"] = d.groupby(["as_of", "tenant_id", "owner_id"]).score.rank(method="first", ascending=False)
    top = d[d["rank"] <= k]
    return dict(precision_at_k=float(top.label.mean()), recall_at_k=float(top.label.sum() / max(d.label.sum(), 1)))


def evaluate(df, score) -> dict:
    y = df.label.astype(int).values
    m = dict(pr_auc=float(average_precision_score(y, score)), roc_auc=float(roc_auc_score(y, score)),
             brier=float(brier_score_loss(y, np.clip(score, 0, 1))), base_rate=float(y.mean()), rows=int(len(y)),
             positives=int(y.sum()))
    m.update(top_k_per_csm(df, score))
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()}


def calibration_table(df, prob, bins=(0, 0.02, 0.05, 0.1, 0.2, 0.35, 1.0)):
    d = pd.DataFrame({"prob": prob, "y": df.label.astype(int).values})
    d["bin"] = pd.cut(d.prob, bins, include_lowest=True)
    t = d.groupby("bin", observed=True).agg(rows=("y", "size"), predicted=("prob", "mean"), observed=("y", "mean"))
    return [dict(bin=str(i), rows=int(r.rows), predicted=round(float(r.predicted), 4), observed=round(float(r.observed), 4))
            for i, r in t.iterrows()]


# ------------------------------------------------------------------ registry

def ensure_ml_schema(con):
    con.execute("create schema if not exists ml")
    con.execute("""create table if not exists ml.model_registry (
        model_version varchar primary key, trained_at timestamptz, status varchar, promoted boolean,
        decision varchar, train_rows bigint, valid_rows bigint, test_rows bigint, best_iteration integer,
        metrics json, features json, split json)""")
    con.execute("""create table if not exists ml.test_predictions (
        model_version varchar, as_of date, tenant_id varchar, account_id varchar, owner_id varchar,
        label boolean, risk_prob double, logistic_prob double, rules_score double)""")
    con.execute("""create table if not exists ml.risk_scores (
        as_of date, tenant_id varchar, account_id varchar, account_name varchar, owner_id varchar,
        risk_prob double, band varchar, band_note varchar, status varchar, notices varchar,
        arr_usd double, days_to_renewal integer, priority double, rank_in_book integer,
        model_version varchar, feature_cutoff timestamptz, data_as_of date, scored_at timestamptz)""")
    con.execute("""create table if not exists ml.risk_reasons (
        as_of date, tenant_id varchar, account_id varchar, model_version varchar, reason_rank integer,
        feature varchar, feature_value double, contribution double, reason varchar)""")


def production_model(con):
    row = con.execute("""select model_version from ml.model_registry where status = 'production'
                         order by trained_at desc limit 1""").fetchone()
    return row[0] if row else None


def load_artifacts(version):
    d = MODEL_DIR / version
    booster = lgb.Booster(model_file=str(d / "model.txt"))
    with open(d / "calibrator.pkl", "rb") as f:
        cal = pickle.load(f)
    return booster, cal, json.loads((d / "metadata.json").read_text())


def predict(booster, cal, df):
    raw = booster.predict(prepare(df))
    return cal.transform(raw, df.tenant_id.values), raw


# ------------------------------------------------------------------ train

def train():
    df = load_training()
    tr, va, te = split(df)
    print(f"rows: train {len(tr):,} ({tr.label.sum()} positive), valid {len(va):,} ({va.label.sum()}), test {len(te):,} ({te.label.sum()})")

    booster = fit_lightgbm(tr, va)
    cal = Calibrator().fit(booster.predict(prepare(va)), va.label.astype(int).values, va.tenant_id.values)
    prob_te, _ = predict(booster, cal, te)
    logit = fit_logistic(tr)
    p_logit = predict_logistic(logit, te)
    p_rules = rules_baseline(te).values

    metrics = dict(lightgbm=evaluate(te, prob_te), logistic=evaluate(te, p_logit), rules=evaluate(te, p_rules),
                   calibration=calibration_table(te, prob_te),
                   calibrated_tenants=sorted(cal.by_tenant))
    importance = dict(zip(booster.feature_name(), booster.feature_importance("gain").round(1).tolist()))
    metrics["top_features_by_gain"] = dict(sorted(importance.items(), key=lambda kv: -kv[1])[:12])

    version = datetime.now(timezone.utc).strftime("risk-%Y%m%dT%H%M%S")
    with connect() as con:
        ensure_ml_schema(con)
        current = production_model(con)
        decision, promote = gate(metrics, current, te)
        out = MODEL_DIR / version
        out.mkdir(parents=True, exist_ok=True)
        booster.save_model(str(out / "model.txt"))
        with open(out / "calibrator.pkl", "wb") as f:
            pickle.dump(cal, f)
        meta = dict(model_version=version, features=FEATURES, categorical=CATEGORICAL, split=SPLIT, bands=BANDS,
                    metrics=metrics, best_iteration=booster.best_iteration, decision=decision)
        (out / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))

        if promote:
            con.execute("update ml.model_registry set status = 'retired' where status = 'production'")
        con.execute("insert into ml.model_registry values (?, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [version, "production" if promote else "rejected", promote, decision, len(tr), len(va), len(te),
                     booster.best_iteration, json.dumps(metrics), json.dumps(FEATURES), json.dumps(SPLIT)])
        preds = te[["as_of", "tenant_id", "account_id", "owner_id", "label"]].copy()
        preds.insert(0, "model_version", version)
        preds["risk_prob"], preds["logistic_prob"], preds["rules_score"] = prob_te, p_logit, p_rules
        con.register("preds", preds)
        con.execute("insert into ml.test_predictions select * from preds")

    print(json.dumps({k: metrics[k] for k in ("lightgbm", "logistic", "rules")}, indent=2))
    print(f"{version}: {decision}")
    return version


def gate(metrics, current, test_df):
    """Promote only if the model beats the hand-written rules and doesn't lose to the current model."""
    new = metrics["lightgbm"]["pr_auc"]
    rules = metrics["rules"]["pr_auc"]
    if new <= rules + PROMOTION["min_gain_over_rules"]:
        return f"rejected: PR-AUC {new} does not beat rules baseline {rules}", False
    if current:
        booster, cal, _ = load_artifacts(current)
        cur = evaluate(test_df, predict(booster, cal, test_df)[0])["pr_auc"]
        if new < cur - PROMOTION["max_loss_vs_production"]:
            return f"rejected: PR-AUC {new} below production {current} ({cur}) on the same test window", False
        return f"promoted: PR-AUC {new} vs rules {rules}, production {cur}", True
    return f"promoted: PR-AUC {new} vs rules {rules} (first model)", True


# ------------------------------------------------------------------ score

def bands_with_hysteresis(scores: pd.DataFrame) -> pd.DataFrame:
    """Walk each account's weekly scores in order. Red needs two runs in a row above the entry line and
    stays until it drops below a lower exit line; the same for yellow. Stops weekly flip-flopping."""
    b = BANDS
    rows = []
    for _, g in scores.sort_values("as_of").groupby(["tenant_id", "account_id"], sort=False):
        band, above_red = "green", 0
        for r in g.itertuples():
            p, note = r.risk_prob, ""
            above_red = above_red + 1 if p >= b["red_enter"] else 0
            if band == "red":
                if p < b["red_exit"]:
                    band = "yellow" if p >= b["yellow_exit"] else "green"
                    note = "left red"
            elif above_red >= b["red_confirm_runs"]:
                band, note = "red", "entered red"
            elif p >= b["red_enter"]:
                band, note = "yellow", "above red line, waiting for confirmation"
            elif band == "yellow":
                if p < b["yellow_exit"]:
                    band, note = "green", "left yellow"
            elif p >= b["yellow_enter"]:
                band, note = "yellow", "entered yellow"
            rows.append((r.Index, band, note))
    idx, band, note = zip(*rows) if rows else ([], [], [])
    out = scores.copy()
    out.loc[list(idx), "band"] = list(band)
    out.loc[list(idx), "band_note"] = list(note)
    return out


def reasons(booster, df, version, top=3):
    """Top features pushing each score up, from the trees' exact per-prediction contributions.
    Context features (renewal timing, ARR, tenant, tier) are left out: true, but not something a CSM
    can change, and renewal timing already drives the priority."""
    contrib = booster.predict(prepare(df), pred_contrib=True)[:, :-1]  # last column is the bias term
    names = booster.feature_name()
    actionable = np.array([n not in NOT_A_REASON for n in names])
    contrib = np.where(actionable, contrib, -np.inf)
    order = np.argsort(-contrib, axis=1)[:, :top]
    values = df[names].to_numpy(dtype=object)
    keys = df[["as_of", "tenant_id", "account_id"]].to_numpy(dtype=object)
    out = []
    for i in range(len(df)):
        for rank, j in enumerate(order[i], start=1):
            c = contrib[i, j]
            if not np.isfinite(c) or c <= 0:
                break
            f, v = names[j], values[i, j]
            v = None if pd.isna(v) else float(v)
            if v is None:
                text = MISSING_TEXT.get(f, f"No data for {f.replace('_', ' ')}")
            else:
                text = REASON_TEXT.get(f, f).format(v=v)
            out.append((*keys[i], version, rank, f, v, float(c), text))
    return pd.DataFrame(out, columns=["as_of", "tenant_id", "account_id", "model_version", "reason_rank", "feature",
                                      "feature_value", "contribution", "reason"])


def score():
    with connect(read_only=True) as con:
        version = production_model(con) if con.execute(
            "select count(*) from information_schema.tables where table_schema = 'ml' and table_name = 'model_registry'").fetchone()[0] else None
        if not version:
            # 99 = nothing to score with yet; Airflow's risk_scoring marks the task skipped, not failed
            print("no production model: run `train` first")
            sys.exit(99)
        df = con.execute("select * from gold.account_features where purpose = 'score' order by as_of").df()
        fx_usd = dict(con.execute("select currency, usd_per_unit from reference.fx_rates").fetchall())  # dbt seed
    booster, cal, _ = load_artifacts(version)
    prob, _ = predict(booster, cal, df)

    s = df[["as_of", "tenant_id", "account_id", "account_name", "owner_id", "currency", "arr", "days_to_renewal",
            "feature_cutoff", "data_as_of", "sources_with_signal_90d"] + NOTICES].copy()
    s["risk_prob"] = prob
    s = bands_with_hysteresis(s)
    notice = s[NOTICES].astype(bool)
    s["notices"] = notice.apply(lambda r: ", ".join(n.replace("notice_", "").replace("_", " ") for n, on in r.items() if on), axis=1)
    s["status"] = np.where(notice.any(axis=1), "customer_notice",
                           np.where(s.sources_with_signal_90d == 0, "insufficient_data", "scored"))
    # priority = expected revenue at risk, weighted up to 2x when renewal is inside 180 days.
    # The CSM's list orders by tier first (customer notice, red, yellow, then the rest) and by
    # priority inside each tier, so a large healthy account never pushes out a flagged one.
    s["arr_usd"] = s.arr.fillna(0) * s.currency.map(fx_usd).fillna(1.0)
    proximity = 1 + np.clip((180 - s.days_to_renewal.fillna(365)) / 180, 0, 1)
    s["priority"] = s.risk_prob * s.arr_usd * proximity
    tier = np.select([s.status == "customer_notice", s.band == "red", s.band == "yellow"], [0, 1, 2], 3)
    s["_order"] = tier * 1e12 - s.priority
    s["rank_in_book"] = s.groupby(["as_of", "tenant_id", s.owner_id.fillna("unassigned")])._order.rank(
        method="first").astype(int)
    s["model_version"], s["scored_at"] = version, datetime.now(timezone.utc)
    cols = ["as_of", "tenant_id", "account_id", "account_name", "owner_id", "risk_prob", "band", "band_note", "status",
            "notices", "arr_usd", "days_to_renewal", "priority", "rank_in_book", "model_version", "feature_cutoff",
            "data_as_of", "scored_at"]
    s = s[cols]
    r = reasons(booster, df, version)

    # Replace the whole window, not just this run's dates: score dates step back from the data date, so
    # when it moves by a day the previous run's dates would otherwise stay behind and "last week" would
    # compare against yesterday, scored by another model. One transaction: readers never see it half-written.
    with connect() as con:
        ensure_ml_schema(con)
        dates = s.as_of.unique()
        con.register("s", s)
        con.register("r", r)
        con.execute("begin")
        con.execute("delete from ml.risk_scores")
        con.execute("delete from ml.risk_reasons")
        con.execute("insert into ml.risk_scores select * from s")
        con.execute("insert into ml.risk_reasons select * from r")
        con.execute("commit")
    latest = s[s.as_of == s.as_of.max()]
    print(f"{version} scored {len(s):,} rows over {len(dates)} dates; latest {latest.as_of.max()}: "
          f"{latest.band.value_counts().to_dict()} | status {latest.status.value_counts().to_dict()}")


if __name__ == "__main__":
    {"train": train, "score": score}[sys.argv[1]]()
