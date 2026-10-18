{# Company name reduced to a matching key: lowercase, no legal suffix, no punctuation or spaces.
   "Pellucid Freight, Inc." / "PELLUCID FREIGHT" / "PellucidFreight (Inc.)" -> "pellucidfreight" #}
{% macro name_key(col) -%}
regexp_replace(
  regexp_replace(
    regexp_replace(lower({{ col }}), '\(.*?\)', '', 'g'),
    '\b(incorporated|inc|llc|corp|corporation|ltd|limited|plc|gmbh|ag|b\.v|bv|kg|co)\b\.?', '', 'g'),
  '[^a-z0-9]', '', 'g')
{%- endmacro %}

{% macro email_domain(col) -%}
lower(split_part({{ col }}, '@', 2))
{%- endmacro %}

{# Validity windows for a versioned entity. valid_* is source time (when it changed);
   known_at is when the warehouse received that version. Point-in-time reads need both. #}
{% macro history_windows(alias, key_col, version_col) -%}
    {%- set w = "partition by " ~ alias ~ ".tenant_id, " ~ alias ~ "." ~ key_col ~ " order by " ~ alias ~ "." ~ version_col ~ ", " ~ alias ~ ".known_at" %}
    {{ alias }}.{{ version_col }} as valid_from,
    lead({{ alias }}.{{ version_col }}) over ({{ w }}) as valid_to,
    lead({{ alias }}.{{ version_col }}) over ({{ w }}) is null as is_current
{%- endmacro %}

{# A column that only appears in later files (schema drift). Until bronze has it, read a typed NULL
   so silver builds the same way before and after the column lands. #}
{% macro optional_column(relation, column, data_type) -%}
    {%- set present = [] -%}
    {%- if execute -%}
        {%- set present = adapter.get_columns_in_relation(relation) | map(attribute='name') | map('lower') | list -%}
    {%- endif -%}
    {%- if column | lower in present -%}{{ column }}{%- else -%}cast(null as {{ data_type }}){%- endif -%}
{%- endmacro %}

{# Lower end of the 95% Wilson interval for k successes in n trials. A rule that went 30 for 30 scores
   about 0.89, not 1.0: few labels earn less trust than many. #}
{% macro wilson_lower(k, n, z=1.96) -%}
    (({{ k }}::double / {{ n }}) + {{ z }}^2 / (2 * {{ n }})
     - {{ z }} * sqrt((({{ k }}::double / {{ n }}) * (1 - {{ k }}::double / {{ n }}) + {{ z }}^2 / (4 * {{ n }})) / {{ n }}))
    / (1 + {{ z }}^2 / {{ n }})
{%- endmacro %}
