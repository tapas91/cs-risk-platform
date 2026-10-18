-- Typed, renamed view over bronze. Keeps every record once: an exact repeat (same message_id)
-- is a retried delivery, and the copy that arrived first wins.
with typed as (
    select

    _tenant_id as tenant_id,
    message_id,
    thread_id,
    lower(mailbox) as mailbox,
    direction,
    lower(from_domain) as from_domain,
    to_domains,
    cc_count,
    -- raw RFC 2822 Date header, e.g. 'Tue, 14 Jul 2026 09:00:00 +0530'
    try_strptime(sent_at, '%a, %d %b %Y %H:%M:%S %z') as sent_at,
    sent_at as sent_at_raw,
    subject,
    has_reply,
    bounce as is_bounce,
    label_ids,
    _fivetran_synced as known_at, coalesce(_fivetran_deleted, false) as is_deleted_in_source, _source_file, _ingested_at
    from {{ source('bronze', 'gmail__message') }}
)

select *
from typed
qualify row_number() over (partition by tenant_id, message_id order by known_at, _ingested_at) = 1
