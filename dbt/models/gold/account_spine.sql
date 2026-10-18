-- One row per (as-of date, live customer): who the model scores on each date, and what the CRM
-- said about them at that moment. A version counts only if it had happened AND reached the
-- warehouse by the as-of date (valid_from and known_at), so late updates never leak backwards.
with dates as (
    select * from {{ ref('as_of_dates') }}
),
versions as (
    select d.as_of, d.as_of_ts, d.purpose, d.data_as_of, h.*
    from dates d
    join {{ ref('dim_account_history') }} h on h.valid_from <= d.as_of_ts and h.known_at <= d.as_of_ts
    qualify row_number() over (partition by d.as_of, h.tenant_id, h.account_id order by h.valid_from desc, h.known_at desc) = 1
),
first_churn as (
    select tenant_id, account_id, min(event_at) as churned_at
    from {{ ref('account_outcomes') }} where event_type = 'churn' group by 1, 2
)
select
    v.as_of,
    v.as_of_ts,
    v.purpose,
    v.data_as_of,
    v.tenant_id,
    v.account_id,
    v.account_name,
    v.tier,
    v.owner_id,
    v.arr,
    v.currency,
    v.billing_country,
    v.contract_start_date,
    v.renewal_date is null as renewal_date_missing,
    -- next renewal: the CRM date when it's set and still ahead, otherwise the next contract anniversary
    coalesce(
        case when v.renewal_date > v.as_of then v.renewal_date end,
        (v.contract_start_date + to_years(cast(ceil(date_diff('day', v.contract_start_date, v.as_of) / 365.25) as integer)))::date
    ) as next_renewal_date,
    date_diff('day', v.contract_start_date, v.as_of) as tenure_days,
    v.known_at as account_version_known_at
from versions v
left join first_churn c on c.tenant_id = v.tenant_id and c.account_id = v.account_id
where v.account_type = 'Customer'
  and not v.is_deleted
  and not v.is_internal_test
  and v.contract_start_date <= v.as_of
  and (c.churned_at is null or c.churned_at > v.as_of_ts)
