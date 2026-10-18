# Synthetic CS dataset - review sample

- Scale **1.0** of full size, seed **42**, window **2023-10-15 → 2026-10-14**, dump taken 2026-10-14 + 1 day
- **5000** accounts, **218,218** event rows (target 200,000), generated in 17.4s
- Lake: `lake/s3/cs-risk-raw`

## Tables

| Table | Kind | Rows | Files | From initial sync | Columns |
|---|---|---:|---:|---:|---|
| `gmail.message` | event | 28,666 | 152 | 133 | _fivetran_deleted, _fivetran_synced, bounce, cc_count, direction, from_domain, has_reply, label_ids, mailbox, message_id, sent_at, subject, thread_id, to_domains |
| `product.event` | event | 81,980 | 152 | 342 | _fivetran_deleted, _fivetran_synced, event_id, event_name, event_time, properties_json, user_hash, workspace_id |
| `product.workspace` | reference | 7,933 | 151 | 2,544 | _fivetran_deleted, _fivetran_synced, created_at, id, name, plan, seats_purchased, sfdc_account_id, status, updated_at |
| `salesforce.account` | reference | 17,576 | 152 | 2,627 | _fivetran_deleted, _fivetran_synced, arr, billing_country, contract_start_date, created_date, currency_iso_code, employee_band, id, industry, is_deleted, last_modified_date, master_record_id, name, owner_id, parent_id, renewal_date, tier, type, website |
| `salesforce.contact` | reference | 24,661 | 152 | 13,627 | _fivetran_deleted, _fivetran_synced, account_id, contact_role, created_date, email, email_bounced, first_name, id, inactive_date, is_champion, last_modified_date, last_name, title |
| `salesforce.opportunity` | event | 37,793 | 152 | 620 | _fivetran_deleted, _fivetran_synced, account_id, amount, close_date, closed_lost_reason, created_date, currency_iso_code, id, is_closed, is_won, last_modified_date, name, owner_id, probability, stage_name, type |
| `salesforce.task` | event | 2,110 | 148 | 6 | _fivetran_deleted, _fivetran_synced, account_id, activity_date, created_date, id, owner_id, status, subject, type, who_id |
| `salesforce.user` | reference | 80 | 15 | 68 | _fivetran_deleted, _fivetran_synced, created_date, email, id, is_active, last_modified_date, name, time_zone, user_role |
| `stripe.charge` | event | 14,688 | 148 | 2 | _fivetran_deleted, _fivetran_synced, amount, created, currency, customer_id, failure_code, id, invoice_id, paid, status |
| `stripe.customer` | reference | 4,158 | 143 | 2,447 | _fivetran_deleted, _fivetran_synced, created, currency, delinquent, email, id, metadata_sfdc_account_id, name |
| `stripe.invoice` | event | 16,043 | 150 | 4 | _fivetran_deleted, _fivetran_synced, amount_due, amount_paid, attempt_count, billing_reason, created, currency, customer_id, id, period_start, status, subscription_id |
| `stripe.subscription` | reference | 6,745 | 148 | 2,447 | _fivetran_deleted, _fivetran_synced, cancel_at, canceled_at, created, currency, customer_id, id, interval, plan_id, quantity, status, unit_amount, updated |
| `zendesk.organization` | reference | 3,995 | 146 | 2,273 | _fivetran_deleted, _fivetran_synced, created_at, domain_names, external_id, id, name, updated_at |
| `zendesk.ticket` | event | 23,811 | 152 | 36 | _fivetran_deleted, _fivetran_synced, assignee_id, created_at, custom_churn_risk_flag, id, organization_id, priority, requester_email, satisfaction_rating, status, subject, tags, type, updated_at, via_channel |
| `zendesk.ticket_comment` | event | 13,127 | 152 | 62 | _fivetran_deleted, _fivetran_synced, author_email, author_role, body, created_at, id, public, ticket_id |

## Accounts by tenant

| Tenant | Accounts | Customers | Prospects | Test |
|---|---:|---:|---:|---:|
| brightpath | 800 | 656 | 144 | 5 |
| helio | 1500 | 1230 | 270 | 8 |
| northwind | 2400 | 1968 | 432 | 12 |
| quarry | 300 | 246 | 54 | 0 |

## Customer archetypes and outcomes (hidden truth)

