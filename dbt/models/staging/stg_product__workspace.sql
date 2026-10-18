-- Typed, renamed view over bronze. Keeps every version once: an exact repeat (same workspace_id, modified_at)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    id as workspace_id,
    sfdc_account_id,
    name as workspace_name,
    plan,
    seats_purchased,
    status,
    created_at,
    updated_at as modified_at,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'product__workspace') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, workspace_id, modified_at order by known_at, _ingested_at) = 1
