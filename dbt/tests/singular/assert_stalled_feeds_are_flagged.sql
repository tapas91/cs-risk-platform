-- Severity warn: lists feeds that are behind, so a run shows them without failing the build.
{{ config(severity='warn') }}
select tenant_id, source_table, hours_behind, freshness_status
from {{ ref('source_freshness') }}
where freshness_status in ('warn', 'stale')
