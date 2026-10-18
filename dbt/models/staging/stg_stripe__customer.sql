-- Typed, renamed view over bronze. Keeps every record once: an exact repeat (same customer_id)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    id as customer_id,
    lower(email) as email,
    name as customer_name,
    metadata_sfdc_account_id,
    upper(currency) as currency,
    created as created_at,
    delinquent,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'stripe__customer') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, customer_id order by known_at, _ingested_at) = 1
