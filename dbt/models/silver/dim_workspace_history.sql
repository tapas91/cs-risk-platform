-- Product workspaces by version (trial -> paid -> canceled, seat changes).
select
    w.tenant_id, w.workspace_id, x.account_id, w.workspace_name, w.plan, w.seats_purchased, w.status, w.created_at,
    {{ history_windows('w', 'workspace_id', 'modified_at') }},
    w.known_at, w._source_file
from {{ ref('stg_product__workspace') }} w
left join {{ ref('account_xref') }} x
    on x.tenant_id = w.tenant_id and x.source_system = 'product.workspace' and x.source_id = w.workspace_id
