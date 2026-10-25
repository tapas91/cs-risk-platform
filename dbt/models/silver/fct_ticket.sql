-- Zendesk tickets, current state. The account comes from the organisation when there is one, and
-- otherwise from the requester's email matching a Salesforce contact.
with versions as (
    select * from {{ ref('stg_zendesk__ticket') }}
),
latest as (
    -- attributes come from the newest real version; a delete marker is not a version
    select * from versions
    where not is_deleted_in_source
    qualify row_number() over (partition by tenant_id, ticket_id order by modified_at desc, known_at desc) = 1
),
timeline as (
    select tenant_id, ticket_id,
           min(modified_at) filter (where status in ('solved', 'closed')) as solved_at,
           min(known_at) as first_known_at,
           count(*) filter (where not is_deleted_in_source) as versions_seen,
           -- Fivetran marks the record deleted, whichever version the marker happens to copy
           bool_or(is_deleted_in_source) as is_deleted
    from versions group by 1, 2
),
requester as (  -- same rule as account_match_candidates: an email shared by two accounts matches neither
    select tenant_id, email, min(account_id) as account_id from {{ ref('dim_contact_history') }}
    group by 1, 2 having count(distinct account_id) = 1
)

select
    l.tenant_id,
    l.ticket_id,
    l.organization_id,
    coalesce(xo.account_id, r.account_id) as account_id,
    case when xo.account_id is not null then 'organization'
         when r.account_id is not null then 'requester_email' end as account_match,
    l.requester_email,
    l.assignee_id,
    l.subject,
    l.ticket_type,
    l.priority,
    l.tags,
    l.tags[1] as topic_tag,
    l.via_channel,
    l.status,
    l.satisfaction_rating,
    l.churn_risk_flag,
    l.created_at,
    t.solved_at,
    date_diff('hour', l.created_at, t.solved_at) as resolution_hours,
    t.is_deleted,
    t.versions_seen,
    t.first_known_at,
    l.known_at as last_known_at
from latest l
join timeline t using (tenant_id, ticket_id)
left join {{ ref('account_xref') }} xo
    on xo.tenant_id = l.tenant_id and xo.source_system = 'zendesk.organization' and xo.source_id = l.organization_id
left join requester r on r.tenant_id = l.tenant_id and r.email = l.requester_email
