-- Each change of a ticket's status, with when it happened and when we learned about it.
with versions as (
    select tenant_id, ticket_id, status, priority, modified_at, known_at,
           lag(status) over (partition by tenant_id, ticket_id order by modified_at, known_at) as previous_status
    from {{ ref('stg_zendesk__ticket') }}
    where not is_deleted_in_source
)

select tenant_id, ticket_id, previous_status, status, priority, modified_at as changed_at, known_at
from versions
where previous_status is distinct from status
