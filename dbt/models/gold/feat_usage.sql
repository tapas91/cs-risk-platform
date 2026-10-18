-- Product usage as of each date. Windows end at the as-of date; an event counts only if the
-- warehouse had received it by then (known_at), so a late batch can't improve a past score.
with s as (select as_of, as_of_ts, tenant_id, account_id from {{ ref('account_spine') }}),
e as (select * from {{ ref('fct_product_event') }} where account_id is not null)
select
    s.as_of, s.tenant_id, s.account_id,
    count(e.event_id) filter (where e.event_time > s.as_of_ts - interval 30 day) as usage_events_30d,
    count(e.event_id) filter (where e.event_time <= s.as_of_ts - interval 30 day and e.event_time > s.as_of_ts - interval 90 day) as usage_events_prior_60d,
    count(distinct e.user_hash) filter (where e.event_time > s.as_of_ts - interval 30 day) as active_users_30d,
    count(distinct e.user_hash) filter (where e.event_time <= s.as_of_ts - interval 30 day and e.event_time > s.as_of_ts - interval 90 day) as active_users_prior_60d,
    count(e.event_id) filter (where e.event_time > s.as_of_ts - interval 30 day and e.event_name = 'export.run') as exports_30d,
    count(e.event_id) filter (where e.event_time > s.as_of_ts - interval 30 day and e.export_status = 'failed') as failed_exports_30d,
    count(e.event_id) filter (where e.event_time > s.as_of_ts - interval 90 day
                              and e.event_name in ('report.create', 'dashboard.share', 'integration.connect')) as value_events_90d,
    count(e.event_id) filter (where e.event_time > s.as_of_ts - interval 90 day and e.event_name = 'seat.remove') as seat_removals_90d,
    count(e.event_id) filter (where e.event_time > s.as_of_ts - interval 90 day and e.event_name = 'settings.update') as admin_changes_90d,
    date_diff('day', max(e.event_time), s.as_of_ts) as days_since_last_usage
from s
left join e on e.tenant_id = s.tenant_id and e.account_id = s.account_id
    and e.event_time <= s.as_of_ts and e.known_at <= s.as_of_ts and e.event_time > s.as_of_ts - interval 180 day
group by s.as_of, s.tenant_id, s.account_id, s.as_of_ts
