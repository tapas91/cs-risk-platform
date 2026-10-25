# CS Risk Platform

Synthetic customer-success data for four B2B SaaS tenants, a DuckDB warehouse built by Airflow and
dbt, and a fitted churn-risk model that ranks each CSM's accounts every time new data lands.

```
lake/ --land.py--> landing/ --bronze_ingest--> bronze --silver_build (dbt)--> silver --risk_scoring--> gold features
(generated)        ("bucket")  every 15 min      exact copy   on BRONZE         typed,      on SILVER     -> ml.risk_scores
                                                                                matched,                     ml.risk_reasons
                                                                                history kept  risk_training (monthly) -> train + gate
```

Each DAG triggers the next through Airflow datasets: `bronze_ingest` → `BRONZE` → `silver_build`
→ `SILVER` → `risk_scoring` → `RISK` → `account_agent`, which ends by publishing the dashboard's snapshot.
`risk_training` retrains monthly and only changes which model `risk_scoring` uses, so a failed retrain
never stops scoring. Every warehouse task shares one single-slot pool, because DuckDB allows one writer.

## Run it

```bash
docker compose up -d --build            # Airflow http://localhost:8080 (admin / admin), dashboard http://localhost:8501
python3 scripts/land.py --until 2024-12 # land the first files; the 15-minute schedule picks them up
python3 scripts/land.py --next          # land the next synced month (new and late files)
python3 scripts/land.py --all           # land the rest
docker compose exec airflow-scheduler airflow dags trigger risk_training   # first model; scoring skips until one exists
.venv/bin/python scripts/verify_warehouse.py   # warehouse checks against the lake and ground truth
.venv/bin/python scripts/evaluate_model.py     # model report against ground truth -> MODEL_REPORT.md
```

To skip waiting for the schedule: `docker compose exec airflow-scheduler airflow dags trigger bronze_ingest`.
`risk_scoring` and `risk_training` are created paused: unpause them in the UI or with `airflow dags unpause`.

Query the published copy, not the live warehouse: `duckdb -readonly warehouse/snapshot.duckdb`.
DuckDB lets one process open a file read-write, or several open it read-only, never both at once. Any
session on `warehouse.duckdb`, read-only included (a SQL client, an editor extension, a notebook),
makes the next pipeline task fail to open it until the session closes.

To regenerate the source data: `.venv/bin/python -m datagen.generate --scale 1.0 --out lake` (see [datagen/README.md](datagen/README.md)).

## Layout

| Path | What it is |
|---|---|
| `datagen/` | Synthetic data generator, edge-case checklist (`verify_blueprint.py`) |
| `lake/` | **The full generated dataset**: Fivetran-style Parquet for 5 sources × 4 tenants × 3 years, plus `_ground_truth/` and `REPORT.md` (never read by the pipeline) |
| `dashboard_data/` | Slim snapshot the hosted dashboard reads (`pipeline/snapshot.py --slim`) |
| `landing/` | The "bucket" Airflow reads. `LANDING_URI` can point at `s3://…` instead |
| `pipeline/bronze.py` | File discovery, exactly-once loads, schema-drift handling |
| `dags/` | `bronze_ingest`, `silver_build`, `risk_scoring`, `risk_training`, `account_agent` |
| `pipeline/risk_model.py` | Train, gate and score; runs in its own virtualenv (`ML_PYTHON`) |
| `pipeline/agent.py`, `pipeline/agent_tools.py` | The account agent: triage, Claude tool loop, validator, fallback, outbox |
| `app/` | The CSM dashboard: `dashboard.py` (pages), `data.py` (tenant-scoped queries) |
| `pipeline/snapshot.py` | Publishes the dashboard's read-only snapshot after each agent run |
| `tests/` | Tenant-isolation tests for the dashboard's data layer; unit tests for the agent's validator |
| `models_store/` | One folder per trained model: LightGBM file, calibrator, metadata with metrics |
| `dbt/` | Staging views, silver and ops tables, seeds, tests |
| `warehouse/warehouse.duckdb` | The warehouse: schemas `bronze`, `staging`, `silver`, `ops`, `reference`, `gold`, `ml` |

## Design decisions

- **Micro-batches every 15 minutes rather than streaming.** The source syncs every 6 hours, so
  latency is bounded by Fivetran, not by the pipeline.
