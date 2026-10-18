-- Typed, renamed view over bronze. Keeps every record once: an exact repeat (same comment_id)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    cast(id as varchar) as comment_id,
    cast(ticket_id as varchar) as ticket_id,
    author_role,
    lower(author_email) as author_email,
    public as is_public,
    body,
    created_at,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'zendesk__ticket_comment') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, comment_id order by known_at, _ingested_at) = 1
