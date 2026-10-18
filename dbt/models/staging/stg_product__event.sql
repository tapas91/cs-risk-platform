-- Typed, renamed view over bronze. Keeps every record once: an exact repeat (same event_id)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    event_id,
    workspace_id,
    user_hash,
    event_name as event_name_raw,
    event_time,
    properties_json,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'product__event') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, event_id order by known_at, _ingested_at) = 1