- **Exactly-once by file.** `bronze._ingested_files` records each file. Retried or overlapping runs
  skip files already loaded. A batch's rows and manifest entries commit in one transaction.
- **Bronze never changes data.** New columns are added and changed types are widened (for example
  DATE + text becomes text). Each change is logged in `ops.schema_changes`.
- **One DuckDB writer.** Every warehouse task runs in the single-slot `duckdb` pool, so tasks
  queue rather than collide.
- **Silver runs on data, not time.** `silver_build` is triggered by the `BRONZE` dataset. When
  nothing lands, bronze stops at its check and silver does not run.
- **Silver is rebuilt in full.** It takes seconds at this volume. It also keeps late identity
  matches correct: a workspace linked today re-attributes its old events. At larger scale, the event
  facts would go incremental and resolve accounts at read time.
- **Every key starts with `tenant_id`.** Source IDs collide across tenants (2,000+ Zendesk ticket IDs).

## Silver model

| Kind | Tables | Notes |
|---|---|---|
| History | `dim_account_history`, `dim_contact_history`, `dim_opportunity_history`, `dim_subscription_history`, `dim_workspace_history` | `valid_from`/`valid_to` are source time; `known_at` is arrival time. Point-in-time features must filter on both |
| Current | `dim_account` (canonical accounts), `dim_user` | |
| Account master | `account_match_candidates`, `account_xref`, `account_domain` | Every Stripe customer, Zendesk org and workspace mapped to one account in its tenant, with `match_method` and `confidence`. Rules: ID, merged-ID redirect, contact email, company domain, name |
| Events | `fct_product_event`, `fct_ticket`, `fct_ticket_status_change`, `fct_ticket_comment`, `fct_email_message`, `fct_invoice`, `fct_charge`, `fct_opportunity_stage_change`, `fct_activity` | Retries removed (first arrival wins); old/new event names unified; Gmail RFC 2822 dates and legacy `dd/mm/yyyy` task dates parsed; amounts in minor units plus USD |
| Ops | `source_freshness`, `match_precision`, `quarantine_identity`, `quarantine_parsing`, `schema_changes` | Stalled feeds scored per tenant; unmatched records kept and counted, never dropped |

## Account-match confidence

`confidence` on `silver.account_xref` is measured, not assumed:

1. `scripts/label_matches.py` labels a sample: up to 150 matches per (source, rule), plus 100
   quarantined records, written to `dbt/seeds/identity_labels.csv`. Here the generator's ground truth
   stands in for an analyst checking matches by hand.
2. `ops.match_precision` checks every candidate a labeled record produced against its true account.
   A rule's confidence is the **lower bound of the 95% Wilson interval** on its precision once it has
   30+ labels. Before that, it uses the rule's prior from `dbt/seeds/match_rule_priors.csv`.
3. `account_xref` tries rules in **prior order** and only uses rules whose confidence is at least
   0.7. Measured confidence is reported and gates a rule; it doesn't reorder rules. Ranking on it would
   let sample size pick winners whenever rules are equally accurate. Reordering is a deliberate change
   to the priors seed.

`scripts/demo_run.sh` runs the cycle: build with priors, label, rebuild with measured confidence.
Rare errors need large samples: the 4 wrong Zendesk external IDs (0.2%) didn't appear in 150 labels,
and the lower bound of 0.98 still covers the true 0.998.

## Risk model

**What it predicts:** the probability that a live customer churns or downsizes (loses 20%+ of seats)
in the next 90 days. Labels come from what Salesforce and Stripe recorded: a cancelled subscription, a
lost renewal, or a "Former Customer" status. The generator's ground truth is never used for training.
Checked against it, those labels find all 639 real churns, with no false ones.

**Features (`dbt/models/gold/`):** about 45 inputs per account, computed **as of** each date. A row
counts only if it had happened *and* reached the warehouse by that date (`known_at`), so late data never
leaks backwards.
- Usage: trend against the prior 60 days, seat utilisation, export share, failed exports.
- Support: urgent and incident tickets, bad CSAT, resolution time, data-export requests.
- Email: response ratio, bounces, days since the customer last wrote.
- Billing: failed charges, past due, seat trend.
- People: champion lost, active contacts, CSM coverage.
- Context: renewal timing, tenure.

Monthly snapshots train the model; weekly snapshots over the last 13 weeks are scored.

