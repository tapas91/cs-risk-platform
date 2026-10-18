-- Typed, renamed view over bronze. Keeps every version once: an exact repeat (same account_id, modified_at)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    id as account_id,
    name as account_name,
    nullif(lower(regexp_replace(regexp_replace(website, '^https?://', ''), '^www\.', '')), '') as website_domain,
    industry,
    type as account_type,
    owner_id,
    try_cast(arr as double) as arr,
    currency_iso_code as currency,
    try_cast(contract_start_date as date) as contract_start_date,
    try_cast(renewal_date as date) as renewal_date,
    tier,
    employee_band,
    billing_country,
    try_cast(created_date as date) as created_date,
    master_record_id,
    coalesce(is_deleted, false) as is_deleted,
    parent_id,
    last_modified_date as modified_at,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'salesforce__account') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, account_id, modified_at order by known_at, _ingested_at) = 1
