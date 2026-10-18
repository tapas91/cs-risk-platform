-- Typed, renamed view over bronze. Keeps every record once: an exact repeat (same charge_id)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    id as charge_id,
    invoice_id,
    customer_id,
    amount as amount_minor,
    upper(currency) as currency,
    status,
    failure_code,
    paid,
    created as created_at,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'stripe__charge') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, charge_id order by known_at, _ingested_at) = 1
