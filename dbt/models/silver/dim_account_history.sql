-- Salesforce accounts, one row per version, with source-time validity (valid_from/valid_to) and
-- arrival time (known_at). A merged duplicate points at its master through master_account_id.
with versions as (
    select * from {{ ref('stg_salesforce__account') }}
),

merges as (
    -- the latest word on each record: merged duplicates carry is_deleted + master_record_id
    select tenant_id, account_id, master_record_id
    from versions
    qualify row_number() over (partition by tenant_id, account_id order by modified_at desc, known_at desc) = 1
)

select
    v.tenant_id,
    v.account_id,
    case when m.master_record_id is not null then m.master_record_id else v.account_id end as master_account_id,
    v.account_name,
    v.website_domain,
    v.industry,
    v.account_type,
    v.owner_id,
    v.arr,
    v.currency,
    v.contract_start_date,
    v.renewal_date,
    v.tier,
    v.employee_band,
    v.billing_country,
    v.created_date,
    v.parent_id,
    v.is_deleted,
    v.account_name ilike '%do not use%' or v.website_domain = t.internal_domain as is_internal_test,
    {{ history_windows('v', 'account_id', 'modified_at') }},
    v.known_at,
    v._source_file
from versions v
join merges m using (tenant_id, account_id)
left join {{ ref('tenants') }} t on t.tenant_id = v.tenant_id
