-- Every way a source record could be tied to an account: one row per (record, rule, account).
-- A record can appear several times when several rules fire. Rules that would match more than one
-- account (shared domain, repeated name) produce no candidate at all. account_xref picks the winner.
with accounts as (
    select tenant_id, account_id, {{ name_key('account_name') }} as name_key from {{ ref('dim_account') }}
),
redirect as (  -- any Salesforce ID ever seen, including merged duplicates, to its canonical account
    select distinct h.tenant_id, h.account_id as any_id, h.master_account_id as account_id
    from {{ ref('dim_account_history') }} h
    join accounts a on a.tenant_id = h.tenant_id and a.account_id = h.master_account_id
),
names as (
    select tenant_id, name_key, min(account_id) as account_id, count(*) as n from accounts group by 1, 2
),
contacts as (  -- an email used at two accounts (a shared mailbox, a consultant) identifies neither
    select tenant_id, email, min(account_id) as account_id from {{ ref('dim_contact_history') }}
    group by 1, 2 having count(distinct account_id) = 1
),

stripe as (select * from {{ ref('stg_stripe__customer') }} qualify row_number() over (partition by tenant_id, customer_id order by known_at desc) = 1),
orgs as (select * from {{ ref('stg_zendesk__organization') }} qualify row_number() over (partition by tenant_id, organization_id order by modified_at desc, known_at desc) = 1),
spaces as (select * from {{ ref('stg_product__workspace') }} qualify row_number() over (partition by tenant_id, workspace_id order by modified_at desc, known_at desc) = 1),

candidates as (
    -- Salesforce itself
    select tenant_id, 'salesforce.account' as source_system, any_id as source_id, account_id,
           case when any_id = account_id then 'sfdc_id' else 'sfdc_merge' end as match_method
    from redirect

    -- Stripe customers
    union all
    select s.tenant_id, 'stripe.customer', s.customer_id, r.account_id,
           case when r.any_id = r.account_id then 'stripe_metadata' else 'stripe_metadata_merged' end
    from stripe s join redirect r on r.tenant_id = s.tenant_id and r.any_id = s.metadata_sfdc_account_id
    union all
    select s.tenant_id, 'stripe.customer', s.customer_id, c.account_id, 'contact_email'
    from stripe s join contacts c on c.tenant_id = s.tenant_id and c.email = s.email
    union all
    select s.tenant_id, 'stripe.customer', s.customer_id, d.account_id, 'email_domain'
    from stripe s join {{ ref('account_domain') }} d on d.tenant_id = s.tenant_id and d.domain = {{ email_domain('s.email') }}
    union all
    select s.tenant_id, 'stripe.customer', s.customer_id, n.account_id, 'name'
    from stripe s join names n on n.tenant_id = s.tenant_id and n.name_key = {{ name_key('s.customer_name') }} and n.n = 1

    -- Zendesk organisations
    union all
    select o.tenant_id, 'zendesk.organization', o.organization_id, r.account_id,
           case when r.any_id = r.account_id then 'zendesk_external_id' else 'zendesk_external_id_merged' end
    from orgs o join redirect r on r.tenant_id = o.tenant_id and r.any_id = o.external_id
    union all
    select o.tenant_id, 'zendesk.organization', o.organization_id, d.account_id, 'org_domain'
    from (select tenant_id, organization_id, lower(unnest(domain_names)) as domain from orgs) o
    join {{ ref('account_domain') }} d on d.tenant_id = o.tenant_id and d.domain = o.domain
    union all
    select o.tenant_id, 'zendesk.organization', o.organization_id, n.account_id, 'name'
    from orgs o join names n on n.tenant_id = o.tenant_id and n.name_key = {{ name_key('o.organization_name') }} and n.n = 1

    -- Product workspaces
    union all
    select w.tenant_id, 'product.workspace', w.workspace_id, r.account_id,
           case when r.any_id = r.account_id then 'workspace_account_id' else 'workspace_account_id_merged' end
    from spaces w join redirect r on r.tenant_id = w.tenant_id and r.any_id = w.sfdc_account_id
    union all
    select w.tenant_id, 'product.workspace', w.workspace_id, n.account_id, 'name'
    from spaces w join names n on n.tenant_id = w.tenant_id
     and n.name_key = {{ name_key("regexp_replace(w.workspace_name, ' - Sandbox$', '')") }} and n.n = 1
)

select distinct * from candidates  -- an org with two matching domains is one candidate, not two
