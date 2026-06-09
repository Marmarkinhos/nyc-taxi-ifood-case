---
status: ready-for-agent
created: 2026-06-08
tags: [dlt, bronze, silver, autoloader]
blocked-by: [03-landing-notebook.md]
blocks: [05-dlt-expectations.md, 06-job-ingestion-dab.md]
---

# 04 — DLT pipeline: Bronze (Auto Loader) + Silver canônica (sem expectations)

## What to build

Pipeline DLT (`ingestion/dlt_pipeline.py`) com 2 nodes — Bronze
streaming table + Silver materialized view — **sem expectations
ainda** (essas entram no ticket #5).

**Bronze** — `${prefix}nyc_taxi_bronze.yellow_taxi_trips_raw`:

- `@dlt.table` (streaming) lendo via Auto Loader
  (`cloudFiles`):
  - `format = parquet`
  - `cloudFiles.schemaEvolutionMode = addNewColumns`
  - `trigger = AvailableNow`
- Source: path do Volume Landing
  (`/Volumes/<catalog>/raw_data/landing/nyc_taxi/yellow/`).
- Preserva 100% das colunas TLC (sem rename/cast/drop).
- **Adiciona** colunas de metadata:
  - `_metadata.file_path`
  - `_metadata.file_modification_time`
  - `_ingestion_ts = current_timestamp()`

**Silver** — `${prefix}nyc_taxi_silver.yellow_taxi_trips`:

- `@dlt.table` (materialized view) lendo Bronze via `dlt.read()`.
- **Canônica e tipada** (ADR-0001, ADR-0005):
  - Todas as colunas TLC preservadas (sem projeção — Gold projeta
    as 5 exigidas).
  - Renomeadas pra snake_case (`VendorID` → `vendor_id`,
    `tpep_pickup_datetime` permanece, etc.).
  - Tipos canônicos forçados (INTs, DECIMAL pra valores
    monetários, TIMESTAMP pros datetimes).
- Colunas derivadas:
  - `pickup_year_month` (`YYYY-MM` de `tpep_pickup_datetime`)
  - `file_year_month` (parse de `_metadata.file_path` —
    `yellow_tripdata_YYYY-MM.parquet`, ADR-0004; reusa helper de
    `nyc_taxi_case.schema` se já criado no #02).
- `tblproperties` defensivas (ADR-0005):
  - `delta.autoOptimize.optimizeWrite = true`
  - `delta.autoOptimize.autoCompact = true`
  - `delta.tuneFileSizesForRewrites = true`
  - ZSTD compression nível alto.
- **Liquid Clustering** em `pickup_year_month` (ADR-0006) —
  NÃO `PARTITIONED BY`.

**Schema das tabelas:** criados pelo DLT na primeira execução. Não
precisa de `CREATE SCHEMA` separado se o DAB target já configura
permissões corretas.

## Acceptance criteria

- [ ] Pipeline DLT cria as 2 tabelas no UC
- [ ] Bronze é streaming table; Silver é MV
- [ ] Bronze preserva exatamente as colunas TLC + 3 metadata
- [ ] Silver tem todas as colunas TLC renomeadas pra snake_case e
      tipadas
- [ ] `pickup_year_month` e `file_year_month` materializados na
      Silver
- [ ] Liquid Clustering aplicado em `pickup_year_month`
- [ ] `tblproperties` defensivas aplicadas
- [ ] Pipeline roda standalone via `pipelines start <pipeline_id>`
      ou `bundle run` (este último depende do ticket #6 pra job
      completo — mas pipeline em si deve ser deployable
      individualmente)
- [ ] Re-run não duplica dados (idempotência Auto Loader +
      `AvailableNow`)
- [ ] Sem expectations ainda — fica pro ticket #5

## Blocked by

- `03-landing-notebook.md` (precisa de parquets no Volume pro
  Auto Loader consumir; tabela `landing_audit` não é dependência
  direta da Bronze/Silver)
