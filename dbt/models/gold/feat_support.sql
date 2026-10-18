-- Support load and sentiment as of each date (tickets the warehouse knew about by then).
-- Explicit notices (cancellation requests, agents' churn-risk flag) are kept as flags, not model
-- inputs: a customer saying "we're leaving" is something to act on, not something to predict.
with s as (select as_of, as_of_ts, tenant_id, account_id from {{ ref('account_spine') }}),
t as (select * from {{ ref('fct_ticket') }} where account_id is not null and not is_deleted)
select
    s.as_of, s.tenant_id, s.account_id,
    count(t.ticket_id) filter (where t.created_at > s.as_of_ts - interval 30 day) as tickets_30d,
    count(t.ticket_id) filter (where t.created_at > s.as_of_ts - interval 90 day) as tickets_90d,
    count(t.ticket_id) filter (where t.created_at > s.as_of_ts - interval 90 day and t.priority in ('urgent', 'high')) as urgent_tickets_90d,
    count(t.ticket_id) filter (where t.created_at > s.as_of_ts - interval 90 day and t.topic_tag in ('escalation', 'incident')) as incident_tickets_90d,
    count(t.ticket_id) filter (where t.solved_at is null or t.solved_at > s.as_of_ts) as open_tickets,
    count(t.ticket_id) filter (where t.solved_at <= s.as_of_ts and t.solved_at > s.as_of_ts - interval 90 day and t.satisfaction_rating = 'bad') as bad_csat_90d,
    count(t.ticket_id) filter (where t.solved_at <= s.as_of_ts and t.solved_at > s.as_of_ts - interval 90 day and t.satisfaction_rating = 'good') as good_csat_90d,
    avg(t.resolution_hours) filter (where t.solved_at <= s.as_of_ts and t.solved_at > s.as_of_ts - interval 90 day) as avg_resolution_hours_90d,
    count(t.ticket_id) filter (where t.created_at > s.as_of_ts - interval 60 day and t.topic_tag = 'data_export') as data_export_tickets_60d,
    count(t.ticket_id) filter (where t.created_at > s.as_of_ts - interval 60 day and t.topic_tag = 'renewal_pricing') as pricing_tickets_60d,
    -- notices: surfaced to the CSM, excluded from the model
    count(t.ticket_id) filter (where t.created_at > s.as_of_ts - interval 60 day and t.topic_tag = 'cancellation') as notice_cancellation_tickets_60d,
    bool_or(coalesce(t.churn_risk_flag, false)) filter (where t.created_at > s.as_of_ts - interval 60 day) as notice_agent_flagged_risk
from s
left join t on t.tenant_id = s.tenant_id and t.account_id = s.account_id
    and t.created_at <= s.as_of_ts and t.first_known_at <= s.as_of_ts and t.created_at > s.as_of_ts - interval 180 day
group by 1, 2, 3
