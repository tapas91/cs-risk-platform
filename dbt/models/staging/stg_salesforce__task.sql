-- Typed, renamed view over bronze. Keeps every record once: an exact repeat (same task_id)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    id as task_id,
    account_id,
    who_id as contact_id,
    owner_id,
    type as task_type,
    subject,
    status,
    -- Northwind's initial backfill stored dates as dd/mm/yyyy text; everything else is ISO
    coalesce(try_strptime(cast(activity_date as varchar), '%d/%m/%Y')::date,
             try_cast(cast(activity_date as varchar) as date)) as activity_date,
    cast(activity_date as varchar) as activity_date_raw,
    regexp_matches(cast(activity_date as varchar), '^\d{2}/\d{2}/\d{4}$') as is_legacy_date_format,
    created_date as created_at,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'salesforce__task') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, task_id order by known_at, _ingested_at) = 1
