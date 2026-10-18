-- Rows whose timestamps or dates could not be parsed. Kept here so a format change is noticed.
select tenant_id, 'gmail.message' as source_table, message_id as record_id, 'sent_at' as field, sent_at_raw as raw_value, _source_file
from {{ ref('stg_gmail__message') }} where sent_at is null
union all
select tenant_id, 'salesforce.task', task_id, 'activity_date', activity_date_raw, _source_file
from {{ ref('stg_salesforce__task') }} where activity_date is null and activity_date_raw is not null
