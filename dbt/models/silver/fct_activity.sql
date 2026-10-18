-- Salesforce tasks: calls, meetings, QBRs and CSM save plays.
select
    t.tenant_id, t.task_id, coalesce(a.master_account_id, t.account_id) as account_id, t.contact_id, t.owner_id,
    t.task_type, t.subject, t.subject like 'Save plan%' or t.subject like 'Executive sponsor escalation%' as is_save_play,
    t.status, t.activity_date, t.activity_date_raw, t.is_legacy_date_format, t.created_at, t.known_at, t._source_file
from {{ ref('stg_salesforce__task') }} t
left join (select distinct tenant_id, account_id, master_account_id from {{ ref('dim_account_history') }}) a
    on a.tenant_id = t.tenant_id and a.account_id = t.account_id
