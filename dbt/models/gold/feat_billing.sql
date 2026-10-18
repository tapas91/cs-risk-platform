-- Billing state as of each date: failed payments, past-due subscriptions and seat trend.
-- A cancel_at date on the subscription is a notice (the customer told us), kept out of the model.
with s as (select as_of, as_of_ts, tenant_id, account_id from {{ ref('account_spine') }}),
charges as (
    select s.as_of, s.tenant_id, s.account_id,
           count(c.charge_id) filter (where c.status = 'failed' and c.created_at > s.as_of_ts - interval 60 day) as failed_charges_60d,
           count(c.charge_id) filter (where c.status = 'succeeded' and c.created_at > s.as_of_ts - interval 180 day) as paid_charges_180d
    from s
    left join {{ ref('fct_charge') }} c on c.tenant_id = s.tenant_id and c.account_id = s.account_id
        and c.created_at <= s.as_of_ts and c.known_at <= s.as_of_ts and c.created_at > s.as_of_ts - interval 180 day
    group by 1, 2, 3
),
subs_now as (
    select s.as_of, s.tenant_id, s.account_id, h.subscription_id, h.status, h.seats, h.cancel_at
    from s
    join {{ ref('dim_subscription_history') }} h on h.tenant_id = s.tenant_id and h.account_id = s.account_id
        and h.valid_from <= s.as_of_ts and h.known_at <= s.as_of_ts
    qualify row_number() over (partition by s.as_of, h.tenant_id, h.subscription_id order by h.valid_from desc, h.known_at desc) = 1
),
subs_before as (
    select s.as_of, s.tenant_id, s.account_id, h.subscription_id, h.seats
    from s
    join {{ ref('dim_subscription_history') }} h on h.tenant_id = s.tenant_id and h.account_id = s.account_id
        and h.valid_from <= s.as_of_ts - interval 90 day and h.known_at <= s.as_of_ts
    qualify row_number() over (partition by s.as_of, h.tenant_id, h.subscription_id order by h.valid_from desc, h.known_at desc) = 1
),
subs as (
    select n.as_of, n.tenant_id, n.account_id,
           sum(n.seats) as subscribed_seats,
           sum(b.seats) as subscribed_seats_90d_ago,
           bool_or(n.status = 'past_due') as is_past_due,
           bool_or(n.cancel_at is not null and n.status <> 'canceled') as notice_cancel_scheduled
    from subs_now n
    left join subs_before b using (as_of, tenant_id, account_id, subscription_id)
    group by 1, 2, 3
)
select c.*, s.subscribed_seats, s.subscribed_seats_90d_ago, coalesce(s.is_past_due, false) as is_past_due,
       coalesce(s.notice_cancel_scheduled, false) as notice_cancel_scheduled
from charges c
left join subs s using (as_of, tenant_id, account_id)
