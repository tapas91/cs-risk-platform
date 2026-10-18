-- Every row in bronze traces back to exactly one manifest entry, and the row counts agree.
with landed as (
    select _source_file, count(*) as n from {{ source('bronze', 'product__event') }} group by 1
    union all select _source_file, count(*) from {{ source('bronze', 'zendesk__ticket') }} group by 1
    union all select _source_file, count(*) from {{ source('bronze', 'gmail__message') }} group by 1
    union all select _source_file, count(*) from {{ source('bronze', 'stripe__charge') }} group by 1
)
select l._source_file, l.n, f.row_count
from landed l
left join {{ source('bronze', '_ingested_files') }} f on f.file = l._source_file
where f.file is null or f.row_count <> l.n