**Deliberately not inputs:**
- **Customer notices** (a cancellation request, a scheduled cancellation, an agent's risk flag). They
  are known risk, not a prediction, so they're shown to the CSM and put at the top of the list.
- **CSM save plays**, because they react to risk the CSM already saw.

**Training (`pipeline/risk_model.py`):**
- LightGBM, compared against logistic regression and a hand-written rules baseline.
- Rolling windows by date, counted back from the newest month with a complete 90-day label: test is
  the last 3 months (now May–July 2026), validation the 3 before, training everything earlier. A
  90-day gap separates each window (a purge gap). The windows move forward each month, so a retrain
  learns from about one more month; the dates each model used are stored with it.
- Accounts that had already given notice are left out of training and evaluation: they are nearly all
  positives, and they're shown to the CSM first anyway.
- Platt calibration (a logistic curve over the model's log-odds), fit on half the validation accounts:
  the half early stopping didn't see. Per tenant where the tenant has 50+ positives in that half, pooled
  otherwise (today: pooled for all).
- **Promotion gate:** a new model replaces production only if it beats the rules baseline and doesn't
  lose more than 0.005 PR-AUC to the current model on the same test window. Every decision is logged
  in `ml.model_registry`.

**Scoring output:**

| Table | Contents |
|---|---|
| `ml.risk_scores` | The current 14 weekly score dates, replaced on every run. Probability, band (red/yellow/green with hysteresis: red needs two weekly scores in a row above 0.25 and holds until below 0.18; the hysteresis walks 26 weeks, so a band doesn't depend on where the shown window starts), status (`scored`, `insufficient_data`, `customer_notice`), priority (risk × ARR in USD × up to 2× near renewal), rank in the CSM's book, `model_version`, `feature_cutoff`, `data_as_of` |
| `ml.risk_reasons` | Top 3 features pushing each score up, with exact TreeSHAP contributions and plain text such as "Champion has left" or "Usage at 34% of its prior level" |
| `ml.score_runs`, `ml.score_log`, `ml.reason_log` | Append-only history of what was shown. Each run logs the latest date's score and reasons for accounts whose shown score changed (new date, model, probability, band, status, rank or notice), so a rerun on unchanged data logs nothing. Agent evidence cites these rows. |

Each CSM's list is ordered by tier (notice, then red, then yellow, then the rest) and by revenue at
risk within each tier.

**Tracing a score:** `ml.risk_scores` → `ml.risk_reasons` (feature, value, contribution) →
`gold.account_features` (the same row, same `as_of`) → silver facts filtered by `known_at <= feature_cutoff`
→ bronze `_source_file`.

**Results** (full detail in `MODEL_REPORT.md`):
- On the test window (accounts with a notice left out): PR-AUC 0.28 against 0.18 for logistic
  regression and 0.03 for the rules, at a 2.2% base rate. A CSM's top 10 holds 1.2 real outcomes,
  against 0.2 at random. 71% of all outcomes appear on some CSM's top-10 list.
- Of accounts that truly churned in the test window, 80% were on their CSM's list in the 90 days
  before, with a median 68–75 days' warning. The rules caught 47%.
- Weakest on payment failures (35%): those happen within weeks, and monthly snapshots are too coarse.
- `days_to_renewal` is its strongest input. Part of the lift is "renewal is close", which a CSM
  already knows.

## Account agent

Runs without anyone starting it: the `account_agent` DAG fires on the `RISK` dataset after every
scoring run. Per run (`pipeline/agent.py`):

1. **Triage (SQL, no model).** From the latest scores it picks accounts that:
   - newly gave notice,
   - newly entered red,
   - rose 10+ points in a week,
   - sit in a CSM's top 3 while flagged, or
   - are dark within 45 days of renewal.

   It skips accounts already handled for that score date, and accounts reviewed in the 7 days before
   it (`AGENT_COOLDOWN_DAYS`) unless they newly gave notice or newly entered red. It caps the run at `AGENT_MAX_CASES`
   (default 12, the cost cap) and 3 per CSM. The leftovers wait for the next run.
2. **Investigate (Claude, `ANTHROPIC_MODEL`, default `claude-opus-5-5`).** Claude uses six read-only
   tools: risk summary, support history, usage, billing, relationship and open work.
   - The tools are **bound in code** to one tenant, account and score date. The model can't name any of
     them, and it only sees data the warehouse had received by the score's cutoff.
   - Every fact gets an evidence ID (E1, E2, ...) recorded in `agent.evidence`, with its source table and key.
   - Customer text arrives wrapped in `<untrusted_customer_text>` tags.
   - Requests use structured JSON output, effort `medium`, prompt caching and server-side
     `fallbacks: "default"` for refusals.
3. **Decide.** Claude returns:
   - a route: `csm_task`, `billing_queue`, `suppress`, `data_quality` or `no_action`,
   - a headline and a two-to-five-sentence brief **in which every sentence cites evidence IDs**,
   - a recommended action and an optional outreach draft, signed as the CSM.
4. **Validate in code.**
   - The route's preconditions must hold. For example, billing requires a failed payment in the
     evidence, and suppression requires an open escalation, a live negotiation or a recent save play.
   - Every citation must exist, and every number in a sentence must appear in a fact it cites.
   - The draft must not use internal terms ("risk", "churn", "score", "model" and the like).
   - On failure, the errors go back to Claude for one retry, then to the fallback.
5. **Fallback.** With no key, a refusal, an API error or a second validation failure, rules choose the
   route and build a template brief from the same evidence. `decided_by` records which path ran.
6. **Act (outbox, idempotent).** It writes `agent.cases`, `agent.evidence`, `agent.tool_calls` and
   `agent.actions`, keyed on tenant, account and score date. It **never changes a score and never
   contacts a customer**: drafts sit at `draft_awaiting_csm_approval`. `agent.runs` logs mode, token
   use and estimated cost.

On demand, through Airflow so the run waits for the warehouse pool instead of racing the pipeline:

```bash
docker compose exec airflow-scheduler airflow dags trigger account_agent --conf '{"account": "<tenant>/<account_id>"}'
```

**Measured:**
- A 12-account run took about 1 minute and cost $0.55 (about $0.05 per account, half the input from cache).
- All 12 briefs passed validation.
- Without an API key, the same run completes in fallback mode.
- In a prompt-injection test, a ticket told the reviewer to mark the account healthy and route it to
  `no_action`. The agent routed it to `csm_task` and noted in the brief that the instruction had been ignored.

**Tracing a brief:**
- `agent.cases.brief` (sentence + evidence IDs) → `agent.evidence` (fact, `source_table`,
  `source_key`) → that silver row, or the `ml.score_log` / `ml.reason_log` row of the scoring run
  it quoted (key `<run_id>/<account>@<as_of>`), which later runs and models never rewrite.
- `ml.risk_scores` and `ml.risk_reasons` → `gold.account_features` → silver → bronze `_source_file`.

**Secrets:** `ANTHROPIC_API_KEY` is injected at runtime from `.env` (git-ignored, mode 600; see
`.env.example`), never baked into the image.

## CSM dashboard

A read-only Streamlit app at **http://localhost:8501** (`dashboard` service, its own small image).

| Page | Who | Shows |
|---|---|---|
| **My accounts** | Everyone | The ranked book: band, risk, change since last week, ARR, renewal, status, the agent's route and headline. Managers can switch CSM or see everyone |
| **Account detail** | Everyone, for accounts they can see | Risk over 13 weeks against the yellow and red lines; TreeSHAP reasons; the agent's brief with evidence IDs; **Trace a fact** (evidence → source rows → the landed bronze files); the outreach draft (copy only); the agent's tool calls; the exact model input row with its cutoff and model version |
| **Team overview** | Managers | Bands per CSM, red accounts the agent hasn't reviewed, revenue at risk, the agent's recent reviews, data freshness per feed, unmatched-record counts |

On every page, a banner names any feed that's stale for the signed-in tenant.

**How it stays safe for multiple organisations:**
- **Tenant-scoped data layer (`app/data.py`).** It's the only code that queries data. Every function takes the
  signed-in viewer and filters on the viewer's `tenant_id`; the tenant never comes from a widget or URL.
- **Visibility.** CSMs see their own book, managers their whole tenant. Anything else raises `NotVisible`.
- **Tests.** `tests/test_tenant_isolation.py` asks for other tenants' accounts and cases, and a colleague's
  accounts, through every function, and expects a refusal. Run them with `docker compose exec dashboard pytest -q tests`.
- **Sign-in.** A demo user picker: the active CSMs and managers of each tenant, from Salesforce users.
  Production would swap in SSO, and only `sign_in()` would change. A new browser session must sign in again.
- **Read-only snapshot.** The app never opens the live warehouse. The `publish_snapshot` task at the end of
  `account_agent` copies it to `warehouse/snapshot.duckdb` with an atomic rename. The app opens that copy
  read-only and reconnects when a new one appears. Everything on screen comes from one moment, shown in the
  sidebar, and the dashboard can never block or corrupt the pipeline.

**Walkthrough (2 minutes):**
1. Sign in as Northwind → **Emeka Kowalski**.
2. Open **Ember Labs LLC** (red, renews in 33 days).
3. **Why this score** shows risk jumping from about 3% to 47% in October.
4. **Agent review** shows the cited brief. Pick `E17` under **Trace a fact** to see the ticket timeline
   and the Parquet file it was loaded from.
5. Sign out, then sign in as Quarry's manager to see the stale-Stripe banner.

### Share it: Streamlit Community Cloud

The repository is ready to host the dashboard at a fixed `https://<name>.streamlit.app` URL.
- **Data:** the hosted app reads `dashboard_data/snapshot.duckdb` (27 MB), a slim copy of the tables the
  dashboard uses, published with `python -m pipeline.snapshot --slim`.
- **Dataset:** the complete generated dataset is in `lake/`, in full, for anyone to browse.
- **No API key needed:** the dashboard shows what the agent already wrote and never calls a model.

1. **Push the repo to GitHub.** It can be public or private; Community Cloud can read private repos once
   you authorise it. Create the repository on GitHub, then:
   ```bash
   git remote add origin git@github.com:<you>/cs-risk-platform.git && git push -u origin main
   ```
2. **Create the app.** At [share.streamlit.io](https://share.streamlit.io), choose **Create app → Deploy a
   public app from GitHub**, then pick the repo, branch `main` and main file path `app/dashboard.py`.
   Under **Advanced settings**, choose Python 3.11.
3. **Optional access code.** In the same Advanced settings, under **Secrets**, add
   `dashboard_password = "choose-a-code"`. Visitors then enter that code before the demo sign-in.
   The code lives in Streamlit's secrets store, never in the repo. Without it, anyone with the URL can use
   the demo, which is fine for synthetic data.
4. **Share the URL.** It stays the same across redeploys.

**To refresh the hosted data:** run the pipeline, then `python -m pipeline.snapshot --slim`, and commit
and push `dashboard_data/snapshot.duckdb`. Community Cloud redeploys on push.

### Future enhancements (out of scope for this exercise)
- **CSM feedback and draft approval:** approve, edit or reject drafts; rate briefs "useful / not useful";
  record the action taken. That needs its own small store, such as SQLite, because the warehouse is the
  pipeline's single writer. Feedback would become an evaluation set for the agent and intervention labels
  for the model, so a successful save stops looking like a wrong prediction.
- SSO in place of the demo picker.

## Next step: ML-based account matching

Rules with measured confidence are about 100% precise, but **1,112 source records stay in quarantine**.
Their tickets, invoices and usage never reach an account's risk score. In a labeled sample of 100,
every one was **ambiguous** rather than unknown: two or more live accounts share the name and domain
(an unmerged Salesforce duplicate, or two companies with the same name). A name-and-domain model can't
solve that either. What helps is evidence the rules don't use:
- contact-email overlap with ticket requesters,
- billing country and currency,
- record creation date against contract start,
- seat count against subscription quantity.

The plan:
1. **Blocking:** same tenant plus a shared name key or domain.
2. **Pair features:** the evidence above, plus name similarity (Jaro-Winkler).
3. **Model:** [Splink](https://github.com/moj-analytical-services/splink), Fellegi–Sunter with
   weights learned by expectation-maximisation. It runs on DuckDB. Validate it with the 1,089 labels
   already in `dbt/seeds/identity_labels.csv` (extend them with negative pairs).
4. **Apply only to quarantined records,** after the deterministic rules, with `match_method = 'ml'`
   and the pair's calibrated probability as confidence. At most one account per record.
5. **Success measures:** quarantine records recovered, precision on the labels, and the risk model's
   PR-AUC with and without the recovered history.

## Known simplifications

- Static FX rates (`dbt/seeds/fx_rates.csv`).
- DuckDB has no row-level security. Tenant isolation is enforced by keys and tests. In production
  you'd use a warehouse with row-level security, or Iceberg plus Trino.
