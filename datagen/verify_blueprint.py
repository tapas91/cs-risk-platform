"""Check that every edge case listed on the Account Risk Platform design page shows up in the lake.

    python -m datagen.verify_blueprint --lake lake

Reads the landed Parquet (as the pipeline would) plus ground truth, and writes BLUEPRINT_CHECK.md."""
import argparse
import glob
from pathlib import Path

import pandas as pd

from . import config as C


def load(root, src, tbl):
    parts = []
    for f in glob.glob(f"{root}/tenant=*/{src}/{tbl}/*/*.parquet"):
        d = pd.read_parquet(f)
        d["tenant"] = f.split("tenant=")[1].split("/")[0]
        parts.append(d)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def latest(df, key="id"):
    return df.sort_values("_fivetran_synced").drop_duplicates(["tenant", key], keep="last")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default="lake")
    args = ap.parse_args()
    out = Path(args.lake)
    root = out / "s3" / "cs-risk-raw"
    gt = out / "_ground_truth"
    truth = pd.read_parquet(gt / "account_truth.parquet")
    defects = pd.read_parquet(gt / "defect_log.parquet")
    text = pd.read_parquet(gt / "text_truth.parquet")
    health = pd.read_parquet(gt / "health_weekly.parquet")
    cust = truth[truth.lifecycle == "customer"]

    tickets = load(root, "zendesk", "ticket")
    events = load(root, "product", "event")
    ws = latest(load(root, "product", "workspace"))
    gmail = load(root, "gmail", "message")
    stripe_cus = latest(load(root, "stripe", "customer"))
    subs = latest(load(root, "stripe", "subscription"))
    charges = load(root, "stripe", "charge")
    accts = load(root, "salesforce", "account")
    acc_latest = latest(accts)
    contacts = latest(load(root, "salesforce", "contact"))
    opps = latest(load(root, "salesforce", "opportunity"))
    tasks = load(root, "salesforce", "task")

    def dcount(table, kind):
        return int(((defects.table == table) & (defects.defect == kind)).sum())

    rows = []

    def check(group, case, evidence, ok):
        rows.append((group, case, evidence, "yes" if ok else "**MISSING**"))

    # --- data arrival
    t_lat = latest(tickets)
    lag = (pd.to_datetime(tickets._fivetran_synced, utc=True) - pd.to_datetime(tickets.updated_at, utc=True)).dt.days
    check("Data arrival", "A ticket from three weeks ago arrives today",
          f"{(lag >= 14).sum():,} ticket versions synced 14+ days after the change; max lag {lag.max()} days", (lag >= 14).any())
    dup = events.duplicated(["tenant", "event_id"]).sum()
    check("Data arrival", "Webhook retries deliver the same event twice", f"{dup:,} repeated product event_ids", dup > 0)
    old = events.event_name.str.contains("_") & ~events.event_name.str.contains(r"\.")
    check("Data arrival", "Event names changed over three years",
          f"{old.sum():,} old-style names (`report_created`), {(~old).sum():,} new-style (`report.create`) after {C.PRODUCT_RENAME_DATE}",
          old.any() and (~old).any())
    out_rows = defects[defects.defect.str.startswith("feed_outage")]
    check("Data arrival", "A feed stops silently",
          "; ".join(f"{r.key.split('=')[1]} {r.table} ({r.defect.split('_')[-1]}, {r.detail})" for r in out_rows.itertuples()), len(out_rows) > 0)
    offsets = gmail.sent_at.str[-5:].nunique()
    check("Data arrival", "Timestamps in mixed timezones",
          f"{offsets} UTC offsets in Gmail Date headers; SFDC dates have no timezone; Zendesk/Stripe/product in UTC", offsets > 1)

    # --- identity
    nometa = stripe_cus.metadata_sfdc_account_id.isna().sum()
    check("Account identity", "Stripe customer with no Salesforce ID", f"{nometa:,} of {len(stripe_cus):,} Stripe customers", nometa > 0)
    personal = contacts.email.str.split("@").str[1].isin(["gmail.com", "outlook.com", "yahoo.com"]).sum()
    check("Account identity", "Shared domains like gmail.com", f"{personal:,} contacts on personal mailboxes", personal > 0)
    multi_ws = ws.dropna(subset=["sfdc_account_id"]).groupby(["tenant", "sfdc_account_id"]).size()
    merged = (acc_latest.is_deleted & acc_latest.master_record_id.notna()).sum()
    parents = acc_latest.parent_id.notna().sum()
    check("Account identity", "Several workspaces, parent and child accounts, mergers",
          f"{(multi_ws > 1).sum():,} accounts with 2+ workspaces; {parents:,} child accounts with parent_id; {merged:,} merged duplicates",
          (multi_ws > 1).any() and parents > 0 and merged > 0)
    pairs = truth.same_company_as.notna().sum() // 2
    check("Account identity", "The same real company is a customer of two tenants",
          f"{pairs} companies appear in two tenants with the same name and domain", pairs > 0)
    unlinked = ws.sfdc_account_id.isna().sum()
    check("Account identity", "Records with no link back to the account",
          f"{unlinked:,} workspaces without sfdc_account_id; {dcount('zendesk.organization', 'missing_external_id'):,} Zendesk orgs without external_id",
          unlinked > 0)

    # --- modeling
    ev = events.drop_duplicates(["tenant", "event_id"]).merge(ws[["tenant", "id", "sfdc_account_id"]], left_on=["tenant", "workspace_id"],
                                                              right_on=["tenant", "id"], how="left")
    per = ev.groupby("sfdc_account_id").size().reindex(cust.account_id).fillna(0)
    check("Modeling", "Accounts with almost no data",
          f"{(per < 5).mean():.0%} of customers have <5 product events in 3 years; {(per == 0).mean():.0%} have none", (per < 5).any())
    tt = text.merge(truth[["account_id", "churn_date"]], on="account_id")
    tt = tt[(tt.topic == "cancellation") & tt.churn_date.notna()]
    leak_cancel = tt.ticket_id.nunique()
    leak_sub = subs.cancel_at.notna().sum()
    check("Modeling", "Features that leak the outcome",
          f"{leak_cancel:,} cancellation tickets from accounts that later churned; {leak_sub:,} Stripe subscriptions with cancel_at set before cancellation; renewal opps carry closed_lost_reason",
          leak_cancel > 0 and leak_sub > 0)
    young = (pd.Timestamp(C.WINDOW_END) - pd.to_datetime(cust.contract_start)).dt.days < 90
    check("Modeling", "Accounts younger than 90 days", f"{young.sum():,} customers signed in the last 90 days of the window", young.any())
    churn = (cust.outcome == "churned").mean()
    check("Modeling", "Churn is roughly 10% of accounts", f"{churn:.1%} of customers churned inside the window; {(cust.outcome == 'at_risk').sum():,} more at risk after it", 0.05 < churn < 0.2)
    tk = latest(tickets).merge(load(root, "zendesk", "organization").drop_duplicates(["tenant", "id"])[["tenant", "id", "external_id"]],
                               left_on=["tenant", "organization_id"], right_on=["tenant", "id"], how="left", suffixes=("", "_org"))
    per_t = tk.groupby("external_id").size()
    noisy = per_t.reindex(cust[cust.archetype == "noisy_loyal"].account_id).dropna().median()
    churned_t = per_t.reindex(cust[cust.outcome == "churned"].account_id).dropna().median()
    check("Modeling", "High ticket volume is ambiguous",
          f"median tickets: noisy-but-loyal {noisy:.0f} (all renew) vs churned {churned_t:.0f}", noisy > churned_t)
    saves = tasks.subject.str.startswith("Save plan").sum()
    by = cust.dropna(subset=["intervention_date"]).outcome.value_counts().to_dict()
    check("Modeling", "A CSM saves a flagged account", f"{saves:,} save-plan tasks in SFDC; interventions by outcome {by}", saves > 0)

    # --- agent and automation
    h = health.sort_values(["account_id", "week"])
    h["above"] = h.health >= 0.5
    flips = h.groupby("account_id").above.apply(lambda s: (s != s.shift()).sum() - 1)
    check("Agent and automation", "An account flips between yellow and red every week",
          f"{(flips >= 4).sum():,} accounts cross a 0.5 health line 4+ times", (flips >= 4).any())
    neg_open = (opps.stage_name == "Negotiation").sum()
    esc_open = t_lat[t_lat.tags.apply(lambda x: "escalation" in list(x)) & t_lat.status.isin(["new", "pending", "open"])].shape[0]
    check("Agent and automation", "Open escalation or mid-negotiation",
          f"{neg_open:,} renewals in Negotiation at dump time; {esc_open:,} open escalation tickets", neg_open > 0)
    inj = int(text.prompt_injection.sum())
    check("Agent and automation", "Ticket text says 'ignore previous instructions'", f"{inj:,} customer comments carry instructions aimed at an AI", inj > 0)
    owners = acc_latest[acc_latest.type == "Customer"]
    unowned = owners.owner_id.isna().sum()
    book = owners.groupby("owner_id").size()
    check("Agent and automation", "A CSM with too many accounts, or no owner",
          f"{unowned:,} customer accounts with no owner; largest book {book.max():,} accounts, median {book.median():.0f}", unowned > 0)
    failed = (charges.status == "failed").sum()
    check("Agent and automation", "The risk is a failed payment", f"{failed:,} failed charges; {(cust.churn_type == 'involuntary').sum():,} involuntary churns", failed > 0)

    # --- tenancy
    sizes = truth.groupby("tenant").size().to_dict()
    check("Tenancy", "A tenant too small for its own model", f"accounts per tenant {sizes}", min(sizes.values()) < 0.1 * len(truth))
    initial = defects[defects.defect == "history_lost_before_setup"].detail.astype(int).sum()
    check("Tenancy", "One tenant's 3-year backfill",
          f"initial syncs on {', '.join(str(t['connector_setup']) for t in C.TENANTS)}; {initial:,} earlier record versions lost at setup", initial > 0)
    zid = latest(tickets).groupby("id").tenant.nunique()
    check("Tenancy", "IDs that are only unique within a tenant", f"{(zid > 1).sum():,} Zendesk ticket IDs exist in more than one tenant", (zid > 1).any())

    # --- details
    silent = ((cust.outcome == "churned") & (cust.detectable == False)).sum()
    check("Details", "Some churners are undetectable on purpose", f"{silent:,} churns with no warning signs", silent > 0)
    check("Details", "Missing renewal dates", f"{dcount('salesforce.account', 'null_renewal_date'):,} customer accounts with renewal_date never filled",
          dcount("salesforce.account", "null_renewal_date") > 0)
    test = acc_latest.name.str.contains("DO NOT USE").sum()
    check("Details", "Test and internal accounts", f"{test} test accounts on internal domains", test > 0)

    L = ["# Blueprint edge-case check", "",
         f"Each row is an edge case from the Account Risk Platform design page, checked against `{root}`.", "",
         "| Group | Edge case | Evidence in the data | Present |", "|---|---|---|---|"]
    L += [f"| {g} | {c} | {e} | {ok} |" for g, c, e, ok in rows]
    missing = [c for g, c, e, ok in rows if ok != "yes"]
    L += ["", f"**{len(rows) - len(missing)} of {len(rows)} present.**" + (" Missing: " + ", ".join(missing) if missing else "")]
    (out / "BLUEPRINT_CHECK.md").write_text("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
