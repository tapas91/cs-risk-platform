# Design notes

What I decided, what I deliberately skipped, and what breaks first at 10× scale. The README covers
how to run it. The full design with diagrams is in
[docs/solution-design.html](docs/solution-design.html) (open it in a browser).

**The problem, as I read it:** CSMs own about 120 accounts and can work about 10 a week. They don't need
a colour grid. They need a short, ranked, explained list, early enough to act, with a human sending
anything a customer sees.

---

## 1. What I decided

### Scope
| Decision | Instead of | Why |
|---|---|---|
| A ranked list per CSM, with reasons | A red/yellow/green grid of every account | The list matches a CSM's capacity; a grid only moves the guessing to a new screen |
| The agent drafts outreach; the CSM sends it | Auto-emailing customers who turn red | An account that turns red is often already unhappy or mid-negotiation. A wrong email there costs far more than a wrong row on a list |
| "Insufficient data" as its own status | Scoring silence as healthy | Unknown must never look like healthy |

### Stack
| Decision | Instead of | Why |
|---|---|---|
| Airflow, DuckDB, dbt, LightGBM, Claude, Streamlit | Spark, Iceberg, Trino, streaming | Runs on one laptop; the source syncs every 6 hours, so streaming buys nothing |
| dbt for silver and gold | SQL inside Python operators | Run order from `ref()`, tests on every build, lineage for free |
| Separate virtualenvs for dbt and ML inside the Airflow image | One shared environment | Their dependencies never fight Airflow's pinned constraint |

### Architecture
- **A deterministic pipeline with one bounded agent,** not an agent per source. Scores must be reproducible and testable against history. The LLM does only what needs judgment: investigating, routing, writing. Code decides what it may see and whether its output stands.
- **Layers:** landing → bronze (exact copy) → silver (true, matched, versioned) → gold (point-in-time features) → model → agent → dashboard.

### Data model
- **`tenant_id` first in every key.** Source IDs collide across tenants (over 2,000 Zendesk ticket IDs), and the same company buying from two tenants is two accounts, never merged.
- **Bronze** is append-only, with each row's `_source_file` and a file manifest, so every file loads exactly once. Schema drift adds or widens columns instead of failing.
- **Silver history** keeps two timelines: `valid_from`/`valid_to` (when it was true in the source) and `known_at` (when we received it). Late data can't leak into past scores.
- **Account master** (`account_xref`): stored ID → merged-ID redirect → contact email → company domain → name, all within one tenant. Ambiguous records go to quarantine rather than being guessed. Rule order is a human decision (`match_rule_priors`); each rule's confidence is **measured** on 1,260 labeled matches (Wilson lower bound) and gates the rule at 0.7.
- **Gold:** one row per account per as-of date, about 45 features, plus a label.

### Account state
An account's state is four layers, each answering a different question:
1. **What the systems said, and when we knew it:** silver history.
2. **The account as the model saw it on a date:** a `gold.account_features` row, built only from data received by that date.
3. **Risk state** (`ml.risk_scores`):
   - a calibrated probability,
   - a band with hysteresis (red after two runs ≥ 0.25, held until < 0.18; yellow 0.10 / 0.07),
   - a status: `scored`, `insufficient_data` or `customer_notice`.
4. **What we're doing about it:** the agent's case (route, brief, evidence) for that score date.

