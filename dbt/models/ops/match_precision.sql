-- How often each match rule picks the right account, measured on the labeled sample
-- (seeds/identity_labels.csv). Every candidate a labeled record produced counts, not only the winner,
-- so a rule is measured even where a stronger rule beat it.
--
-- confidence = the lower bound of the 95% interval on measured precision, once the rule has at least
-- min_labels_per_rule labels; the rule's prior before that. The lower bound rather than the plain
-- ratio keeps a rule with few labels from outranking one with many.
{% set min_n = var('min_labels_per_rule') %}

with labeled as (
    select c.source_system, c.match_method, c.account_id = l.true_account_id as is_correct
    from {{ ref('account_match_candidates') }} c
    join {{ ref('identity_labels') }} l using (tenant_id, source_system, source_id)
),

measured as (
    select source_system, match_method, count(*) as n_labeled, count(*) filter (where is_correct) as n_correct
    from labeled
    group by 1, 2
)

select
    p.source_system,
    p.match_method,
    p.rule,
    p.prior_confidence,
    coalesce(m.n_labeled, 0) as n_labeled,
    coalesce(m.n_correct, 0) as n_correct,
    round(m.n_correct::double / m.n_labeled, 4) as measured_precision,
    round({{ wilson_lower('m.n_correct', 'm.n_labeled') }}, 4) as precision_lower_95,
    case when m.n_labeled >= {{ min_n }} then round({{ wilson_lower('m.n_correct', 'm.n_labeled') }}, 4)
         else p.prior_confidence end as confidence,
    case when m.n_labeled >= {{ min_n }} then 'measured' else 'prior' end as confidence_source
from {{ ref('match_rule_priors') }} p
left join measured m using (source_system, match_method)
