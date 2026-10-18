# Risk model report

Production model **risk-20261018T082010**. promoted: PR-AUC 0.2938 vs rules 0.0392, production 0.285.

Training rows 43,728, validation 12,601, test 22,992 (test = monthly snapshots from 2026-01 to 2026-07); 150 boosting rounds.

## 1. Test window: model vs baselines

Positive = the account churned or downsized within 90 days, as recorded in Salesforce/Stripe.

| Model | PR-AUC | ROC-AUC | Brier | Precision of each CSM's top 10 | Share of outcomes in a top-10 list |
|---|---:|---:|---:|---:|---:|
| LightGBM (production) | 0.294 | 0.899 | 0.022 | 14.3% | 71.4% |
| Logistic regression | 0.221 | 0.840 | 0.151 | 12.5% | 62.0% |
| Hand-written rules | 0.039 | 0.568 | 0.053 | 7.0% | 34.6% |

Base rate 2.8%: a random top 10 would contain 0.3 real outcomes; the model's contains 1.4.

### Calibration (test window)

| Predicted band | Accounts | Mean predicted | Observed rate |
|---|---:|---:|---:|
| (-0.001, 0.02] | 16,931 | 0.4% | 0.3% |
| (0.02, 0.05] | 2,022 | 3.0% | 4.1% |
| (0.05, 0.1] | 2,709 | 6.7% | 9.1% |
| (0.1, 0.2] | 1,127 | 12.0% | 12.9% |
| (0.2, 0.35] | 40 | 26.2% | 20.0% |
| (0.35, 1.0] | 163 | 77.7% | 65.0% |

Calibrated per tenant: helio, northwind; others use the pooled curve.

## 2. Real churn in the test window (hidden truth)

Accounts that truly churned between 2026-01-01 and 2026-09-29, and whether they appeared in their CSM's top 10 on a monthly snapshot in the 90 days before churning.

| Why it churned (generator archetype) | Churned | On the list: model | Median warning (days) | On the list: rules |
|---|---:|---:|---:|---:|
| slow_decline | 60 | 51 (85%) | 66 | 24 (40%) |
| champion_loss | 49 | 49 (100%) | 71 | 48 (98%) |
| dormant | 44 | 42 (95%) | 70 | 12 (27%) |
| silent_churn | 34 | 21 (62%) | 72 | 12 (35%) |
| support_crisis | 32 | 26 (81%) | 70 | 12 (38%) |
| payment_failure | 31 | 14 (45%) | 66 | 24 (77%) |
| **All** | **250** | **203 (81%)** | | **132 (53%)** |

`silent_churn` accounts leave with no warning signs by design. The model still lists some of them because churn happens at renewal and renewal timing is its strongest input: that is "renewal is close", which a CSM already knows, not foresight. Read the other rows for the model's real early warning.

## 3. Today's list (2026-10-15)

3,330 live customers scored: green 3,103, yellow 194, red 33; 1,038 with too little recent data to judge; 1 with a customer notice.

357 accounts are truly heading for churn or downsell after the data ends. The model warns 90 days ahead, so they are split by when the outcome lands:

| Outcome lands | Accounts | On their CSM's top 10 | Flagged red/yellow | Undetectable by design |
|---|---:|---:|---:|---:|
| within 90 days | 104 | 55 (53%) | 40 (38%) | 10 |
| 91-180 days | 107 | 2 (2%) | 0 (0%) | 14 |
| later | 146 | 17 (12%) | 9 (6%) | 5 |

Outcomes more than 90 days out are outside what the model is built to see; they should rise as renewal nears.

## 4. Does it cry wolf?

Share of each healthy group flagged red or yellow today (no churn coming):

| Group | Accounts | Flagged | On a top-10 list |
|---|---:|---:|---:|
| healthy | 1,580 | 4.6% | 10.8% |
| expanding | 399 | 5.0% | 14.0% |
| seasonal | 279 | 2.5% | 15.1% |
| noisy_loyal | 194 | 9.8% | 14.4% |
| dormant | 207 | 12.6% | 15.9% |

Seasonal and noisy-but-loyal accounts are the traps: they look like churners on one signal (usage dip, ticket volume).

## 5. What the model leans on

Top features by total gain:

1. `days_to_renewal`
2. `active_champions`
3. `arr`
4. `tenure_days`
5. `subscribed_seats`
6. `days_since_last_usage`
7. `active_contacts`
8. `failed_charges_60d`
9. `avg_resolution_hours_90d`
10. `tenant_id`
11. `champions_lost`
12. `days_since_customer_email`

Notices (cancellation requests, scheduled cancellations, agent risk flags) are deliberately not inputs: they are shown to the CSM as known risk. CSM save plays are excluded too, since they react to risk already seen.
