-- Each stage move on an opportunity: the pre-sales funnel and the renewal timeline.
with v as (
    select *, lag(stage_name) over (partition by tenant_id, opportunity_id order by valid_from, known_at) as previous_stage
    from {{ ref('dim_opportunity_history') }}
)

select tenant_id, opportunity_id, account_id, opportunity_type, previous_stage, stage_name, amount, currency,
       close_date, closed_lost_reason, valid_from as changed_at, known_at
from v
where previous_stage is distinct from stage_name
