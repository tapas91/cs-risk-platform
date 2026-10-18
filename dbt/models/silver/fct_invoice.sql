-- Stripe invoices, current state. Invoices carry no modified timestamp, so the latest status is the
-- last one received; paid_at comes from the successful charge.
with latest as (
    select * from {{ ref('stg_stripe__invoice') }}
    qualify row_number() over (partition by tenant_id, invoice_id order by known_at desc) = 1
),
charges as (
    select tenant_id, invoice_id,
           min(created_at) filter (where status = 'succeeded') as paid_at,
           count(*) filter (where status = 'failed') as failed_attempts
    from {{ ref('fct_charge') }} group by 1, 2
)

select
    i.tenant_id, i.invoice_id, i.customer_id, x.account_id, i.subscription_id, i.billing_reason,
    i.amount_due_minor, i.amount_paid_minor, i.currency,
    round(i.amount_due_minor / 100.0 * fx.usd_per_unit, 2) as amount_due_usd,
    i.period_start, i.status, i.attempt_count, coalesce(c.failed_attempts, 0) as failed_attempts,
    i.created_at, c.paid_at, i.known_at
from latest i
left join charges c using (tenant_id, invoice_id)
left join {{ ref('fx_rates') }} fx on fx.currency = i.currency
left join {{ ref('account_xref') }} x
    on x.tenant_id = i.tenant_id and x.source_system = 'stripe.customer' and x.source_id = i.customer_id
