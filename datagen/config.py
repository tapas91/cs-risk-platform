"""Generator configuration. Every rate that shapes the data lives here so a run is fully described
by (config, seed, scale). The values are copied into _ground_truth/config_used.json on every run."""
from datetime import date

SEED = 42
WINDOW_START = date(2023, 10, 15)
WINDOW_END = date(2026, 10, 14)

# Full-scale targets. --scale multiplies them (0.10 = the review sample).
FULL_ACCOUNTS = 5000
FULL_EVENTS = 200_000
# Poisson-driven streams are normalised to these targets; ticket comments follow from tickets (1-3 each),
# structural streams (invoices, charges, opportunity versions) fall out of the simulation, and product
# events take the remainder.
STREAM_TARGETS = {
    "zendesk.ticket": 7_000,
    "gmail.message_outbound": 11_000,   # replies are added on top of this
    "salesforce.task": 1_500,
}
PRODUCT_MIN_SHARE = 0.40  # product events never fall below this share of the event budget

# Customer organisations using the CS platform. `accounts` are their customers.
# connector_setup: when Fivetran started syncing. All four go live at the window start, so syncs cover
# the full three years; the initial sync carries only the pre-window state (contracts signed since 2021).
TENANTS = [
    dict(key="northwind", code="NW", name="Northwind Analytics", product="Northwind Insights",
         domain="northwind-analytics.io", share=0.48, csms=20, aes=10, tz="-05:00",
         currencies={"USD": 0.85, "EUR": 0.15}, monthly_share=0.02, seasonality="standard",
         connector_setup=WINDOW_START,
         features=["dashboards", "scheduled reports", "the SQL editor", "data alerts", "embedded charts"],
         integrations=["Snowflake", "BigQuery", "Salesforce", "Slack", "HubSpot"]),
    dict(key="helio", code="HE", name="Helio HR", product="Helio People",
         domain="heliohr.co.uk", share=0.30, csms=12, aes=6, tz="+00:00",
         currencies={"GBP": 0.60, "EUR": 0.30, "USD": 0.10}, monthly_share=0.07, seasonality="standard",
         connector_setup=WINDOW_START,
         features=["payroll exports", "leave management", "performance reviews", "onboarding checklists", "org charts"],
         integrations=["Xero", "Okta", "Slack", "Microsoft Teams", "Workday"]),
    dict(key="brightpath", code="BP", name="Brightpath Learning", product="Brightpath Classroom",
         domain="brightpath.education", share=0.16, csms=7, aes=4, tz="+05:30",
         currencies={"USD": 0.70, "GBP": 0.30}, monthly_share=0.02, seasonality="academic",
         connector_setup=WINDOW_START,
         features=["gradebook", "assignment builder", "parent portal", "attendance tracking", "course templates"],
         integrations=["Google Classroom", "Canvas", "Clever", "Microsoft Teams", "Zoom"]),
    dict(key="quarry", code="QU", name="Quarry Logistics", product="Quarry Dispatch",
         domain="quarrylogistics.de", share=0.06, csms=3, aes=2, tz="+01:00",
         currencies={"EUR": 0.80, "USD": 0.20}, monthly_share=0.03, seasonality="standard",
         connector_setup=WINDOW_START,
         features=["route planning", "driver app", "proof of delivery", "load board", "ETA notifications"],
         integrations=["SAP", "Samsara", "Geotab", "Slack", "Shopify"]),
]

# Share of accounts that only ever appear as pre-sales prospects (never sign).
PROSPECT_SHARE = 0.18
PROSPECT_OUTCOMES = {"lost": 0.55, "open": 0.25, "nurture": 0.20}
LOST_REASONS = {"Price": 0.30, "Competitor": 0.25, "No Decision": 0.20,
                "Missing Feature": 0.15, "Timing / Budget": 0.10}
# Customers whose contract started inside the window have their pre-sales history in the data.
CUSTOMER_ACQUIRED_IN_WINDOW = 0.40

