-- Source records that refer to a customer but could not be tied to exactly one account.
-- reason: no_match (nothing matched), or a missing link we can name. These rows are excluded from
-- account-level facts until fixed, and they are counted, never silently dropped.
with refs as (
    select tenant_id, 'stripe.customer' as source_system, customer_id as source_id, customer_name as label,
           metadata_sfdc_account_id as claimed_account_id, email
    from {{ ref('stg_stripe__customer') }}
    union
    select tenant_id, 'zendesk.organization', organization_id, organization_name, external_id, null
    from {{ ref('stg_zendesk__organization') }}
    union
    select tenant_id, 'product.workspace', workspace_id, workspace_name, sfdc_account_id, null
    from {{ ref('stg_product__workspace') }}
),
shared_emails as (  -- the contact-email rule skips these (see account_match_candidates)
    select tenant_id, email from {{ ref('dim_contact_history') }}
    group by 1, 2 having count(distinct account_id) > 1
)

select r.tenant_id, r.source_system, r.source_id, r.label, r.claimed_account_id,
       case when r.claimed_account_id is not null then 'claimed_id_not_found'
            when s.email is not null then 'ambiguous_contact_email'
            else 'no_link_and_no_match' end as reason
from refs r
left join {{ ref('account_xref') }} x using (tenant_id, source_system, source_id)
left join shared_emails s on s.tenant_id = r.tenant_id and s.email = r.email
where x.account_id is null
