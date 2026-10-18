-- Salesforce contacts by version; account_id is resolved through merges to the canonical account.
select
    c.tenant_id,
    c.contact_id,
    coalesce(a.master_account_id, c.account_id) as account_id,
    c.first_name,
    c.last_name,
    c.email,
    {{ email_domain('c.email') }} as email_domain,
    c.title,
    c.contact_role,
    c.is_champion,
    c.created_date,
    c.inactive_date,
    c.email_bounced,
    {{ history_windows('c', 'contact_id', 'modified_at') }},
    c.known_at,
    c._source_file
from {{ ref('stg_salesforce__contact') }} c
left join (select distinct tenant_id, account_id, master_account_id from {{ ref('dim_account_history') }}) a
    on a.tenant_id = c.tenant_id and a.account_id = c.account_id
