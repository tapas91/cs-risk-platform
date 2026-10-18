-- Gmail metadata from CSM and AE mailboxes. The customer side is the recipient for outbound mail and
-- the sender for inbound mail; it maps to an account by company domain only.
with m as (
    select *,
           case when direction = 'outbound' then lower(to_domains[1]) else from_domain end as counterpart_domain
    from {{ ref('stg_gmail__message') }}
)

select
    m.tenant_id,
    m.message_id,
    m.thread_id,
    m.mailbox,
    u.user_id as mailbox_user_id,
    u.user_role as mailbox_role,
    m.direction,
    m.counterpart_domain,
    d.account_id,
    m.counterpart_domain in (select domain from {{ ref('personal_email_domains') }}) as is_personal_domain,
    m.subject = 'Delivery Status Notification (Failure)' as is_bounce_notice,
    m.sent_at,
    m.sent_at_raw,
    m.subject,
    m.has_reply,
    m.is_bounce,
    m.cc_count,
    m.known_at,
    m._source_file
from m
left join {{ ref('dim_user') }} u on u.tenant_id = m.tenant_id and u.email = m.mailbox
left join {{ ref('account_domain') }} d on d.tenant_id = m.tenant_id and d.domain = m.counterpart_domain
-- two Salesforce users can share a mailbox address (a rehire, a reused alias): take the one who had
-- started by the time the message was sent, the most recent first
qualify row_number() over (partition by m.tenant_id, m.message_id
                           order by (u.created_date <= m.sent_at::date) desc nulls last, u.created_date desc) = 1