# Customer archetypes: the hidden state that drives every event.
ARCHETYPES = {
    "healthy":         0.40,
    "expanding":       0.10,
    "seasonal":        0.07,
    "noisy_loyal":     0.05,
    "slow_decline":    0.10,
    "champion_loss":   0.06,
    "support_crisis":  0.06,
    "payment_failure": 0.04,
    "silent_churn":    0.03,
    "dormant":         0.09,
}

TIERS = {"enterprise": 0.15, "mid": 0.40, "smb": 0.45}
SEATS = {"enterprise": (80, 600), "mid": (15, 120), "smb": (2, 20)}
PRICE_PER_SEAT_YEAR = {"enterprise": 420, "mid": 360, "smb": 300}

# Mess. Each defect is logged to _ground_truth/defect_log.parquet with the affected key.
DEFECTS = {
    "late_arrival_rate": 0.04,          # synced 1-30 days after the event (after connector setup)
    "very_late_rate": 0.005,            # synced 60-120 days after the event
    "duplicate_rate_product": 0.015,    # retried deliveries, same event_id
    "duplicate_rate_gmail": 0.005,
    "clock_skew_rate": 0.002,           # product event_time ahead of real time by 1-48h
    "soft_delete_rate_ticket": 0.005,   # spam tickets deleted after sync
    "sfdc_duplicate_account_rate": 0.03,
    "stripe_missing_sfdc_id": 0.06,
    "stripe_stale_sfdc_id": 0.02,       # points at a merged (deleted) duplicate
    "stripe_duplicate_customer": 0.02,
    "workspace_missing_account": 0.05,
    "trial_workspace_missing_account": 0.60,
    "zendesk_org_external_id_missing": 0.40,
    "zendesk_org_coverage": 0.92,
    "personal_email_domain_accounts": 0.03,
    "test_account_rate": 0.005,
    "null_arr": 0.03,
    "null_renewal_date": 0.04,
    "null_industry": 0.15,
    "csm_departure_rate": 0.15,
}

# Connector outages. "delayed": nothing syncs during the window, then the backlog lands at the end.
# "lost": events produced during the window never reach the lake (tracking was broken at source).
FEED_OUTAGES = [
    dict(tenant="helio", table="zendesk.ticket", start=date(2025, 11, 3), end=date(2025, 11, 24), kind="delayed"),
    dict(tenant="helio", table="zendesk.ticket_comment", start=date(2025, 11, 3), end=date(2025, 11, 24), kind="delayed"),
    dict(tenant="northwind", table="product.event", start=date(2026, 3, 9), end=date(2026, 3, 14), kind="lost"),
    dict(tenant="brightpath", table="gmail.message", start=date(2026, 5, 18), end=date(2026, 6, 8), kind="delayed"),
    # still broken when the data is dumped: nothing after 21 Sep has arrived
    dict(tenant="quarry", table="stripe.invoice", start=date(2026, 9, 21), end=date(2026, 11, 30), kind="delayed"),
    dict(tenant="quarry", table="stripe.charge", start=date(2026, 9, 21), end=date(2026, 11, 30), kind="delayed"),
]
CROSS_TENANT_COMPANY_RATE = 0.006   # same real company is a customer of two tenants
PARENT_CHILD_RATE = 0.04            # enterprise/mid accounts that are subsidiaries of another account
PROMPT_INJECTION_RATE = 0.002       # customer comments carrying instructions aimed at an AI system
INTERVENTION_RATE = {"recovered": 0.8, "churned": 0.3, "at_risk": 0.2}  # CSM save plays on risk accounts

PRODUCT_RENAME_DATE = date(2024, 7, 1)        # event names move to dotted form
ZENDESK_CUSTOM_FIELD_DATE = date(2025, 2, 1)  # churn_risk_flag column appears
LLM_TEXT_SHARE = 0.35                          # share of ticket comments drawn from the LLM-written corpus
