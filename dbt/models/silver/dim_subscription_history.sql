-- Stripe subscriptions by version: seat changes, past_due, cancel_at notice, cancellation.
select
    s.tenant_id, s.subscription_id, s.customer_id, x.account_id, s.plan_id, s.billing_interval, s.seats,
    s.unit_amount_minor, s.currency, s.status, s.cancel_at, s.canceled_at, s.created_at,
    {{ history_windows('s', 'subscription_id', 'modified_at') }},
    s.known_at, s._source_file
from {{ ref('stg_stripe__subscription') }} s
left join {{ ref('account_xref') }} x
    on x.tenant_id = s.tenant_id and x.source_system = 'stripe.customer' and x.source_id = s.customer_id
