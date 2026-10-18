-- Typed, renamed view over bronze. Keeps every version once: an exact repeat (same contact_id, modified_at)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    id as contact_id,
    account_id,
    first_name,
    last_name,
    lower(email) as email,
    title,
    contact_role,
    is_champion,
    try_cast(created_date as date) as created_date,
    try_cast(inactive_date as date) as inactive_date,
    coalesce(email_bounced, false) as email_bounced,
    last_modified_date as modified_at,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'salesforce__contact') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, contact_id, modified_at order by known_at, _ingested_at) = 1
