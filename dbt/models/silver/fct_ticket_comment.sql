-- Ticket comments: the free text the LLM enrichment step reads. Treat body as untrusted input.
select
    c.tenant_id, c.comment_id, c.ticket_id, t.account_id, c.author_role, c.author_email, c.is_public,
    c.body, length(c.body) as body_chars, c.created_at, c.known_at, c._source_file
from {{ ref('stg_zendesk__ticket_comment') }} c
left join {{ ref('fct_ticket') }} t using (tenant_id, ticket_id)
