-- Typed, renamed view over bronze. Keeps every version once: an exact repeat (same opportunity_id, modified_at)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    id as opportunity_id,
    account_id,
    name as opportunity_name,
    type as opportunity_type,
    stage_name,
    try_cast(amount as double) as amount,
    currency_iso_code as currency,
    try_cast(close_date as date) as close_date,
    probability,
    is_closed,
    is_won,
    closed_lost_reason,
    owner_id,
    try_cast(created_date as date) as created_date,
    last_modified_date as modified_at,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'salesforce__opportunity') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, opportunity_id, modified_at order by known_at, _ingested_at) = 1
