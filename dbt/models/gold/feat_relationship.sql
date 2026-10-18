-- People and coverage: is the champion still there, is anyone from our side talking to them.
-- CSM save plays are recorded but kept out of the model: they react to risk the CSM already saw.
with s as (select as_of, as_of_ts, tenant_id, account_id, owner_id from {{ ref('account_spine') }}),
contacts as (
    select s.as_of, s.tenant_id, s.account_id, h.contact_id, h.is_champion, h.email_bounced, h.inactive_date
    from s
    join {{ ref('dim_contact_history') }} h on h.tenant_id = s.tenant_id and h.account_id = s.account_id
        and h.valid_from <= s.as_of_ts and h.known_at <= s.as_of_ts
    qualify row_number() over (partition by s.as_of, h.tenant_id, h.contact_id order by h.valid_from desc, h.known_at desc) = 1
),
people as (
    select as_of, tenant_id, account_id,
           count(*) filter (where not email_bounced and (inactive_date is null or inactive_date > as_of)) as active_contacts,
           count(*) filter (where is_champion and not email_bounced and (inactive_date is null or inactive_date > as_of)) as active_champions,
           count(*) filter (where is_champion and (email_bounced or inactive_date <= as_of)) as champions_lost
    from contacts group by 1, 2, 3
),
activity as (
    select s.as_of, s.tenant_id, s.account_id,
           date_diff('day', max(a.activity_date), s.as_of) as days_since_csm_activity,
           count(a.task_id) filter (where a.activity_date > s.as_of - interval 90 day) as csm_activities_90d,
           count(a.task_id) filter (where a.is_save_play and a.activity_date > s.as_of - interval 90 day) as save_plays_90d
    from s
    left join {{ ref('fct_activity') }} a on a.tenant_id = s.tenant_id and a.account_id = s.account_id
        and a.activity_date <= s.as_of and a.known_at <= s.as_of_ts and a.activity_date > s.as_of - interval 365 day
    group by 1, 2, 3
)
select s.as_of, s.tenant_id, s.account_id, s.owner_id is null as owner_missing,
       coalesce(p.active_contacts, 0) as active_contacts, coalesce(p.active_champions, 0) as active_champions,
       coalesce(p.champions_lost, 0) as champions_lost,
       a.days_since_csm_activity, a.csm_activities_90d, a.save_plays_90d
from s
left join people p using (as_of, tenant_id, account_id)
left join activity a using (as_of, tenant_id, account_id)
