-- A version must never end before it starts, in any history table.
{% for m in ['dim_account_history', 'dim_contact_history', 'dim_workspace_history', 'dim_subscription_history', 'dim_opportunity_history'] %}
select '{{ m }}' as model, valid_from, valid_to from {{ ref(m) }} where valid_to < valid_from
{% if not loop.last %}union all{% endif %}
{% endfor %}
