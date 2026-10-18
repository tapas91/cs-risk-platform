{# Use the folder's schema name as-is (staging, silver, ops, reference) instead of dbt's default prefixing. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
