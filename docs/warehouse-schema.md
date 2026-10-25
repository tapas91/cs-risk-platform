# Warehouse schema

The DuckDB warehouse (`warehouse/warehouse.duckdb`) holds 84 tables and views in eight schemas. This page
is the map: one overview of the layers, then three focused diagrams of the tables a new engineer reads
most. Every column of every dbt model, with its tests and full lineage, is in the generated dbt docs
(see [Browse every model](#browse-every-model-dbt-docs)).

Three keys run through everything:

| Key | Where it starts | What it means |
|---|---|---|
| `tenant_id` + a source ID | bronze | One record in one customer organisation's source system. Source IDs collide across tenants, so `tenant_id` is always part of the key. |
| `tenant_id` + `account_id` | silver (`account_xref`) | One canonical Salesforce account. Every fact is resolved to it, within its tenant only. |
| `as_of` + `tenant_id` + `account_id` | gold | The account as the model saw it on one date, built only from data received by that date. |

## 1. Layers

```mermaid
flowchart TB
    L["<b>landing/</b><br/>Fivetran-style Parquet<br/>tenant / source / table / synced_month"]

    subgraph BR["bronze · 16 tables"]
        B1["15 source tables<br/>salesforce__account, zendesk__ticket,<br/>stripe__charge, product__event, gmail__message …<br/><i>append-only, _source_file, _fivetran_synced</i>"]
        B2["_ingested_files<br/><i>file manifest: exactly once</i>"]
    end

    subgraph ST["staging · 15 views"]
        S1["stg_&lt;source&gt;__&lt;table&gt;<br/><i>typed, renamed, retries removed,<br/>known_at = sync time</i>"]
    end

    subgraph SV["silver · 19 tables"]
        V1["identity<br/>dim_account(_history), account_domain,<br/>account_match_candidates, <b>account_xref</b>"]
        V2["history (valid_from / valid_to / known_at)<br/>dim_contact, dim_subscription,<br/>dim_opportunity, dim_workspace _history"]
        V3["facts<br/>fct_product_event, fct_ticket (+ comment,<br/>status_change), fct_charge, fct_invoice,<br/>fct_email_message, fct_activity, …"]
    end

    subgraph RF["reference · 7 seeds"]
        R1["tenants, fx_rates, event_name_map,<br/>match_rule_priors, identity_labels,<br/>personal_email_domains, freshness_rules"]
    end

    subgraph OP["ops · 5 tables"]
        O1["match_precision, quarantine_identity,<br/>quarantine_parsing, source_freshness,<br/>schema_changes"]
    end

    subgraph GD["gold · 10 tables"]
        G1["as_of_dates → account_spine<br/>→ feat_usage / support / email /<br/>billing / relationship<br/>→ <b>account_features</b>"]
        G2["account_outcomes → <b>account_labels</b>"]
    end

    subgraph ML["ml · 7 tables"]
        M1["model_registry, test_predictions"]
        M2["<b>risk_scores</b>, risk_reasons<br/><i>current 14 weekly dates</i>"]
        M3["score_runs, <b>score_log</b>, reason_log<br/><i>append-only: what was shown</i>"]
    end

    subgraph AG["agent · 5 tables"]
        A1["runs → <b>cases</b> → evidence,<br/>tool_calls, actions"]
    end

    D["<b>snapshot.duckdb</b><br/>read-only copy<br/>for the dashboard"]

    L -- "bronze_ingest<br/>every 15 min" --> BR
    BR -- "silver_build (dbt)" --> ST
    ST --> SV
    RF --> SV
    SV --> OP
    SV -- "risk_scoring (dbt)" --> GD
    GD -- "risk_training (monthly)" --> M1
    GD -- "risk_scoring" --> M2
    M2 --> M3
    M2 -- "account_agent" --> AG
    M3 -. "evidence cites" .-> AG
    AG -- "publish_snapshot" --> D
    ML --> D
```

## 2. Identity: how a source record becomes an account

Every Stripe customer, Zendesk organisation and product workspace is tied to at most one Salesforce
account in its own tenant. Rules propose candidates, a measured confidence gates each rule, a human-set
prior picks the winner, and anything left without a confident winner is quarantined rather than guessed.

```mermaid
erDiagram
    DIM_ACCOUNT["silver.dim_account"] {
        varchar tenant_id PK
        varchar account_id PK
        varchar master_account_id "merge redirect target"
        varchar account_name
        varchar website_domain
        varchar owner_id "CSM"
        timestamptz known_at
    }
    DIM_ACCOUNT_HISTORY["silver.dim_account_history"] {
        varchar tenant_id PK
        varchar account_id PK
        timestamptz valid_from PK
        timestamptz valid_to
        varchar master_account_id
        timestamptz known_at "when we received this version"
    }
    ACCOUNT_DOMAIN["silver.account_domain"] {
        varchar tenant_id PK
        varchar domain PK "only domains with exactly one owner"
        varchar account_id FK
    }
    DIM_CONTACT_HISTORY["silver.dim_contact_history"] {
        varchar tenant_id PK
        varchar contact_id PK
        timestamptz valid_from PK
        varchar account_id FK
        varchar email
        boolean is_champion
    }
    ACCOUNT_MATCH_CANDIDATES["silver.account_match_candidates"] {
        varchar tenant_id PK
        varchar source_system PK "stripe.customer, zendesk.organization, ..."
        varchar source_id PK
        varchar account_id PK
        varchar match_method PK "sfdc_id, contact_email, email_domain, name, ..."
    }
    MATCH_RULE_PRIORS["reference.match_rule_priors"] {
        varchar source_system PK
        varchar match_method PK
        double prior_confidence "rule order: a human decision"
    }
    IDENTITY_LABELS["reference.identity_labels"] {
        varchar tenant_id PK
        varchar source_system PK
        varchar source_id PK
        varchar true_account_id "checked by an analyst"
    }
    MATCH_PRECISION["ops.match_precision"] {
        varchar source_system PK
        varchar match_method PK
        bigint n_labeled
        double precision_lower_95 "Wilson lower bound"
        double confidence "the gate: >= 0.7 to match"
    }
    ACCOUNT_XREF["silver.account_xref"] {
        varchar tenant_id PK
        varchar source_system PK
        varchar source_id PK
        varchar account_id FK
        varchar match_method
        double confidence
    }
    QUARANTINE_IDENTITY["ops.quarantine_identity"] {
        varchar tenant_id PK
        varchar source_system PK
        varchar source_id PK
        varchar claimed_account_id
        varchar reason "no_link_and_no_match, ambiguous_contact_email, ..."
    }

    DIM_ACCOUNT ||--|{ DIM_ACCOUNT_HISTORY : "versions"
    DIM_ACCOUNT ||--o{ ACCOUNT_DOMAIN : "owns"
    DIM_ACCOUNT ||--o{ DIM_CONTACT_HISTORY : "has contacts"
    DIM_ACCOUNT ||--o{ ACCOUNT_MATCH_CANDIDATES : "proposed by a rule"
    MATCH_RULE_PRIORS ||--|| MATCH_PRECISION : "prior for"
    IDENTITY_LABELS }o--|| MATCH_PRECISION : "measure"
    MATCH_PRECISION ||--o{ ACCOUNT_MATCH_CANDIDATES : "gates"
    ACCOUNT_MATCH_CANDIDATES }|--o| ACCOUNT_XREF : "highest prior wins"
    DIM_ACCOUNT ||--o{ ACCOUNT_XREF : "canonical account"
    ACCOUNT_MATCH_CANDIDATES }o..o| QUARANTINE_IDENTITY : "no confident winner"
```

`account_xref` is what every fact joins to get its `account_id`. `fct_ticket` also matches a requester's
email to a contact, but only when that email belongs to exactly one account.

## 3. Facts to gold: one row per account per date

Silver facts keep two timestamps: when something happened (`event_time`, `created_at`, `valid_from`) and
when the warehouse received it (`known_at`). Gold reads both, so a feature row for a date only uses what
was known on that date.

```mermaid
erDiagram
    DIM_ACCOUNT["silver.dim_account"] {
        varchar tenant_id PK
        varchar account_id PK
    }
    FCT_PRODUCT_EVENT["silver.fct_product_event"] {
        varchar tenant_id PK
        varchar event_id PK
        varchar account_id FK "via the workspace's xref"
        varchar event_name
        timestamptz event_time
        timestamptz known_at
    }
    FCT_TICKET["silver.fct_ticket"] {
        varchar tenant_id PK
        varchar ticket_id PK
        varchar account_id FK
        varchar priority
        varchar satisfaction_rating
        timestamptz created_at
        timestamptz first_known_at
    }
    FCT_CHARGE["silver.fct_charge"] {
        varchar tenant_id PK
        varchar charge_id PK
        varchar account_id FK
        varchar status
        double amount_usd
        timestamptz created_at
        timestamptz known_at
    }
    FCT_EMAIL_MESSAGE["silver.fct_email_message"] {
        varchar tenant_id PK
        varchar message_id PK
        varchar account_id FK
        varchar direction
        timestamptz sent_at
        timestamptz known_at
    }
    FCT_ACTIVITY["silver.fct_activity"] {
        varchar tenant_id PK
        varchar task_id PK
        varchar account_id FK
        boolean is_save_play
        date activity_date
    }
    DIM_SUBSCRIPTION_HISTORY["silver.dim_subscription_history"] {
        varchar tenant_id PK
        varchar subscription_id PK
        timestamptz valid_from PK
        varchar account_id FK
        bigint seats
        varchar status
        timestamptz known_at
    }
    FCT_OPPORTUNITY_STAGE_CHANGE["silver.fct_opportunity_stage_change"] {
        varchar tenant_id PK
        varchar opportunity_id PK
        timestamptz changed_at PK
        varchar account_id FK
        varchar stage_name
        timestamptz known_at
    }
    AS_OF_DATES["gold.as_of_dates"] {
        date as_of PK
        varchar purpose PK "train: monthly, score: 27 weekly"
        date data_as_of "newest arrival"
    }
    ACCOUNT_SPINE["gold.account_spine"] {
        date as_of PK
        varchar purpose PK
        varchar tenant_id PK
        varchar account_id PK
        varchar owner_id
        bigint tenure_days
        date next_renewal_date
    }
    FEAT_USAGE["gold.feat_usage (and feat_support, feat_email, feat_billing, feat_relationship)"] {
        date as_of PK
        varchar tenant_id PK
        varchar account_id PK
        bigint usage_events_30d
        bigint active_users_30d
        bigint days_since_last_usage
    }
    ACCOUNT_FEATURES["gold.account_features"] {
        date as_of PK
        varchar purpose PK
        varchar tenant_id PK
        varchar account_id PK
        double usage_trend "one of 45 model inputs"
        boolean notice_cancel_scheduled "shown, not a model input"
        timestamptz feature_cutoff "nothing after this is used"
    }
    ACCOUNT_OUTCOMES["gold.account_outcomes"] {
        varchar tenant_id
        varchar account_id
        timestamptz event_at
        varchar event_type "churn, lost renewal, downsell 20%+"
    }
    ACCOUNT_LABELS["gold.account_labels"] {
        date as_of PK
        varchar tenant_id PK
        varchar account_id PK
        boolean label "outcome within 90 days"
        boolean label_complete "the 90 days have passed"
    }

    DIM_ACCOUNT ||--o{ FCT_PRODUCT_EVENT : ""
    DIM_ACCOUNT ||--o{ FCT_TICKET : ""
    DIM_ACCOUNT ||--o{ FCT_CHARGE : ""
    DIM_ACCOUNT ||--o{ FCT_EMAIL_MESSAGE : ""
    DIM_ACCOUNT ||--o{ FCT_ACTIVITY : ""
    DIM_ACCOUNT ||--o{ DIM_SUBSCRIPTION_HISTORY : ""
    DIM_ACCOUNT ||--o{ FCT_OPPORTUNITY_STAGE_CHANGE : ""
    AS_OF_DATES ||--|{ ACCOUNT_SPINE : "live customers on each date"
    ACCOUNT_SPINE ||--|| FEAT_USAGE : "same key"
    FCT_PRODUCT_EVENT }o--o{ FEAT_USAGE : "windows ending at as_of, known_at <= as_of"
    ACCOUNT_SPINE ||--|| ACCOUNT_FEATURES : "joins all five feat_*"
    FEAT_USAGE ||--|| ACCOUNT_FEATURES : ""
    DIM_SUBSCRIPTION_HISTORY }o--o{ ACCOUNT_OUTCOMES : "cancellations, seat drops"
    FCT_OPPORTUNITY_STAGE_CHANGE }o--o{ ACCOUNT_OUTCOMES : "lost renewals"
    ACCOUNT_SPINE ||--o| ACCOUNT_LABELS : "train dates"
    ACCOUNT_OUTCOMES }o--o{ ACCOUNT_LABELS : "next outcome after as_of"
```

The other four feature models follow `feat_usage`'s pattern: `feat_support` reads `fct_ticket`,
`feat_email` reads `fct_email_message`, `feat_billing` reads `fct_charge` and `dim_subscription_history`,
and `feat_relationship` reads `dim_contact_history` and `fct_activity`. `account_spine` also reads
`dim_account_history` (the version known on each date) and `account_outcomes` (to drop accounts already
gone).

## 4. Model and agent: from a feature row to a cited brief

`ml.risk_scores` is the current window, rewritten by every scoring run. `ml.score_log` is the history of
what was shown, and agent evidence points at it, so a brief keeps tracing to the numbers it quoted.

```mermaid
erDiagram
    ACCOUNT_FEATURES["gold.account_features"] {
        date as_of PK
        varchar purpose PK
        varchar tenant_id PK
        varchar account_id PK
    }
    ACCOUNT_LABELS["gold.account_labels"] {
        date as_of PK
        varchar tenant_id PK
        varchar account_id PK
        boolean label
    }
    MODEL_REGISTRY["ml.model_registry"] {
        varchar model_version PK
        varchar status "production, retired, rejected"
        varchar decision "the gate's verdict"
        json metrics
        json split "the windows it trained on"
    }
    TEST_PREDICTIONS["ml.test_predictions"] {
        varchar model_version FK
        date as_of
        varchar tenant_id
        varchar account_id
        boolean label
        double risk_prob
    }
    RISK_SCORES["ml.risk_scores"] {
        date as_of PK "latest 14 weekly dates"
        varchar tenant_id PK
        varchar account_id PK
        double risk_prob
        varchar band
        varchar status
        integer rank_in_book
        varchar model_version FK
        timestamptz feature_cutoff
    }
    RISK_REASONS["ml.risk_reasons"] {
        date as_of PK
        varchar tenant_id PK
        varchar account_id PK
        integer reason_rank PK
        varchar feature
        double contribution "TreeSHAP"
    }
    SCORE_RUNS["ml.score_runs"] {
        varchar run_id PK
        varchar model_version FK
        date as_of
        integer logged
    }
    SCORE_LOG["ml.score_log"] {
        varchar run_id PK
        varchar tenant_id PK
        varchar account_id PK
        date as_of
        double risk_prob
        varchar band
    }
    REASON_LOG["ml.reason_log"] {
        varchar run_id PK
        varchar tenant_id PK
        varchar account_id PK
        integer reason_rank PK
        varchar reason
    }
    AGENT_RUNS["agent.runs"] {
        varchar run_id PK
        varchar mode "llm or fallback"
        double est_cost_usd
    }
    CASES["agent.cases"] {
        varchar case_id PK "tenant|account|as_of"
        varchar run_id FK
        varchar tenant_id
        varchar account_id
        date as_of
        varchar trigger
        varchar route
        json brief "sentences with evidence IDs"
    }
    EVIDENCE["agent.evidence"] {
        varchar case_id PK
        varchar evidence_id PK "E1, E2, ..."
        varchar fact
        varchar source_table
        varchar source_key
    }
    TOOL_CALLS["agent.tool_calls"] {
        varchar case_id PK
        integer seq PK
        varchar tool
    }
    ACTIONS["agent.actions"] {
        varchar action_id PK "case_id|route"
        varchar case_id FK
        varchar assignee
        varchar status
    }

    ACCOUNT_FEATURES ||--o| ACCOUNT_LABELS : "train rows"
    ACCOUNT_LABELS }o--|| MODEL_REGISTRY : "trains"
    MODEL_REGISTRY ||--o{ TEST_PREDICTIONS : "evaluated by"
    ACCOUNT_FEATURES ||--o| RISK_SCORES : "score rows"
    MODEL_REGISTRY ||--o{ RISK_SCORES : "production model"
    RISK_SCORES ||--o{ RISK_REASONS : "top 3"
    SCORE_RUNS ||--o{ SCORE_LOG : "rows that changed"
    RISK_SCORES ||--o| SCORE_LOG : "latest date, logged"
    SCORE_LOG ||--o{ REASON_LOG : ""
    AGENT_RUNS ||--o{ CASES : ""
    RISK_SCORES ||--o| CASES : "triaged"
    CASES ||--|{ EVIDENCE : ""
    CASES ||--o{ TOOL_CALLS : ""
    CASES ||--o| ACTIONS : "outbox"
    EVIDENCE }o..o| SCORE_LOG : "source_key run_id/account@as_of"
```

Evidence also points at silver rows (`source_table` + `source_key`: a ticket, a charge, a subscription),
and those carry `_source_file` back to the landed bronze file. The dashboard follows that chain.

## Browse every model (dbt docs)

The diagrams above are curated. For every dbt model's columns, tests and lineage graph, generate the dbt
docs from the running stack and open them locally:

```bash
docker compose exec airflow-scheduler bash -c '$DBT_BIN docs generate --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt --target-path /opt/airflow/dbt/target'
```

```bash
python3 -m http.server 8081 --directory dbt/target
```

Then open http://localhost:8081. Generate it while the DAGs are idle: it reads the warehouse.