| Archetype | Accounts | Outcomes |
|---|---:|---|
| champion_loss | 245 | churned 113, at_risk 66, recovered 36, recovering 30 |
| dormant | 367 | renewed 213, churned 112, at_risk 42 |
| expanding | 407 | renewed 407 |
| healthy | 1655 | renewed 1655 |
| noisy_loyal | 204 | renewed 204 |
| payment_failure | 163 | churned 108, recovered 55 |
| seasonal | 285 | renewed 285 |
| silent_churn | 122 | churned 93, at_risk 29 |
| slow_decline | 407 | at_risk 197, churned 134, downsold 76 |
| support_crisis | 245 | churned 79, recovered 78, recovering 50, at_risk 38 |

- Churned inside the window: **639** of 4100 customers (15.6%); involuntary 108, undetectable 93
- Still active but heading for churn/downsell after the window (`at_risk`): **372**
- Downsold: 76, recovered after a risk episode: 169

## Pre-sales

| Outcome | Accounts | With trial | Avg trial engagement |
|---|---:|---:|---:|
| lost | 488 | 221 | 0.48 |
| nurture | 175 | 0 | - |
| open | 237 | 142 | 0.52 |
| won | 1640 | 1000 | 0.71 |

Lost reasons: Price 118, Competitor 114, No Decision 108, Missing Feature 90, Timing / Budget 58

## Ticket text

- 13,140 comments: template 10604, llm 2536
- Sentiment: neutral 8590, positive 3119, negative 1431
- Top topics: how_to 3564, feature_request 2023, bug 1675, integration 1239, praise 932, renewal_pricing 781, billing 729, sso 654, performance 502, onboarding 354

## Injected defects (from the defect log)

| Table | Defect | Count |
|---|---|---:|
| `gmail.message` | duplicate | 143 |
| `gmail.message` | feed_outage_delayed | 1 |
| `gmail.message` | late | 1123 |
| `gmail.message` | not_yet_arrived | 27 |
| `gmail.message` | very_late | 138 |
| `product.event` | clock_skew | 152 |
| `product.event` | duplicate | 1234 |
| `product.event` | feed_outage_lost | 1 |
| `product.event` | late | 3255 |
| `product.event` | not_yet_arrived | 99 |
| `product.event` | very_late | 397 |
| `product.workspace` | late | 241 |
| `product.workspace` | missing_account_link | 203 |
| `product.workspace` | not_yet_arrived | 16 |
| `product.workspace` | versions_collapsed_between_syncs | 1 |
| `product.workspace` | very_late | 23 |
| `salesforce.account` | duplicate_account | 154 |
| `salesforce.account` | history_lost_before_setup | 4 |
| `salesforce.account` | late | 591 |
| `salesforce.account` | not_yet_arrived | 10 |
| `salesforce.account` | null_arr | 134 |
| `salesforce.account` | null_industry | 606 |
| `salesforce.account` | null_renewal_date | 154 |
| `salesforce.account` | very_late | 70 |
| `salesforce.contact` | late | 421 |
| `salesforce.contact` | not_yet_arrived | 11 |
| `salesforce.contact` | personal_email_domain | 144 |
| `salesforce.contact` | very_late | 61 |
| `salesforce.opportunity` | history_lost_before_setup | 4 |
| `salesforce.opportunity` | late | 1425 |
| `salesforce.opportunity` | not_yet_arrived | 36 |
| `salesforce.opportunity` | very_late | 195 |
| `salesforce.task` | late | 89 |
| `salesforce.task` | legacy_date_format | 1 |
| `salesforce.task` | not_yet_arrived | 3 |
| `salesforce.task` | very_late | 9 |
| `salesforce.user` | late | 2 |
| `stripe.charge` | feed_outage_delayed | 1 |
| `stripe.charge` | late | 630 |
| `stripe.charge` | not_yet_arrived | 38 |
| `stripe.charge` | very_late | 73 |
| `stripe.customer` | duplicate_customer | 83 |
| `stripe.customer` | late | 75 |
| `stripe.customer` | missing_sfdc_id | 211 |
| `stripe.customer` | stale_sfdc_id | 5 |
| `stripe.customer` | very_late | 12 |
| `stripe.invoice` | feed_outage_delayed | 1 |
| `stripe.invoice` | history_lost_before_setup | 1 |
| `stripe.invoice` | late | 643 |
| `stripe.invoice` | not_yet_arrived | 41 |
| `stripe.invoice` | versions_collapsed_between_syncs | 4 |
| `stripe.invoice` | very_late | 93 |
| `stripe.subscription` | late | 173 |
| `stripe.subscription` | not_yet_arrived | 3 |
| `stripe.subscription` | very_late | 16 |
| `zendesk.organization` | late | 72 |
| `zendesk.organization` | missing_external_id | 1596 |
| `zendesk.organization` | no_zendesk_org | 272 |
| `zendesk.organization` | stale_external_id | 32 |
| `zendesk.organization` | very_late | 8 |
| `zendesk.ticket` | feed_outage_delayed | 1 |
| `zendesk.ticket` | history_lost_before_setup | 4 |
| `zendesk.ticket` | late | 966 |
| `zendesk.ticket` | not_yet_arrived | 25 |
| `zendesk.ticket` | soft_deleted | 47 |
| `zendesk.ticket` | versions_collapsed_between_syncs | 4 |
| `zendesk.ticket` | very_late | 115 |
| `zendesk.ticket_comment` | feed_outage_delayed | 1 |
| `zendesk.ticket_comment` | late | 512 |
| `zendesk.ticket_comment` | not_yet_arrived | 13 |
| `zendesk.ticket_comment` | prompt_injection | 19 |
| `zendesk.ticket_comment` | very_late | 64 |

