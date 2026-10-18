# Blueprint edge-case check

Each row is an edge case from the Account Risk Platform design page, checked against `lake/s3/cs-risk-raw`.

| Group | Edge case | Evidence in the data | Present |
|---|---|---|---|
| Data arrival | A ticket from three weeks ago arrives today | 728 ticket versions synced 14+ days after the change; max lag 120 days | yes |
| Data arrival | Webhook retries deliver the same event twice | 1,226 repeated product event_ids | yes |
| Data arrival | Event names changed over three years | 16,778 old-style names (`report_created`), 65,202 new-style (`report.create`) after 2024-07-01 | yes |
| Data arrival | A feed stops silently | helio zendesk.ticket (delayed, 2025-11-03..2025-11-24 rows=171); helio zendesk.ticket_comment (delayed, 2025-11-03..2025-11-24 rows=86); brightpath gmail.message (delayed, 2026-05-18..2026-06-08 rows=117); quarry stripe.invoice (delayed, 2026-09-21..2026-11-30 rows=25); quarry stripe.charge (delayed, 2026-09-21..2026-11-30 rows=22); northwind product.event (lost, 2026-03-09..2026-03-14 rows=228) | yes |
| Data arrival | Timestamps in mixed timezones | 5 UTC offsets in Gmail Date headers; SFDC dates have no timezone; Zendesk/Stripe/product in UTC | yes |
| Account identity | Stripe customer with no Salesforce ID | 294 of 4,158 Stripe customers | yes |
| Account identity | Shared domains like gmail.com | 480 contacts on personal mailboxes | yes |
| Account identity | Several workspaces, parent and child accounts, mergers | 124 accounts with 2+ workspaces; 102 child accounts with parent_id; 120 merged duplicates | yes |
| Account identity | The same real company is a customer of two tenants | 31 companies appear in two tenants with the same name and domain | yes |
| Account identity | Records with no link back to the account | 422 workspaces without sfdc_account_id; 1,596 Zendesk orgs without external_id | yes |
| Modeling | Accounts with almost no data | 36% of customers have <5 product events in 3 years; 11% have none | yes |
| Modeling | Features that leak the outcome | 11 cancellation tickets from accounts that later churned; 530 Stripe subscriptions with cancel_at set before cancellation; renewal opps carry closed_lost_reason | yes |
| Modeling | Accounts younger than 90 days | 84 customers signed in the last 90 days of the window | yes |
| Modeling | Churn is roughly 10% of accounts | 15.6% of customers churned inside the window; 372 more at risk after it | yes |
| Modeling | High ticket volume is ambiguous | median tickets: noisy-but-loyal 5 (all renew) vs churned 2 | yes |
| Modeling | A CSM saves a flagged account | 294 save-plan tasks in SFDC; interventions by outcome {'recovered': 137, 'churned': 98, 'at_risk': 64} | yes |
| Agent and automation | An account flips between yellow and red every week | 170 accounts cross a 0.5 health line 4+ times | yes |
| Agent and automation | Open escalation or mid-negotiation | 428 renewals in Negotiation at dump time; 0 open escalation tickets | yes |
| Agent and automation | Ticket text says 'ignore previous instructions' | 19 customer comments carry instructions aimed at an AI | yes |
| Agent and automation | A CSM with too many accounts, or no owner | 37 customer accounts with no owner; largest book 102 accounts, median 81 | yes |
| Agent and automation | The risk is a failed payment | 986 failed charges; 108 involuntary churns | yes |
| Tenancy | A tenant too small for its own model | accounts per tenant {'brightpath': 800, 'helio': 1500, 'northwind': 2400, 'quarry': 300} | yes |
| Tenancy | One tenant's 3-year backfill | initial syncs on 2023-10-15, 2023-10-15, 2023-10-15, 2023-10-15; 2,718 earlier record versions lost at setup | yes |
| Tenancy | IDs that are only unique within a tenant | 2,136 Zendesk ticket IDs exist in more than one tenant | yes |
| Details | Some churners are undetectable on purpose | 93 churns with no warning signs | yes |
| Details | Missing renewal dates | 154 customer accounts with renewal_date never filled | yes |
| Details | Test and internal accounts | 25 test accounts on internal domains | yes |

**27 of 27 present.**