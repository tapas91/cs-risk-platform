-- Salesforce opportunities by version (new business, renewals, expansions).
select
    o.tenant_id, o.opportunity_id, coalesce(a.master_account_id, o.account_id) as account_id, o.opportunity_name,
    o.opportunity_type, o.stage_name, o.amount, o.currency, o.close_date, o.probability, o.is_closed, o.is_won,
    o.closed_lost_reason, o.owner_id, o.created_date,
    {{ history_windows('o', 'opportunity_id', 'modified_at') }},
    o.known_at, o._source_file
from {{ ref('stg_salesforce__opportunity') }} o
left join (select distinct tenant_id, account_id, master_account_id from {{ ref('dim_account_history') }}) a
    on a.tenant_id = o.tenant_id and a.account_id = o.account_id
