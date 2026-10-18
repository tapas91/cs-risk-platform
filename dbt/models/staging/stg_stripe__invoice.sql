-- Typed, renamed view over bronze. Keeps every version once: an exact repeat (same invoice_id, status)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    id as invoice_id,
    customer_id,
    subscription_id,
    billing_reason,
    amount_due as amount_due_minor,
    amount_paid as amount_paid_minor,
    upper(currency) as currency,
    try_cast(period_start as date) as period_start,
    status,
    attempt_count,
    created as created_at,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'stripe__invoice') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, invoice_id, status order by known_at, _ingested_at) = 1
