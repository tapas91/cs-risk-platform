-- Typed, renamed view over bronze. Keeps every version once: an exact repeat (same organization_id, modified_at)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    cast(id as varchar) as organization_id,
    name as organization_name,
    domain_names,
    external_id,
    created_at,
    updated_at as modified_at,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'zendesk__organization') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, organization_id, modified_at order by known_at, _ingested_at) = 1
