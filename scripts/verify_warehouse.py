"""Check the warehouse against the generated lake and its ground truth.

    .venv/bin/python scripts/verify_warehouse.py

Opens warehouse/warehouse.duckdb read-only, so run it when no Airflow task is writing."""
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
con = duckdb.connect(str(ROOT / "warehouse" / "warehouse.duckdb"), read_only=True, config={"TimeZone": "UTC"})
truth = pd.read_parquet(ROOT / "lake" / "_ground_truth" / "account_truth.parquet")
defects = pd.read_parquet(ROOT / "lake" / "_ground_truth" / "defect_log.parquet")
results = []


def check(name, ok, detail):
    results.append((name, "PASS" if ok else "FAIL", detail))


def q(sql):
    return con.execute(sql).fetchall()


# 1. bronze is a complete, exact copy of what landed
lake_files = list((ROOT / "lake" / "s3" / "cs-risk-raw").rglob("*.parquet"))
lake_rows = sum(duckdb.sql(f"select count(*) from read_parquet('{f}')").fetchone()[0] for f in lake_files)
files, rows = q("select count(*), sum(row_count) from bronze._ingested_files")[0]
check("bronze: every landed file loaded once", files == len(lake_files), f"{files:,} of {len(lake_files):,} files")
check("bronze: row count equals the lake", rows == lake_rows, f"{rows:,} rows vs {lake_rows:,} in the lake")

# 2. dedupe: retried product events collapse to one row each
# (the defect log also counts retries that never landed: lost in an outage or synced after the dump)
bronze_ev, distinct_ev = q("select count(*), count(distinct (_tenant_id, event_id)) from bronze.product__event")[0]
silver_ev = q("select count(*) from silver.fct_product_event")[0][0]
check("silver: product event retries removed", silver_ev == distinct_ev,
      f"{bronze_ev:,} bronze rows -> {silver_ev:,} silver events; {bronze_ev - silver_ev:,} retried deliveries removed")

# 3. event names unified across the 2024-07-01 rename
names = q("select count(distinct event_name), count(*) filter (where event_name like '%\\_%' escape '\\' and event_name not like '%.%') from silver.fct_product_event")[0]
check("silver: one event-name vocabulary", names[1] == 0, f"{names[0]} canonical names, {names[1]} old-style left")

# 4. legacy dd/mm/yyyy task dates parsed
legacy = q("select count(*) filter (where is_legacy_date_format), count(*) filter (where activity_date is null) from silver.fct_activity")[0]
check("silver: legacy task dates parsed", legacy[1] == 0, f"{legacy[0]} dd/mm/yyyy rows parsed, {legacy[1]} unparsed")

# 5. merged Salesforce duplicates point at their master
merged = truth.dropna(subset=["duplicate_sfdc_id"])
redir = dict(q("select account_id, master_account_id from silver.dim_account_history where is_current"))
done = [r for r in merged.itertuples() if redir.get(r.duplicate_sfdc_id) == r.account_id]
merged_in_window = q("select count(*) from silver.dim_account_history where is_current and is_deleted")[0][0]
check("silver: merged duplicates redirect to master", len(done) == merged_in_window,
      f"{len(done)} of {len(merged)} duplicates merged by the dump date (the rest are still separate in Salesforce)")

# 6. every account match agrees with the generator's identity truth
ident = pd.read_parquet(ROOT / "lake" / "_ground_truth" / "identity_truth.parquet")
truth_of = {(r.tenant, r.source_system, r.source_id): r.account_id for r in ident.itertuples()}
xr = q("select tenant_id, source_system, source_id, account_id, match_method from silver.account_xref where source_system <> 'salesforce.account'")
wrong = [x for x in xr if truth_of.get((x[0], x[1], x[2])) not in (x[3], None)]
by_name = sum(1 for x in xr if x[4] == "name")
# A source record can carry the ID of a Salesforce duplicate that hasn't been merged yet. That account is live,
# so following the stored link is right; ground truth points at the record that will survive the merge.
live_dupes = {r[0] for r in q("""select account_id from silver.dim_account a where exists (
    select 1 from silver.dim_account b where b.tenant_id = a.tenant_id and b.account_id <> a.account_id
      and b.website_domain = a.website_domain)""")}
explained = sum(1 for x in wrong if x[3] in live_dupes)
precision = 1 - len(wrong) / max(len(xr), 1)
check("silver: account matches are correct", precision >= 0.995,
      f"{len(xr):,} Stripe/Zendesk/workspace records matched ({by_name} by name); precision {precision:.2%}; "
      f"{len(wrong)} wrong, {explained} of them a stored ID pointing at an unmerged Salesforce duplicate")

# 7. identity coverage and quarantine
cov = q("""select source_system, count(*) from silver.account_xref group by 1 order by 1""")
quar = q("select source_system, reason, count(*) from ops.quarantine_identity group by 1, 2 order by 1, 2")
check("silver: account master built", len(cov) == 4, "; ".join(f"{s} {n:,}" for s, n in cov))
check("ops: unmatched records quarantined, not dropped", len(quar) > 0, "; ".join(f"{s} {r} {n}" for s, r, n in quar))

