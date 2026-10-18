-- One row per (as-of date, live customer): every model input, the notices kept beside them, and the
-- watermark of the data the row was built from. The model reads this table; so does the trace view.
with s as (select * from {{ ref('account_spine') }})
select
    s.as_of, s.purpose, s.tenant_id, s.account_id, s.account_name, s.owner_id, s.tier, s.arr, s.currency,
    s.next_renewal_date, s.renewal_date_missing,
    -- account
    s.tenure_days,
    date_diff('day', s.as_of, s.next_renewal_date) as days_to_renewal,
    s.tenure_days < 90 as is_new_customer,
    -- usage
    coalesce(u.usage_events_30d, 0) as usage_events_30d,
    coalesce(u.usage_events_prior_60d, 0) as usage_events_prior_60d,
    -- 30-day usage against the monthly average of the 60 days before it; NULL when there is no baseline
    round(u.usage_events_30d / nullif(u.usage_events_prior_60d / 2.0, 0), 3) as usage_trend,
    coalesce(u.active_users_30d, 0) as active_users_30d,
    round(u.active_users_30d / nullif(b.subscribed_seats, 0), 3) as seat_utilisation,
    round(u.active_users_30d / nullif(u.active_users_prior_60d, 0), 3) as active_user_trend,
    coalesce(u.exports_30d, 0) as exports_30d,
    round(u.exports_30d / nullif(u.usage_events_30d, 0), 3) as export_share_30d,
    coalesce(u.failed_exports_30d, 0) as failed_exports_30d,
    coalesce(u.value_events_90d, 0) as value_events_90d,
    coalesce(u.seat_removals_90d, 0) as seat_removals_90d,
    coalesce(u.admin_changes_90d, 0) as admin_changes_90d,
    u.days_since_last_usage,
    -- support
    coalesce(t.tickets_30d, 0) as tickets_30d,
    coalesce(t.tickets_90d, 0) as tickets_90d,
    coalesce(t.urgent_tickets_90d, 0) as urgent_tickets_90d,
    coalesce(t.incident_tickets_90d, 0) as incident_tickets_90d,
    coalesce(t.open_tickets, 0) as open_tickets,
    coalesce(t.bad_csat_90d, 0) as bad_csat_90d,
    coalesce(t.good_csat_90d, 0) as good_csat_90d,
    t.avg_resolution_hours_90d,
    coalesce(t.data_export_tickets_60d, 0) as data_export_tickets_60d,
    coalesce(t.pricing_tickets_60d, 0) as pricing_tickets_60d,
    -- email
    coalesce(m.emails_out_90d, 0) as emails_out_90d,
    coalesce(m.emails_in_90d, 0) as emails_in_90d,
    round(m.emails_in_90d / nullif(m.emails_out_90d, 0), 3) as email_response_ratio_90d,
    coalesce(m.email_bounces_90d, 0) as email_bounces_90d,
    m.days_since_customer_email,
    -- billing
    coalesce(b.failed_charges_60d, 0) as failed_charges_60d,
    b.is_past_due,
    b.subscribed_seats,
    round(b.subscribed_seats / nullif(b.subscribed_seats_90d_ago, 0), 3) as seat_trend_90d,
    -- relationship
    r.owner_missing,
    r.active_contacts,
    r.active_champions,
    r.champions_lost,
    r.days_since_csm_activity,
    coalesce(r.csm_activities_90d, 0) as csm_activities_90d,
    -- data coverage: how many sources said anything in the last 90 days
    (coalesce(u.usage_events_30d + u.usage_events_prior_60d, 0) > 0)::int
      + (coalesce(t.tickets_90d, 0) > 0)::int
      + (coalesce(m.emails_out_90d + m.emails_in_90d, 0) > 0)::int as sources_with_signal_90d,
    -- notices and CSM actions: shown to the CSM, never model inputs
    coalesce(t.notice_cancellation_tickets_60d, 0) > 0 as notice_cancellation_request,
    coalesce(t.notice_agent_flagged_risk, false) as notice_agent_flagged_risk,
    coalesce(b.notice_cancel_scheduled, false) as notice_cancel_scheduled,
    coalesce(r.save_plays_90d, 0) as save_plays_90d,
    -- lineage
    s.as_of_ts as feature_cutoff,
    s.data_as_of
from s
left join {{ ref('feat_usage') }} u using (as_of, tenant_id, account_id)
left join {{ ref('feat_support') }} t using (as_of, tenant_id, account_id)
left join {{ ref('feat_email') }} m using (as_of, tenant_id, account_id)
left join {{ ref('feat_billing') }} b using (as_of, tenant_id, account_id)
left join {{ ref('feat_relationship') }} r using (as_of, tenant_id, account_id)