Rates are measured on the output, so they differ slightly from the configured values at this scale.

## Sample rows

### `gmail.message`

- **tenant=northwind**
  - `message_id`: <nICF8NMNitKTO456hRsx@mail.gmail.com>
  - `thread_id`: t_be6JbZ4DyvznFseO
  - `mailbox`: emeka.kowalski@northwind-analytics.io
  - `direction`: outbound
  - `from_domain`: northwind-analytics.io
  - `to_domains`: ['kestrelsoftware.nl']
  - `cc_count`: 0
  - `sent_at`: Mon, 23 Oct 2023 14:54:13 -0500
  - `subject`: Renewal for 2026
  - `has_reply`: False
  - `bounce`: False
  - `label_ids`: ['SENT']
  - `_fivetran_synced`: 2023-10-24 00:12:20+00:00
  - `_fivetran_deleted`: False
- **tenant=northwind**
  - `message_id`: <PYeXSLl4RElPxTchThJu@mail.gmail.com>
  - `thread_id`: t_qNjqCMbrUpSchYUR
  - `mailbox`: hana.jensen@northwind-analytics.io
  - `direction`: outbound
  - `from_domain`: northwind-analytics.io
  - `to_domains`: ['willowanalytics.co.uk']
  - `cc_count`: 0
  - `sent_at`: Thu, 16 Nov 2023 10:21:41 -0500
  - `subject`: Quick question
  - `has_reply`: True
  - `bounce`: False
  - `label_ids`: ['SENT']
  - `_fivetran_synced`: 2023-11-16 18:22:20+00:00
  - `_fivetran_deleted`: False

### `product.event`

- **tenant=quarry**
  - `event_id`: e_3WNfp9oFifoKQwwsURrX
  - `workspace_id`: ws_e751ee2132
  - `user_hash`: 7f8c149ddb43
  - `event_name`: login_session
  - `event_time`: 2023-10-24 11:50:46.462921+00:00
  - `properties_json`: {"duration_s": 243, "client": "web"}
  - `_fivetran_synced`: 2023-10-24 12:31:59+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `event_id`: e_iZzGhLjb6kQgbzuDLKIL
  - `workspace_id`: ws_524a51c645
  - `user_hash`: a24c46617263
  - `event_name`: report_created
  - `event_time`: 2023-11-17 10:21:06.789641+00:00
  - `properties_json`: {}
  - `_fivetran_synced`: 2023-11-17 12:24:50+00:00
  - `_fivetran_deleted`: False

### `product.workspace`

- **tenant=quarry**
  - `id`: ws_db78ec005a
  - `sfdc_account_id`: 001QU000000003FKY
  - `name`: Wayfarer Express GmbH
  - `plan`: mid
  - `seats_purchased`: 60
  - `status`: active
  - `created_at`: 2023-11-18 08:43:57.478264+00:00
  - `updated_at`: 2023-11-18 08:43:57.478264+00:00
  - `_fivetran_synced`: 2023-11-18 12:04:38+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `id`: ws_6fa7cb1f24
  - `sfdc_account_id`: 001QU000000012KF7
  - `name`: Ultramarine Distribution AG - Sandbox
  - `plan`: enterprise
  - `seats_purchased`: 186
  - `status`: active
  - `created_at`: 2021-08-05 16:05:32.260270+00:00
  - `updated_at`: 2024-02-21 06:32:35.547500+00:00
  - `_fivetran_synced`: 2024-02-21 12:09:37+00:00
  - `_fivetran_deleted`: False