# 8. tenant isolation: the same company in two tenants stays two accounts
pairs = truth.dropna(subset=["same_company_as"])
leak = q("""select count(*) from silver.account_xref x join silver.dim_account a
            on a.account_id = x.account_id where a.tenant_id <> x.tenant_id""")[0][0]
check("silver: no match crosses tenants", leak == 0, f"{len(pairs) // 2} same-company pairs kept apart; {leak} cross-tenant links")

# 9. soft deletes flagged, not lost
deleted = q("select count(*) from silver.fct_ticket where is_deleted")[0][0]
landed = q("select count(distinct (_tenant_id, id)) from bronze.zendesk__ticket where _fivetran_deleted")[0][0]
check("silver: soft-deleted tickets flagged", deleted == landed, f"{deleted} flagged, {landed} deletions landed in bronze")

# 10. the stalled feed is visible
stale = q("select tenant_id, source_table, hours_behind, freshness_status from ops.source_freshness where freshness_status <> 'ok' and freshness_status <> 'not_monitored' order by hours_behind desc")
check("ops: Quarry's stalled Stripe feed flagged", any(s[0] == "quarry" and s[1].startswith("stripe") for s in stale),
      "; ".join(f"{t} {s} {h}h {st}" for t, s, h, st in stale))

# 11. bitemporal history: initial backfill visible as a known_at jump
backfill = q("""select tenant_id, count(*) filter (where date_diff('day', valid_from, known_at) > 30) from silver.dim_account_history group by 1 order by 1""")
check("silver: history keeps source time and arrival time", all(n > 0 for _, n in backfill),
      "versions known 30+ days after they happened: " + ", ".join(f"{t} {n}" for t, n in backfill))

# 12. match confidence is measured, and the rule order still follows the priors
mp = q("""select count(*) filter (where confidence_source = 'measured'), count(*) filter (where n_labeled >= 30),
                 min(confidence) filter (where confidence_source = 'measured') from ops.match_precision""")[0]
out_of_order = q("""select count(*) from silver.account_xref x
    join silver.account_match_candidates c using (tenant_id, source_system, source_id)
    join ops.match_precision pc on pc.source_system = c.source_system and pc.match_method = c.match_method
    join ops.match_precision px on px.source_system = x.source_system and px.match_method = x.match_method
    where pc.confidence >= 0.7 and pc.prior_confidence > px.prior_confidence""")[0][0]
check("silver: match confidence measured from labels", mp[0] == mp[1] and mp[0] > 0 and out_of_order == 0,
      f"{mp[0]} rules measured (lowest {mp[2]}); {out_of_order} records won by a weaker rule than available")

# 13. agent: every brief sentence cites evidence that exists, nothing was sent to a customer, one action per case
has_agent = q("select count(*) from information_schema.tables where table_schema = 'agent' and table_name = 'cases'")[0][0]
if has_agent:
    cases = q("select count(*) from agent.cases")[0][0]
    dangling = q("""select count(*) from agent.cases c, unnest(cast(c.brief as json[])) as b(s), unnest(cast(s->'evidence' as varchar[])) as e(id)
                    where not exists (select 1 from agent.evidence v where v.case_id = c.case_id and v.evidence_id = e.id)""")[0][0]
    uncited = q("select count(*) from agent.cases, unnest(cast(brief as json[])) as b(s) where json_array_length(s->'evidence') = 0")[0][0]
    sent = q("select count(*) from agent.cases where outreach_status is not null and outreach_status <> 'draft_awaiting_csm_approval'")[0][0]
    dup = q("select count(*) - count(distinct case_id) from agent.actions")[0][0]
    by = dict(q("select decided_by, count(*) from agent.cases group by 1"))
    check("agent: briefs cited, drafts unsent, actions idempotent", cases > 0 and not (dangling or uncited or sent or dup),
          f"{cases} cases ({', '.join(f'{k} {v}' for k, v in by.items())}); {uncited} uncited sentences, {dangling} citations "
          f"to missing evidence, {sent} drafts sent, {dup} duplicate actions")

# 14. agent runs are recorded honestly: the latest run finished, and failed cases are counted, not lost
if has_agent:
    runs = dict(q("select status, count(*) from agent.runs group by 1"))
    latest = q("select status from agent.runs order by started_at desc limit 1")[0][0]
    has_failures = q("select count(*) from information_schema.tables where table_schema = 'agent' and table_name = 'failures'")[0][0]
    failed_cases = q("select count(*) from agent.failures")[0][0] if has_failures else 0
    check("agent: runs recorded honestly", latest in ("ok", "partial"),
          f"latest run {latest}; runs by status {runs}; {failed_cases} failed case attempts recorded for retry")

w = max(len(r[0]) for r in results)
for name, status, detail in results:
    print(f"{status}  {name.ljust(w)}  {detail}")
print(f"\n{sum(r[1] == 'PASS' for r in results)} of {len(results)} checks passed")
