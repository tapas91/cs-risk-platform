-- Card payment attempts, including dunning retries.
select
    c.tenant_id, c.charge_id, c.invoice_id, c.customer_id, x.account_id, c.amount_minor, c.currency,
    round(c.amount_minor / 100.0 * fx.usd_per_unit, 2) as amount_usd,
    c.status, c.failure_code, c.paid, c.created_at, c.known_at, c._source_file
from {{ ref('stg_stripe__charge') }} c
left join {{ ref('fx_rates') }} fx on fx.currency = c.currency
left join {{ ref('account_xref') }} x
    on x.tenant_id = c.tenant_id and x.source_system = 'stripe.customer' and x.source_id = c.customer_id
