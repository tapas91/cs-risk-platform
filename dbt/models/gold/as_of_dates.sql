-- The dates the model looks at the world from.
--   train: first of every month whose 90-day outcome window has fully passed by the data date
--   score: the data date and the 13 weeks before it, 7 days apart (for week-on-week movement)
-- data_as_of is the newest arrival in the warehouse, not the clock: this dataset is a fixed dump.
{% set horizon = var('label_horizon_days') %}
with watermark as (
    select max(known_at)::date as data_as_of from {{ ref('fct_product_event') }}
),
train as (
    select unnest(generate_series(date '{{ var("first_training_as_of") }}',
                                  (select data_as_of from watermark) - interval {{ horizon }} day,
                                  interval 1 month))::date as as_of, 'train' as purpose
),
score as (
    select unnest(generate_series((select data_as_of from watermark) - interval 91 day,
                                  (select data_as_of from watermark), interval 7 day))::date as as_of, 'score' as purpose
)
select as_of, purpose, cast(as_of as timestamptz) as as_of_ts, (select data_as_of from watermark) as data_as_of
from (select * from train union all select * from score)
