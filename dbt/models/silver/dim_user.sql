-- CSMs, AEs and managers: latest version per user.
select tenant_id, user_id, user_name, email, user_role, time_zone, created_date, is_active, modified_at, known_at
from {{ ref('stg_salesforce__user') }}
qualify row_number() over (partition by tenant_id, user_id order by modified_at desc, known_at desc) = 1
