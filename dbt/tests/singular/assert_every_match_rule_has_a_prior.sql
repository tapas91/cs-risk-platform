-- A new rule in account_match_candidates must be declared in seeds/match_rule_priors.csv,
-- otherwise its matches would silently disappear from account_xref.
select distinct c.source_system, c.match_method
from {{ ref('account_match_candidates') }} c
left join {{ ref('match_rule_priors') }} p using (source_system, match_method)
where p.match_method is null
