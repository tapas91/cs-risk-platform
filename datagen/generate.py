"""Generate the synthetic Fivetran landing zone.

    python -m datagen.generate --scale 0.1 --out lake

Layout:
    <out>/s3/cs-risk-raw/tenant=<t>/<source>/<table>/synced_month=YYYY-MM/part-initial.parquet
                                                                       /part-00000.parquet
    <out>/_ground_truth/  account_truth, identity_truth, health_weekly, text_truth, defect_log, config_used.json
    <out>/REPORT.md       counts, mixes and measured defect rates for review
"""
import argparse
import json
import shutil
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

from . import config as C
from .world import World
from . import sources as S
from .sync import sync_table, legacy_formats

PRIVATE = ["_pk", "_changed_at", "_tenant", "_initial"]


def write_lake(tables, world, root: Path, rng, defects):
    stats = defaultdict(lambda: dict(rows=0, files=0, initial=0, columns=None, sample=[]))
    for fq, rows in tables.items():
        by_tenant = defaultdict(list)
        for r in rows:
            by_tenant[r["_tenant"]].append(r)
        for tkey, trows in by_tenant.items():
            tenant = world.tenants[tkey]
            synced = sync_table(fq, trows, tenant, rng, defects)
            legacy_formats(fq, tenant, synced, defects)
            source, table = fq.split(".")
            # one file per (synced month, initial vs incremental). Real Fivetran writes one file per sync;
            # monthly compaction keeps the file count reviewable without changing what arrives late.
            groups = defaultdict(list)
            for r in synced:
                groups[(r["_fivetran_synced"].strftime("%Y-%m"), r["_initial"])].append(r)
            for (month, initial), grows in sorted(groups.items()):
                df = pd.DataFrame(grows).sort_values("_fivetran_synced")
                df = df.drop(columns=[c for c in PRIVATE if c in df.columns])
                path = root / f"tenant={tkey}" / source / table / f"synced_month={month}"
                path.mkdir(parents=True, exist_ok=True)
                df.to_parquet(path / ("part-initial.parquet" if initial else "part-00000.parquet"), index=False)
                st = stats[fq]
                st["rows"] += len(df)
                st["files"] += 1
                st["initial"] += len(df) if initial else 0
                st["columns"] = sorted(set(st["columns"] or []) | set(df.columns))
                if len(st["sample"]) < 2 and not initial and len(df) > 3:
                    st["sample"].append((tkey, df.iloc[len(df) // 2].to_dict()))
    return stats


def ground_truth(world, ctx, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for a in world.accounts:
        end_h = float(world.health[a.idx, -1])
        rows.append(dict(
            tenant=a.tenant, account_id=a.account_id, name=a.name, domain=a.domain, lifecycle=a.lifecycle,
            archetype=a.archetype, tier=a.tier, seats_at_start=a.seats, arr_at_start=a.arr, currency=a.currency,
            billing_interval=a.billing_interval, is_test=a.is_test, duplicate_sfdc_id=a.duplicate_id,
            presales_outcome=a.presales_outcome, lost_reason=a.lost_reason, has_trial=a.has_trial,
            trial_engagement=round(a.engagement, 3) if a.has_trial else None, contract_start=a.contract_start,
            acquired_in_window=a.acquired_in_window, onset_date=a.onset, outcome=a.outcome, outcome_date=a.outcome_date,
            churn_date=a.churn_date, churn_type=a.churn_type, detectable=a.detectable,
            n_expansions=sum(1 for _, s in a.expansions if s > 0), health_at_window_end=round(end_h, 3),
            parent_id=a.parent_id, same_company_as=a.same_company_as, intervention_date=a.intervention,
            owner_at_window_end=a.owner_on(C.WINDOW_END) if a.lifecycle == "customer" else a.owner_ae))
    pd.DataFrame(rows).to_parquet(out / "account_truth.parquet", index=False)
    hw = [(a.tenant, a.account_id, wk, round(float(world.health[a.idx, i]), 3))
          for a in world.accounts if a.lifecycle == "customer" for i, wk in enumerate(world.weeks) if world.health[a.idx, i] > 0]
    pd.DataFrame(hw, columns=["tenant", "account_id", "week", "health"]).to_parquet(out / "health_weekly.parquet", index=False)
    pd.DataFrame(ctx.text_truth).to_parquet(out / "text_truth.parquet", index=False)
    pd.DataFrame(ctx.defects).to_parquet(out / "defect_log.parquet", index=False)
    pd.DataFrame(ctx.identity_truth).to_parquet(out / "identity_truth.parquet", index=False)
    cfg = {k: v for k, v in vars(C).items() if k.isupper()}
    (out / "config_used.json").write_text(json.dumps(cfg, default=str, indent=2))
    return pd.DataFrame(rows)


EVENT_TABLES = ["salesforce.opportunity", "salesforce.task", "zendesk.ticket", "zendesk.ticket_comment",
                "stripe.invoice", "stripe.charge", "product.event", "gmail.message"]


def report(stats, truth: pd.DataFrame, ctx, scale, seed, out: Path, lake: Path, elapsed: float):
    L = []
    total_events = sum(stats[t]["rows"] for t in EVENT_TABLES if t in stats)
    L += ["# Synthetic CS dataset - review sample", "",
          f"- Scale **{scale}** of full size, seed **{seed}**, window **{C.WINDOW_START} → {C.WINDOW_END}**, dump taken {C.WINDOW_END} + 1 day",
          f"- **{len(truth)}** accounts, **{total_events:,}** event rows (target {int(C.FULL_EVENTS * scale):,}), generated in {elapsed:.1f}s",
          f"- Lake: `{lake}`", ""]
    L += ["## Tables", "", "| Table | Kind | Rows | Files | From initial sync | Columns |", "|---|---|---:|---:|---:|---|"]
    for fq in sorted(stats):
        s = stats[fq]
        kind = "event" if fq in EVENT_TABLES else "reference"
        L.append(f"| `{fq}` | {kind} | {s['rows']:,} | {s['files']} | {s['initial']:,} | {', '.join(s['columns'])} |")
    L += ["", "## Accounts by tenant", "", "| Tenant | Accounts | Customers | Prospects | Test |", "|---|---:|---:|---:|---:|"]
    for t, g in truth.groupby("tenant"):
        L.append(f"| {t} | {len(g)} | {(g.lifecycle == 'customer').sum()} | {(g.lifecycle == 'prospect').sum()} | {g.is_test.sum()} |")
    cust = truth[truth.lifecycle == "customer"]
    L += ["", "## Customer archetypes and outcomes (hidden truth)", "", "| Archetype | Accounts | Outcomes |", "|---|---:|---|"]
    for arch, g in cust.groupby("archetype"):
        oc = ", ".join(f"{k} {v}" for k, v in g.outcome.value_counts().items())
        L.append(f"| {arch} | {len(g)} | {oc} |")
    churned = (cust.outcome == "churned").sum()
    L += ["", f"- Churned inside the window: **{churned}** of {len(cust)} customers ({churned / len(cust):.1%}); "
              f"involuntary {(cust.churn_type == 'involuntary').sum()}, undetectable {((cust.outcome == 'churned') & (cust.detectable == False)).sum()}",
          f"- Still active but heading for churn/downsell after the window (`at_risk`): **{(cust.outcome == 'at_risk').sum()}**",
          f"- Downsold: {(cust.outcome == 'downsold').sum()}, recovered after a risk episode: {(cust.outcome == 'recovered').sum()}", ""]
    pre = truth[truth.presales_outcome.isin(["won", "lost", "open", "nurture"])]
    L += ["## Pre-sales", "", "| Outcome | Accounts | With trial | Avg trial engagement |", "|---|---:|---:|---:|"]
    for oc, g in pre.groupby("presales_outcome"):
        eng = g.trial_engagement.dropna()
        L.append(f"| {oc} | {len(g)} | {g.has_trial.sum()} | {eng.mean():.2f} |" if len(eng) else f"| {oc} | {len(g)} | 0 | - |")
    lr = truth.lost_reason.value_counts()
    L += ["", "Lost reasons: " + ", ".join(f"{k} {v}" for k, v in lr.items()), ""]
    tt = pd.DataFrame(ctx.text_truth)
    if len(tt):
        L += ["## Ticket text", "",
              f"- {len(tt):,} comments: " + ", ".join(f"{k} {v}" for k, v in tt.text_source.value_counts().items()),
              "- Sentiment: " + ", ".join(f"{k} {v}" for k, v in tt.sentiment.value_counts().items()),
              "- Top topics: " + ", ".join(f"{k} {v}" for k, v in tt.topic.value_counts().head(10).items()), ""]
    d = pd.DataFrame(ctx.defects)
    L += ["## Injected defects (from the defect log)", "", "| Table | Defect | Count |", "|---|---|---:|"]
    for (tbl, kind), n in d.groupby(["table", "defect"]).size().items():
        L.append(f"| `{tbl}` | {kind} | {n} |")
    L += ["", "Rates are measured on the output, so they differ slightly from the configured values at this scale.", ""]
    L += ["## Sample rows", ""]
    for fq in sorted(stats):
        L += [f"### `{fq}`", ""]
        for tkey, row in stats[fq]["sample"]:
            L.append(f"- **tenant={tkey}**")
            for k, v in row.items():
                v = str(v)
                L.append(f"  - `{k}`: {v[:160] + '...' if len(v) > 160 else v}")
        L.append("")
    (out / "REPORT.md").write_text("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=C.SEED)
    ap.add_argument("--out", default="lake")
    args = ap.parse_args()
    t0 = time.time()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    world = World(args.scale, args.seed)
    ctx = S.Ctx(world)
    S.build_people(ctx)
    tables = {}
    for src, fn in (("salesforce", S.emit_salesforce), ("zendesk", S.emit_zendesk), ("gmail", S.emit_gmail),
                    ("stripe", S.emit_stripe)):
        for tbl, rows in fn(ctx).items():
            tables[f"{src}.{tbl}"] = rows
    used = sum(len(tables[t]) for t in EVENT_TABLES if t in tables)
    budget = C.FULL_EVENTS * args.scale
    target = max(budget - used, budget * C.PRODUCT_MIN_SHARE)
    for tbl, rows in S.emit_product(ctx, target).items():
        tables[f"product.{tbl}"] = rows
    lake = out / "s3" / "cs-risk-raw"
    stats = write_lake(tables, world, lake, world.rng, ctx.defects)
    truth = ground_truth(world, ctx, out / "_ground_truth")
    report(stats, truth, ctx, args.scale, args.seed, out, lake, time.time() - t0)
    print((out / "REPORT.md").read_text())


if __name__ == "__main__":
    main()
