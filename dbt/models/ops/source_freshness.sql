-- How far behind each feed is, per tenant. "As of" is the newest sync seen anywhere for that tenant,
-- so a static demo dataset still shows which feed stopped while the others kept arriving.
{% set tables = ['salesforce__account', 'salesforce__contact', 'salesforce__opportunity', 'salesforce__task',
                 'zendesk__organization', 'zendesk__ticket', 'zendesk__ticket_comment', 'stripe__customer',
                 'stripe__subscription', 'stripe__invoice', 'stripe__charge', 'product__workspace',
                 'product__event', 'gmail__message'] %}
with per_table as (
    {% for t in tables %}
    select _tenant_id as tenant_id, '{{ t }}' as source_table, max(_fivetran_synced) as last_synced_at,
           max(_ingested_at) as last_ingested_at, count(distinct _source_file) as files, count(*) as rows_landed
    from {{ source('bronze', t) }} group by 1
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),
scored as (
    select p.*,
           max(last_synced_at) over (partition by tenant_id) as tenant_as_of,
           date_diff('hour', last_synced_at, max(last_synced_at) over (partition by tenant_id)) as hours_behind,
           r.warn_after_hours, r.error_after_hours
    from per_table p
    left join {{ ref('freshness_rules') }} r using (source_table)
)

select *,
       case when error_after_hours is null then 'not_monitored'
            when hours_behind >= error_after_hours then 'stale'
            when hours_behind >= warn_after_hours then 'warn'
            else 'ok' end as freshness_status
from scored
