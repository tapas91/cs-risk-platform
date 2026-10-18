select * from {{ ref('match_precision') }} where confidence < 0 or confidence > 1 or confidence is null
