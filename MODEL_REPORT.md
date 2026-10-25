# Risk model report

Production model **risk-20261025T060019**. promoted: PR-AUC 0.2788 vs rules 0.0316, production 0.2291.

Training rows 55,924, validation 4,793, test 9,878 (test = monthly snapshots from 2026-05 to 2026-07); 160 boosting rounds.

## 1. Test window: model vs baselines

Positive = the account churned or downsized within 90 days, as recorded in Salesforce/Stripe.

| Model | PR-AUC | ROC-AUC | Brier | Precision of each CSM's top 10 | Share of outcomes in a top-10 list |
|---|---:|---:|---:|---:|---:|
| LightGBM (production) | 0.279 | 0.903 | 0.019 | 11.5% | 70.7% |
| Logistic regression | 0.180 | 0.851 | 0.155 | 9.7% | 59.5% |
| Hand-written rules | 0.032 | 0.565 | 0.050 | 5.5% | 33.8% |

Base rate 2.2%: a random top 10 would contain 0.2 real outcomes; the model's contains 1.2.

### Calibration (test window)

| Predicted band | Accounts | Mean predicted | Observed rate |
|---|---:|---:|---:|
| (-0.001, 0.02] | 8,266 | 0.4% | 0.4% |
| (0.02, 0.05] | 701 | 3.2% | 6.9% |
| (0.05, 0.1] | 512 | 7.3% | 13.5% |
| (0.1, 0.2] | 294 | 13.6% | 9.9% |
| (0.2, 0.35] | 52 | 24.4% | 11.5% |
| (0.35, 1.0] | 53 | 73.6% | 62.3% |

Calibrated per tenant: none; others use the pooled curve.

## 2. Real churn in the test window (hidden truth)

Accounts that truly churned between 2026-05-01 and 2026-09-29, and whether they appeared in their CSM's top 10 on a monthly snapshot in the 90 days before churning.

| Why it churned (generator archetype) | Churned | On the list: model | Median warning (days) | On the list: rules |
|---|---:|---:|---:|---:|
| slow_decline | 29 | 25 (86%) | 68 | 8 (28%) |
| champion_loss | 26 | 26 (100%) | 70 | 23 (88%) |
| dormant | 23 | 20 (87%) | 72 | 4 (17%) |
| silent_churn | 20 | 13 (65%) | 73 | 7 (35%) |
| payment_failure | 17 | 6 (35%) | 16 | 12 (71%) |
| support_crisis | 10 | 10 (100%) | 75 | 5 (50%) |
| **All** | **125** | **100 (80%)** | | **59 (47%)** |

`silent_churn` accounts leave with no warning signs by design. The model still lists some of them because churn happens at renewal and renewal timing is its strongest input: that is "renewal is close", which a CSM already knows, not foresight. Read the other rows for the model's real early warning.

## 3. Today's list (2026-10-15)

3,330 live customers scored: green 3,127, yellow 168, red 35; 1,038 with too little recent data to judge; 1 with a customer notice.

357 accounts are truly heading for churn or downsell after the data ends. The model warns 90 days ahead, so they are split by when the outcome lands:

| Outcome lands | Accounts | On their CSM's top 10 | Flagged red/yellow | Undetectable by design |
|---|---:|---:|---:|---:|
| within 90 days | 104 | 50 (48%) | 32 (31%) | 10 |
| 91-180 days | 107 | 2 (2%) | 0 (0%) | 14 |
| later | 146 | 16 (11%) | 7 (5%) | 5 |

Outcomes more than 90 days out are outside what the model is built to see; they should rise as renewal nears.

## 4. Does it cry wolf?

Share of each healthy group flagged red or yellow today (no churn coming):

| Group | Accounts | Flagged | On a top-10 list |
|---|---:|---:|---:|
| healthy | 1,580 | 4.1% | 11.6% |
| expanding | 399 | 2.8% | 11.8% |
| seasonal | 279 | 3.6% | 13.6% |
| noisy_loyal | 194 | 8.2% | 14.9% |
| dormant | 207 | 13.0% | 15.9% |

Seasonal and noisy-but-loyal accounts are the traps: they look like churners on one signal (usage dip, ticket volume).

## 5. What the model leans on

Top features by total gain:

1. `days_to_renewal`
2. `active_champions`
3. `arr`
4. `tenure_days`
5. `failed_charges_60d`
6. `days_since_last_usage`
7. `subscribed_seats`
8. `avg_resolution_hours_90d`
9. `active_contacts`
10. `tenant_id`
11. `days_since_csm_activity`
12. `champions_lost`

Notices (cancellation requests, scheduled cancellations, agent risk flags) are deliberately not inputs: they are shown to the CSM as known risk. CSM save plays are excluded too, since they react to risk already seen.