### `salesforce.account`

- **tenant=quarry**
  - `id`: 001QU000000009DFZ
  - `name`: Meridian Movers AG
  - `website`: https://www.meridianmovers.de
  - `industry`: None
  - `type`: Customer
  - `owner_id`: 005QU0000000033D0
  - `arr`: 26400.0
  - `currency_iso_code`: EUR
  - `contract_start_date`: 2020-10-18
  - `renewal_date`: 2024-10-18
  - `tier`: mid
  - `employee_band`: 201-1000
  - `billing_country`: DE
  - `created_date`: 2020-05-23
  - `master_record_id`: None
  - `is_deleted`: False
  - `parent_id`: None
  - `last_modified_date`: 2023-10-18 11:43:00.155323+00:00
  - `_fivetran_synced`: 2023-10-18 12:38:16+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `id`: 001QU000000006TSE
  - `name`: Fennel Couriers GmbH
  - `website`: https://www.fennelcouriers.de
  - `industry`: E-commerce
  - `type`: Customer
  - `owner_id`: 005QU0000000033D0
  - `arr`: 18700.0
  - `currency_iso_code`: EUR
  - `contract_start_date`: 2021-11-17
  - `renewal_date`: 2024-11-17
  - `tier`: mid
  - `employee_band`: 201-1000
  - `billing_country`: DE
  - `created_date`: 2021-08-24
  - `master_record_id`: None
  - `is_deleted`: False
  - `parent_id`: None
  - `last_modified_date`: 2023-11-17 07:10:47.471401+00:00
  - `_fivetran_synced`: 2023-11-17 12:24:04+00:00
  - `_fivetran_deleted`: False

### `salesforce.contact`

- **tenant=quarry**
  - `id`: 003QU000000036RYQ
  - `account_id`: 001QU00000000Q6D8
  - `first_name`: Nadia
  - `last_name`: Ueda
  - `email`: nadia.ueda@pellucidmovers.nl
  - `title`: Head of Operations
  - `contact_role`: Champion
  - `is_champion`: True
  - `created_date`: 2023-10-25
  - `inactive_date`: None
  - `email_bounced`: False
  - `last_modified_date`: 2023-10-25 11:03:16.927547+00:00
  - `_fivetran_synced`: 2023-10-25 12:02:27+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `id`: 003QU00000003746O
  - `account_id`: 001QU00000000Q6D8
  - `first_name`: Arjun
  - `last_name`: Larsen
  - `email`: arjun.larsen@pellucidmovers.nl
  - `title`: Account Manager
  - `contact_role`: End User
  - `is_champion`: False
  - `created_date`: 2023-11-09
  - `inactive_date`: None
  - `email_bounced`: False
  - `last_modified_date`: 2023-11-09 16:54:40.164798+00:00
  - `_fivetran_synced`: 2023-11-09 18:23:14+00:00
  - `_fivetran_deleted`: False

### `salesforce.opportunity`

- **tenant=quarry**
  - `id`: 006QU00000000TQON
  - `account_id`: 001QU00000000CXRE
  - `name`: Verdant Fleet Services GmbH & Co. KG - Renewal 2024
  - `type`: Renewal
  - `stage_name`: Renewal Open
  - `amount`: 3700.0
  - `currency_iso_code`: EUR
  - `close_date`: 2024-01-23
  - `probability`: 70
  - `is_closed`: False
  - `is_won`: False
  - `closed_lost_reason`: None
  - `owner_id`: 005QU0000000033D0
  - `created_date`: 2023-10-25
  - `last_modified_date`: 2023-10-25 08:41:05.984551+00:00
  - `_fivetran_synced`: 2023-10-25 12:35:34+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `id`: 006QU00000002VKOK
  - `account_id`: 001QU000000014LQV
  - `name`: Evergreen Haulage - Renewal 2023
  - `type`: Renewal
  - `stage_name`: Negotiation
  - `amount`: 33700.0
  - `currency_iso_code`: EUR
  - `close_date`: 2023-12-14
  - `probability`: 75
  - `is_closed`: False
  - `is_won`: False
  - `closed_lost_reason`: None
  - `owner_id`: 005QU000000003FKY
  - `created_date`: 2023-09-15
  - `last_modified_date`: 2023-11-14 12:51:04.033322+00:00
  - `_fivetran_synced`: 2023-11-14 18:27:48+00:00
  - `_fivetran_deleted`: False

