-- The account master never links a record to an account in another tenant.
select x.*
from {{ ref('account_xref') }} x
left join {{ ref('dim_account') }} a on a.tenant_id = x.tenant_id and a.account_id = x.account_id
where a.account_id is null
