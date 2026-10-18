-- Churn and downsell events, read from what the source systems recorded (never from ground truth).
-- An account can have several churn records (Stripe cancellation, lost renewal, CRM status change);
-- labels use the earliest. Downsell = a subscription losing at least 20% of its seats.
with churn as (
    select tenant_id, account_id, min(canceled_at) as event_at, 'churn' as event_type, 'stripe_canceled' as evidence
    from {{ ref('dim_subscription_history') }}
    where status = 'canceled' and account_id is not null
    group by 1, 2
    union all
    select tenant_id, account_id, min(close_date)::timestamptz, 'churn', 'renewal_closed_lost'
    from {{ ref('fct_opportunity_stage_change') }}
    where opportunity_type = 'Renewal' and stage_name = 'Closed Lost'
    group by 1, 2
    union all
    select tenant_id, master_account_id, min(valid_from), 'churn', 'crm_former_customer'
    from {{ ref('dim_account_history') }}
    where account_type = 'Former Customer'
    group by 1, 2
),
seat_changes as (
    select tenant_id, account_id, valid_from, seats, status,
           lag(seats) over (partition by tenant_id, subscription_id order by valid_from, known_at) as previous_seats
    from {{ ref('dim_subscription_history') }}
    where account_id is not null
),
downsell as (
    select tenant_id, account_id, valid_from as event_at, 'downsell' as event_type, 'seats_reduced' as evidence
    from seat_changes
    where status <> 'canceled' and seats <= previous_seats * 0.8
)
select * from churn
union all
select * from downsell
