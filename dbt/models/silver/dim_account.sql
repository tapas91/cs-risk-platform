-- Current state of every live (non-merged) Salesforce account. The canonical account list.
select *
from {{ ref('dim_account_history') }}
where is_current and not is_deleted
