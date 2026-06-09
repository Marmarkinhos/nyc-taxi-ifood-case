---
status: ready-for-agent
created: 2026-06-08
tags: [notebook, dashboard, consumption, dab]
blocked-by: [11-dbt-analyses.md]
blocks: [13-readme-finalization.md]
---

# 12 — Notebook `answers.py` + AI/BI dashboard `.lvdash.json`

## What to build

Camadas de consumo visual + interativa (Decisão #8 trio + ADR
relacionados). **Modelos dbt continuam SSoT — estes só exibem.**

### `notebooks/answers.py`

Notebook Databricks (Python) que:

1. Lê os 3 modelos analytics do #11 via
   `spark.read.table("${prefix}nyc_taxi_gold.<modelo>")`.
2. Mostra cada um via `display()`:
   - Pergunta 1: `monthly_avg_total_amount` → tabela + chart
     (linha) `pickup_year_month` × `avg_total_amount`.
   - Pergunta 2: `hourly_avg_passenger_count_may` → tabela +
     chart (bar) `pickup_hour` × `avg_passenger_count`.
   - EDA: `eda_geographic` → tabela + chart (heatmap se viável).
3. Comentários em markdown (`# MAGIC %md`) explicando contexto +
   apontando pros modelos dbt como SSoT.

**Não faz SQL inline.** Não recalcula. Não consome Silver/Bronze
diretamente. Só `spark.read.table` dos analytics.

### `resources/nyc_taxi_dashboard.lvdash.json`

AI/BI dashboard versionado via DAB (Decisão #8 — "infra como
código até a ponta"):

- Datasets apontam pras 3 tabelas analytics
- 3 visualizações:
  - Line chart: `monthly_avg_total_amount`
  - Bar chart: `hourly_avg_passenger_count_may`
  - Pivot/heatmap: `eda_geographic`
- Filtros opcionais (vendor, hora) — só se trivial de adicionar
- Declarado no `databricks.yml` ou
  `resources/general_variables.yml` pra ser deployado junto com
  bundles

## Acceptance criteria

- [ ] `notebooks/answers.py` executa end-to-end em workspace
      (após `bundle run job_dbt` ter populado as tabelas analytics)
- [ ] 3 `display()` calls produzem visualizações úteis (não só
      tabelas raw)
- [ ] Comentários markdown apontam pros modelos dbt como SSoT
- [ ] Sem SQL inline; só `spark.read.table`
- [ ] `nyc_taxi_dashboard.lvdash.json` deployado via
      `bundle deploy` aparece como dashboard na UI
- [ ] 3 visualizações no dashboard renderizam corretamente
- [ ] Notebook adicionado ao bundle (visível via
      `bundle deploy`)

## Blocked by

- `11-dbt-analyses.md` (precisa das 3 tabelas analytics
  materializadas)

## Notas

- AI/BI dashboard `.lvdash.json` schema: gerar via export da UI
  Databricks (criar dashboard manualmente → "Export as JSON") e
  versionar.
- Genie e DuckDB **descartados conscientemente** (Decisão #8 +
  CONTEXT.md §NÃO-objetivos).
