-- Company domains that point at exactly one live account in a tenant. Personal mailbox domains and
-- domains shared by two live accounts (an unmerged duplicate) are left out on purpose.
with domains as (
    select tenant_id, website_domain as domain, account_id from {{ ref('dim_account') }} where website_domain is not null
    union
    select c.tenant_id, c.email_domain, c.account_id
    from {{ ref('dim_contact_history') }} c
    join {{ ref('dim_account') }} a on a.tenant_id = c.tenant_id and a.account_id = c.account_id
    where c.is_current
)

select tenant_id, domain, min(account_id) as account_id
from domains
where domain not in (select domain from {{ ref('personal_email_domains') }})
  and domain not in (select internal_domain from {{ ref('tenants') }})
group by tenant_id, domain
having count(distinct account_id) = 1
