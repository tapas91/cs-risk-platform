-- Product events, one row per event. Retried deliveries are already gone in staging. Old and new
-- event names map to one canonical name; old 'row_count' and new 'rows' export keys become one column.
with events as (
    select * from {{ ref('stg_product__event') }}
)

select
    e.tenant_id,
    e.event_id,
    e.workspace_id,
    x.account_id,
    e.user_hash,
    coalesce(m.event_name, e.event_name_raw) as event_name,
    e.event_name_raw,
    e.event_time,
    e.known_at,
    date_diff('hour', e.event_time, e.known_at) as arrival_lag_hours,
    e.event_time > e.known_at as is_clock_skewed,       -- device clock ahead of the server
    coalesce(try_cast(e.properties_json::json ->> 'rows' as bigint),
             try_cast(e.properties_json::json ->> 'row_count' as bigint)) as export_rows,
    e.properties_json::json ->> 'status' as export_status,
    try_cast(e.properties_json::json ->> 'duration_s' as integer) as session_seconds,
    e.properties_json::json ->> 'client' as client,
    e.properties_json::json ->> 'provider' as integration_provider,
    try_cast(e.properties_json::json ->> 'delta' as integer) as seat_delta,
    e.properties_json,
    e._source_file
from events e
left join {{ ref('event_name_map') }} m on m.raw_name = e.event_name_raw
left join {{ ref('account_xref') }} x
    on x.tenant_id = e.tenant_id and x.source_system = 'product.workspace' and x.source_id = e.workspace_id
