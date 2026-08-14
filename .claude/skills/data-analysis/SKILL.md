---
name: data-analysis
description: Analyze structured data from databases or project files with verified queries, explicit metric definitions, and evidence-based conclusions. Use for schema inspection, SQL analysis, KPI calculations, comparisons, trends, anomalies, and any request whose answer depends on actual data.
---

# Data Analysis

Produce reproducible analysis from real data. Never invent tables, fields, query results, or numerical conclusions.

## Workflow

1. Restate the question as measurable outputs, including entity, metric, dimensions, filters, and time range.
2. Inspect the available schema and sample only what is necessary. Do not assume field meanings from names alone when documentation is available.
3. State the metric definition before querying. Resolve ambiguous definitions or clearly label the chosen assumption.
4. Prefer read-only queries. Limit rows, select only needed columns, and aggregate in the database where practical.
5. Check totals, nulls, duplicates, date boundaries, units, and obvious outliers before accepting a result.
6. Present findings with the query scope, evidence, caveats, and a concise business interpretation.

## Database Rules

- Use the `db` MCP tools for database facts; inspect objects before executing SQL.
- Do not execute INSERT, UPDATE, DELETE, DDL, administrative commands, or stored procedures unless the user explicitly requests and authorizes the exact write operation.
- Never expose connection strings, credentials, secrets, or unrelated personal data.
- If the database is unavailable, say which connection or permission is missing and stop short of fabricating an answer.

## Output

Separate the answer into: metric definition, result, supporting evidence, interpretation, and limitations. Include SQL only when it helps review or reproduce the analysis.
