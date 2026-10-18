-- Typed, renamed view over bronze. Keeps every version once: an exact repeat (same subscription_id, modified_at)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    id as subscription_id,
    customer_id,
    plan_id,
    interval as billing_interval,
    quantity as seats,
    unit_amount as unit_amount_minor,
    upper(currency) as currency,
    status,
    cancel_at,
    canceled_at,
    created as created_at,
    updated as modified_at,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'stripe__subscription') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, subscription_id, modified_at order by known_at, _ingested_at) = 1
