-- What happened next: churn or downsell within the horizon after each as-of date, as recorded by
-- the source systems. label_complete is false when the horizon runs past the data date; those rows
-- are scored but never used to train or evaluate.
{% set horizon = var('label_horizon_days') %}
with s as (select as_of, as_of_ts, data_as_of, tenant_id, account_id from {{ ref('account_spine') }}),
o as (select * from {{ ref('account_outcomes') }})
select
    s.as_of, s.tenant_id, s.account_id,
    min(o.event_at) as next_event_at,
    arg_min(o.event_type, o.event_at) as next_event_type,
    arg_min(o.evidence, o.event_at) as next_event_evidence,
    min(o.event_at) is not null as label,
    s.as_of + interval {{ horizon }} day <= s.data_as_of as label_complete
from s
left join o on o.tenant_id = s.tenant_id and o.account_id = s.account_id
    and o.event_at > s.as_of_ts and o.event_at <= s.as_of_ts + interval {{ horizon }} day
group by s.as_of, s.tenant_id, s.account_id, s.data_as_of