### `salesforce.task`

- **tenant=northwind**
  - `id`: 00TNW000000020IHN
  - `account_id`: 001NW00000001Z5LV
  - `who_id`: 003NW00000009CYED
  - `owner_id`: 005NW000000006TSE
  - `type`: Meeting
  - `subject`: QBR
  - `status`: Completed
  - `activity_date`: 23/10/2023
  - `created_date`: 2023-10-23 16:05:34.429114+00:00
  - `_fivetran_synced`: 2023-10-23 18:23:53+00:00
  - `_fivetran_deleted`: False
- **tenant=northwind**
  - `id`: 00TNW00000004V14V
  - `account_id`: 001NW0000000BDLMH
  - `who_id`: 003NW0000001HPYL0
  - `owner_id`: 005NW000000005GWM
  - `type`: Call
  - `subject`: Executive sponsor sync
  - `status`: Completed
  - `activity_date`: 20/11/2023
  - `created_date`: 2023-11-20 21:31:43.195278+00:00
  - `_fivetran_synced`: 2023-11-21 00:07:53+00:00
  - `_fivetran_deleted`: False

### `salesforce.user`


### `stripe.charge`

- **tenant=quarry**
  - `id`: ch_juIkGw2cUdn1zi
  - `invoice_id`: in_dCkQwZSSXBY5Sa
  - `customer_id`: cus_XQwDk4GNALBoXb
  - `amount`: 25000
  - `currency`: eur
  - `status`: succeeded
  - `failure_code`: None
  - `paid`: True
  - `created`: 2023-10-19 06:23:31.790299+00:00
  - `_fivetran_synced`: 2023-10-19 12:15:09+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `id`: ch_dbH8nRZ2owKQ4X
  - `invoice_id`: in_IQp5Cer4uDdRgf
  - `customer_id`: cus_XQwDk4GNALBoXb
  - `amount`: 25000
  - `currency`: eur
  - `status`: succeeded
  - `failure_code`: None
  - `paid`: True
  - `created`: 2023-11-19 00:57:35.836992+00:00
  - `_fivetran_synced`: 2023-11-19 06:28:11+00:00
  - `_fivetran_deleted`: False

### `stripe.customer`

- **tenant=quarry**
  - `id`: cus_PUiCyPt9hnJHTA
  - `email`: yara.haddad@nettlesupply.pl
  - `name`: Nettle Supply Co, Inc.
  - `metadata_sfdc_account_id`: 001QU00000000MM1T
  - `currency`: eur
  - `created`: 2023-11-20 07:08:53.834655+00:00
  - `delinquent`: False
  - `_fivetran_synced`: 2023-11-20 12:18:59+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `id`: cus_YpHq1mZHYFJetW
  - `email`: yusuf.murphy@quilltransport.de
  - `name`: QuillTransport
  - `metadata_sfdc_account_id`: 001QU00000000T28R
  - `currency`: eur
  - `created`: 2024-03-21 11:22:30.881205+00:00
  - `delinquent`: False
  - `_fivetran_synced`: 2024-03-21 12:34:25+00:00
  - `_fivetran_deleted`: False

### `stripe.invoice`

- **tenant=quarry**
  - `id`: in_dCkQwZSSXBY5Sa
  - `customer_id`: cus_XQwDk4GNALBoXb
  - `subscription_id`: sub_TGYqwWVIbWQ5Oh
  - `billing_reason`: subscription_cycle
  - `amount_due`: 25000
  - `currency`: eur
  - `period_start`: 2023-10-19
  - `created`: 2023-10-19 05:12:31.790299+00:00
  - `status`: paid
  - `amount_paid`: 25000
  - `attempt_count`: 1
  - `_fivetran_synced`: 2023-10-19 12:04:19+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `id`: in_IQp5Cer4uDdRgf
  - `customer_id`: cus_XQwDk4GNALBoXb
  - `subscription_id`: sub_TGYqwWVIbWQ5Oh
  - `billing_reason`: subscription_cycle
  - `amount_due`: 25000
  - `currency`: eur
  - `period_start`: 2023-11-19
  - `created`: 2023-11-18 23:30:35.836992+00:00
  - `status`: open
  - `amount_paid`: 0
  - `attempt_count`: 0
  - `_fivetran_synced`: 2023-11-19 00:36:44+00:00
  - `_fivetran_deleted`: False

