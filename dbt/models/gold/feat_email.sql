-- Conversation health from mailbox metadata. Inbound counts are used rather than the outbound
-- has_reply flag, because has_reply is set when a reply arrives, possibly after the as-of date.
with s as (select as_of, as_of_ts, tenant_id, account_id from {{ ref('account_spine') }}),
m as (select * from {{ ref('fct_email_message') }} where account_id is not null and sent_at is not null)
select
    s.as_of, s.tenant_id, s.account_id,
    count(m.message_id) filter (where m.direction = 'outbound' and m.sent_at > s.as_of_ts - interval 90 day) as emails_out_90d,
    count(m.message_id) filter (where m.direction = 'inbound' and not m.is_bounce_notice and m.sent_at > s.as_of_ts - interval 90 day) as emails_in_90d,
    count(m.message_id) filter (where (m.is_bounce or m.is_bounce_notice) and m.sent_at > s.as_of_ts - interval 90 day) as email_bounces_90d,
    date_diff('day', max(m.sent_at) filter (where m.direction = 'inbound' and not m.is_bounce_notice), s.as_of_ts) as days_since_customer_email
from s
left join m on m.tenant_id = s.tenant_id and m.account_id = s.account_id
    and m.sent_at <= s.as_of_ts and m.known_at <= s.as_of_ts and m.sent_at > s.as_of_ts - interval 180 day
group by s.as_of, s.tenant_id, s.account_id, s.as_of_ts