### What the model predicts
- **Target:** churn or downsize (20%+ seats lost) **within 90 days**, for live customers. That's long enough to act and short enough to be honest. Downsell counts, because losing half the seats is a loss too.
- **Labels** come from what the business recorded (Stripe cancellation, lost renewal, Former Customer status, seat drop), never from the generator's answers. They match all 639 real churns.
- **Not inputs:** customer notices (known risk, shown to the CSM, not predicted) and CSM save plays (they react to risk already seen).
- **Model:** LightGBM, over logistic regression and over an LLM's judgment. Tabular data, rare positives (2–3%); trees learn interactions and give an exact per-score explanation (TreeSHAP).
- **Evaluation population:** accounts that already gave notice are left out of training and test. They're nearly all positives and would inflate every metric; the model is judged on early warning only.
- **Windows:** rolling, counted back from the newest month with a complete label (test 3 months, validation 3, training the rest, 90-day gaps between), so each monthly retrain learns from one more month.
- **Calibration:** Platt (a logistic curve over the model's log-odds) on half the validation accounts, the half early stopping didn't see; per tenant where a tenant has 50+ positives. Isotonic was tried and dropped: on ~100 positives it overfit into steps whose ties cost ranking quality (PR-AUC 0.24 vs 0.28 for the same model).
- **Ranking:** probability × ARR × up to 2× within 180 days of renewal. Notices first, then red, then yellow.

### How unattended work is triggered
1. `bronze_ingest` runs every 15 minutes, and stops at its first task if nothing new landed.
2. Each later DAG runs because the previous one **changed data** (Airflow datasets), not on a clock: `silver_build` → `risk_scoring` (features, score with the production model) → `account_agent` (review, publish dashboard snapshot).
3. **Training is separate and monthly** (`risk_training`). Labels take 90 days to mature, so retraining on every sync adds nothing and would change every score. A failed retrain never stops scoring.
4. **Gates:**
   - dbt tests fail a bad silver build;
   - a retrained model reaches production only if it beats the rules baseline and doesn't lose more than 0.005 PR-AUC to production;
   - the agent reviews at most 12 accounts per run, 3 per CSM.

### The agent
- **Triage is SQL;** investigation is Claude with six read-only tools **bound in code** to one tenant, account and score date, seeing only data known by that date.
- **Output** is validated in code:
  - every brief sentence cites evidence IDs, and every number appears in a cited fact;
  - routes need supporting evidence (billing needs a failed payment, suppression needs work in progress);
  - drafts contain no internal terms.
- **One retry,** then rule-based fallback. That fallback also covers no API key and refusals.
- **Idempotent outbox** (`agent.actions`). It never changes a score and never contacts a customer.
- **Customer text is marked untrusted.** A planted prompt injection was ignored and flagged.

### Dashboard
- **Read-only,** over a snapshot published with an atomic rename, so it can't block or corrupt the single-writer warehouse.
- **One tenant-scoped data layer** (`app/data.py`). The tenant comes from the signed-in user, never from the page. CSMs see their own book; managers see their tenant. Ten tests try to cross those lines.
- **Trace-back:** score → reasons → model input row; brief sentence → evidence → source rows → landed bronze file.

### Evaluation
| Layer | How it's checked |
|---|---|
| Data | `verify_blueprint.py`: all 27 designed edge cases present, with counts |
| Pipeline | `verify_warehouse.py`: 15 checks against the lake and ground truth (exactly-once, dedupe, merges, no cross-tenant links, identity precision 99.96%, stalled feed flagged, agent briefs cited) |
| Model | Rolling time-based test window, notice accounts left out. PR-AUC 0.28 vs 0.18 for logistic regression and 0.03 for rules; top-10 precision 11.5% vs a 2.2% base rate; 80% of real churners listed in the 90 days before, with a median 68–75 days' warning. Calibration table, trap-group false alarms, ablation (`MODEL_REPORT.md`) |
| Agent | Code validation of every brief, prompt-injection test, per-case `decided_by` and validation status, cost per run |
| Dashboard | Tenant-isolation tests; headless app tests in a clean container |

---

## 2. What I deliberately skipped

| Skipped | Why | What it would take |
|---|---|---|
| **Automatic customer emails** | False positives here damage relationships; a human should send | Policy and approval workflow first |
| **Real-time streaming** | The source syncs every 6 hours; latency is bounded by the source | Webhooks into a queue for the few urgent signals (failed payment, P1 ticket) |
| **Database row-level security** | DuckDB doesn't have it; a local build doesn't need a warehouse service | A warehouse with RLS, or a schema per large tenant |
| **LLM features from ticket text** | The model is required to stand on fitted, measurable features first; text features need their own evaluation | Schema-bound extraction, cached by content hash, admitted only if it improves the backtest |
| **Probabilistic matching (Splink)** | The rules are 99.96% precise; the remaining quarantine is ambiguity between near-identical accounts, which Splink alone wouldn't resolve | Extra evidence (contact overlap, currency, dates), scoped to the quarantine |
| **CSM feedback, draft approval, a CSM assistant, a Monday digest** | Nothing would consume feedback yet; a read-only dashboard is the safer multi-tenant story | A small app-owned store (SQLite), then feedback as agent-evaluation and intervention labels |
| **Per-tenant LLM consent and PII redaction** | Synthetic data; the generator stores no message bodies | A per-tenant opt-in flag and redaction before any text reaches the model |
| **A context-only model as the gate's baseline** | Out of time; the ablation shows it's the honest bar | A second baseline in `gate()` and in `MODEL_REPORT.md` |
| **SSO** | The demo picker shows the roles; only `sign_in()` would change | An identity provider in front of Streamlit |
| **Parent/child roll-up, per-tenant quotas, tenant offboarding** | Not needed to show the core loop | Hierarchy in gold; Airflow pools per tenant; a deletion and retrain job |

---

## 3. What breaks first at 10×

At 10× there are about 50,000 accounts, 2.2 million events, 21,000 landed files, and perhaps 40 tenants.
**These are projections from current measurements, not a load test:** an 88 MB warehouse, a 27 MB
dashboard snapshot, about 220 accounts in the agent's queue, and silver building in about 10 seconds.

| Order | What breaks | Why | Fix |
|---|---|---|---|
| 1 | **The hosted dashboard** | The slim snapshot grows to about 270 MB, past GitHub's 100 MB per-file limit. A hard stop | Serve the snapshot from object storage or a hosted DuckDB (MotherDuck) instead of git |
| 2 | **The agent, and everything queued behind it** | About 2,000 flagged accounts; at 12 per run the backlog never drains. A higher cap holds the single-writer pool for minutes to hours, and ingestion and silver wait | Take the agent off the pool (read the snapshot, write its own outbox); parallel reviews; the Batch API for non-urgent cases; a re-review cooldown |
| 3 | **The single writer** | Full silver rebuilds and gold's point-in-time joins grow about 10×, and every step waits for every other | Incremental event facts; move storage to Iceberg plus a query engine (dbt models carry over) |
| 4 | **Identity matching** | More look-alike names and domains: quarantine grows faster than the data. Precision holds, recall drops | Probabilistic matching becomes necessary |
| 5 | **Tenant isolation** | With 40 tenants, one missed `WHERE tenant_id` in the application layer is a cross-tenant leak | Database-enforced row-level security |
| 6 | **File discovery** | Listing the whole bucket every 15 minutes gets slow and costly on real S3 | S3 event notifications to a queue, or listing only recent `synced_month` partitions |

**What doesn't break: the model.** More history only improves it, training stays in the minutes, and
more tenants qualify for their own calibration.&#x20;