### `stripe.subscription`

- **tenant=quarry**
  - `id`: sub_j5ymjhyaf8FTq7
  - `customer_id`: cus_PUiCyPt9hnJHTA
  - `plan_id`: mid_yearly
  - `interval`: year
  - `quantity`: 118
  - `unit_amount`: 28729
  - `currency`: eur
  - `status`: active
  - `cancel_at`: None
  - `canceled_at`: None
  - `created`: 2023-11-20 07:08:53.834655+00:00
  - `updated`: 2023-11-20 07:08:53.834655+00:00
  - `_fivetran_synced`: 2023-11-20 12:13:33+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `id`: sub_edgFIEPVp6PYk2
  - `customer_id`: cus_YpHq1mZHYFJetW
  - `plan_id`: mid_yearly
  - `interval`: year
  - `quantity`: 50
  - `unit_amount`: 42000
  - `currency`: eur
  - `status`: active
  - `cancel_at`: None
  - `canceled_at`: None
  - `created`: 2024-03-21 11:22:30.881205+00:00
  - `updated`: 2024-03-21 11:22:30.881205+00:00
  - `_fivetran_synced`: 2024-03-21 12:13:28+00:00
  - `_fivetran_deleted`: False

### `zendesk.organization`

- **tenant=quarry**
  - `id`: 4500
  - `name`: Nettle Supply Co
  - `domain_names`: ['nettlesupply.pl']
  - `external_id`: None
  - `created_at`: 2023-11-20 10:42:46.260530+00:00
  - `updated_at`: 2023-11-20 10:42:46.260530+00:00
  - `_fivetran_synced`: 2023-11-20 12:20:45+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `id`: 4496
  - `name`: Foxglove Express, Inc.
  - `domain_names`: ['foxgloveexpress.de']
  - `external_id`: 001QU00000000LRHY
  - `created_at`: 2024-03-17 12:59:57.047398+00:00
  - `updated_at`: 2024-03-17 12:59:57.047398+00:00
  - `_fivetran_synced`: 2024-03-17 18:35:22+00:00
  - `_fivetran_deleted`: False

### `zendesk.ticket`

- **tenant=quarry**
  - `id`: 80104
  - `organization_id`: 4456
  - `requester_email`: laura.quinn@larkspurdistribution.at
  - `assignee_id`: 360000004
  - `subject`: Would love to see this in ETA notifications
  - `type`: task
  - `priority`: low
  - `tags`: ['feature_request']
  - `via_channel`: web
  - `created_at`: 2023-11-22 06:35:51.759935+00:00
  - `status`: new
  - `satisfaction_rating`: None
  - `updated_at`: 2023-11-22 06:35:51.759935+00:00
  - `_fivetran_synced`: 2023-11-22 12:01:44+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `id`: 80106
  - `organization_id`: 4459.0
  - `requester_email`: sofia.keller@copperleaftransport.de
  - `assignee_id`: 360000008
  - `subject`: driver app shows wrong numbers
  - `type`: problem
  - `priority`: high
  - `tags`: ['bug']
  - `via_channel`: chat
  - `created_at`: 2023-12-12 13:30:02.049640+00:00
  - `status`: closed
  - `satisfaction_rating`: None
  - `updated_at`: 2023-12-18 06:41:13.042679+00:00
  - `_fivetran_synced`: 2023-12-18 12:11:12+00:00
  - `_fivetran_deleted`: False

### `zendesk.ticket_comment`

- **tenant=quarry**
  - `id`: 9100193
  - `ticket_id`: 80103
  - `author_role`: end-user
  - `author_email`: arjun.quinn@larkspurdistribution.at
  - `public`: True
  - `body`: Team, It would help a lot if ETA notifications supported custom fields. Not happy with this. Arjun
  - `created_at`: 2023-11-19 09:28:53.898141+00:00
  - `_fivetran_synced`: 2023-11-19 12:32:50+00:00
  - `_fivetran_deleted`: False
- **tenant=quarry**
  - `id`: 9100462
  - `ticket_id`: 80248
  - `author_role`: end-user
  - `author_email`: julia.gallagher@saffronsupply.pl
  - `public`: True
  - `body`: That did not fix it. We've now lost two days on this.
  - `created_at`: 2023-12-15 05:54:33.267945+00:00
  - `_fivetran_synced`: 2023-12-15 06:11:44+00:00
  - `_fivetran_deleted`: False
