-- Source records that refer to a customer but could not be tied to exactly one account.
-- reason: no_match (nothing matched), or a missing link we can name. These rows are excluded from
-- account-level facts until fixed, and they are counted, never silently dropped.
with refs as (
    select tenant_id, 'stripe.customer' as source_system, customer_id as source_id, customer_name as label,
           metadata_sfdc_account_id as claimed_account_id
    from {{ ref('stg_stripe__customer') }}
    union
    select tenant_id, 'zendesk.organization', organization_id, organization_name, external_id
    from {{ ref('stg_zendesk__organization') }}
    union
    select tenant_id, 'product.workspace', workspace_id, workspace_name, sfdc_account_id
    from {{ ref('stg_product__workspace') }}
)

select r.tenant_id, r.source_system, r.source_id, r.label, r.claimed_account_id,
       case when r.claimed_account_id is null then 'no_link_and_no_match' else 'claimed_id_not_found' end as reason
from refs r
left join {{ ref('account_xref') }} x using (tenant_id, source_system, source_id)
where x.account_id is null
