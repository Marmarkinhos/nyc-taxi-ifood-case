---
status: done
created: 2026-06-08
closed: 2026-06-09
tags: [dbt, gold, model, enrichment]
blocked-by: [07-dbt-project-skeleton.md]
blocks: [09-dbt-tests.md, 10-job-dbt-dab.md, 11-dbt-analyses.md]
---

# 08 — dbt Gold model + filtro janela + enriquecimento + first-run hard-fail

## What to build

`dbt/models/gold/yellow_taxi_trips_consumption.sql` — modelo Gold
principal do case. Materialização default `view` (ADR-0011 §notas).

**Lógica:**

1. Lê `landing_audit` via `source('monitoring', 'landing_audit')`,
   filtra pelo run mais recente (`MAX(run_id)`) com
   `pipeline_update_id IS NOT NULL` (= run de ingestão completou).
   Extrai `start_year_month` + `end_year_month` desse run = janela
   ativa (ADR-0003 editado).

2. **First-run hard-fail** via Jinja:
   ```jinja
   {% set audit_check_query %}
     SELECT COUNT(*) AS n FROM {{ source('monitoring', 'landing_audit') }}
     WHERE pipeline_update_id IS NOT NULL
   {% endset %}
   {% if execute %}
     {% set result = run_query(audit_check_query) %}
     {% if result.columns[0].values()[0] == 0 %}
       {{ exceptions.raise_compiler_error(
         "nenhum run de ingestão completo registrado em landing_audit; "
         "rode `bundle run job_ingestion` primeiro"
       ) }}
     {% endif %}
   {% endif %}
   ```

3. Lê Silver via `source('silver', 'yellow_taxi_trips')`, filtra
   `pickup_year_month BETWEEN start_param AND end_param`.

4. **Projeta 5 colunas exigidas + derivadas + enriquecimento:**
   - `vendor_id`
   - `passenger_count`
   - `total_amount`
   - `tpep_pickup_datetime` AS `pickup_at`
   - `tpep_dropoff_datetime` AS `dropoff_at`
   - `pickup_year_month` (já materializada na Silver)
   - `pickup_hour` (derivada de `tpep_pickup_datetime`)
   - `pickup_location_id`, `dropoff_location_id` (renomeados de
     `PULocationID`/`DOLocationID`)
   - JOIN com `ref('dim_locations')` 2x:
     - `pickup_borough`, `pickup_zone` (via `pickup_location_id`)
     - `dropoff_borough`, `dropoff_zone` (via `dropoff_location_id`)

5. **Sem aggregation** — Gold é fato detalhado; análises do #11
   agregam por cima.

## Acceptance criteria

- [ ] Modelo materializa como view em
      `${prefix}nyc_taxi_gold.yellow_taxi_trips_consumption`
- [ ] Compila e roda com `dbt run --select yellow_taxi_trips_consumption`
- [ ] Filtra pela janela do último run completo de `landing_audit`
- [ ] First-run vazio falha hard com mensagem acionável (testável
      truncando `landing_audit` temporariamente)
- [ ] Enriquecimento com `dim_locations` produz `pickup_borough` /
      `dropoff_borough` não-nulos pra LocationIDs conhecidas (todas
      as 260 zonas do seed)
- [ ] Total de linhas = total da Silver filtrada pela janela
      (verificação manual com 1 mês)
- [ ] Default `view` aplica (sem `{{ config(materialized='table') }}`)
- [ ] Sem hardcode de `start`/`end` year_month — sempre via audit

## Blocked by

- `07-dbt-project-skeleton.md` (precisa de `sources.yml` +
  `dim_locations` seedado)

## Resolution (2026-06-09)

Entregue end-to-end. Modelo em
`dbt/models/gold/yellow_taxi_trips_consumption.sql`, materializado em
`workspace.nyc_taxi_gold.yellow_taxi_trips_consumption` (view).

**Validação:**

| Critério | Resultado |
|---|---|
| Materializa como view | ✅ |
| `dbt run --select yellow_taxi_trips_consumption` | ✅ 5.01s |
| Filtra por janela do último run completo | ✅ jan-mai 2023 |
| First-run vazio → hard-fail acionável | ✅ validado no compile |
| `pickup_borough` / `dropoff_borough` 100% non-null | ✅ 16.044.080/16.044.080 |
| Row count Gold == Silver filtrada | ✅ ambos 16.044.080 |
| Default `view` (sem `+materialized` override) | ✅ |
| Sem hardcode de start/end | ✅ via `latest_complete_run` CTE |

**Decisão refinada durante implementação:**

- `ref('dim_locations')` **não funciona** — dbt resolve `ref()` por
  node name (`taxi_zone_lookup`), não por alias. Modelo usa
  `ref('taxi_zone_lookup')` com comentário explicativo inline.

**Bug descoberto + workaround aplicado:**

`landing.py:_resolve_job_context()` retorna `"interactive"` mesmo
quando rodado via `bundle run job_ingestion`, fazendo a task 3
(`update_audit_task`) não conseguir backfillar `pipeline_update_id`
(filtro `WHERE job_run_id = '{{job.run_id}}'` não casa com
`"interactive"`). Bug não bloqueou o #08: backfillei manualmente
via SQL `UPDATE`, depois rodei `dbt run` com sucesso. Bug registrado
em ticket **#15** (`15-resolve-job-context-bug.md`), que bloqueia
#10 (`job_dbt` precisa do contrato funcionando sem UPDATE manual).

