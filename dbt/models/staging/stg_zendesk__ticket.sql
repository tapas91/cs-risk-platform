-- Typed, renamed view over bronze. Keeps every version once: an exact repeat (same ticket_id, modified_at, is_deleted_in_source)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    cast(id as varchar) as ticket_id,
    cast(organization_id as varchar) as organization_id,
    lower(requester_email) as requester_email,
    cast(assignee_id as varchar) as assignee_id,
    subject,
    type as ticket_type,
    priority,
    tags,
    via_channel,
    status,
    satisfaction_rating,
    {{ optional_column(source('bronze', 'zendesk__ticket'), 'custom_churn_risk_flag', 'boolean') }} as churn_risk_flag,  -- field added in Zendesk in Feb 2025
    created_at,
    updated_at as modified_at,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'zendesk__ticket') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, ticket_id, modified_at, is_deleted_in_source order by known_at, _ingested_at) = 1
