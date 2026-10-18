-- Account master: every source record that refers to a customer, mapped to one canonical Salesforce
-- account within its tenant. Matches never cross tenants.
--
-- Two numbers, two jobs:
--   prior_confidence (seeds/match_rule_priors.csv) sets the ORDER in which rules are tried. It is a
--     deliberate choice, changed by a person when the measurements say so.
--   confidence (ops.match_precision) is the measured trust in the rule and the GATE: a rule whose
--     confidence falls below min_match_confidence stops matching anything.
-- Ranking on measured confidence instead would let sample size pick the winner: with every rule at
-- 100% on the sample, the rule with the most labels would win on a narrower interval alone.
-- Records left without a match: ops.quarantine_identity.
{% set min_conf = var('min_match_confidence') %}

with scored as (
    select c.*, p.confidence, p.confidence_source, p.prior_confidence
    from {{ ref('account_match_candidates') }} c
    join {{ ref('match_precision') }} p using (source_system, match_method)
    where p.confidence >= {{ min_conf }}   -- the gate: an untrustworthy rule matches nothing
),

ranked as (
    select *,
           row_number() over (partition by tenant_id, source_system, source_id
                              order by prior_confidence desc, confidence desc, account_id) as rank
    from scored
)

select tenant_id, source_system, source_id, account_id, match_method, confidence, confidence_source
from ranked
where rank = 1
