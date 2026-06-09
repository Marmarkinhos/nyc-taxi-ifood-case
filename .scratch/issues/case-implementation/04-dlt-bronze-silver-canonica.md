---
status: done
created: 2026-06-08
closed: 2026-06-09
tags: [dlt, bronze, silver, autoloader]
blocked-by: [03-landing-notebook.md]
blocks: [05-dlt-expectations.md, 06-job-ingestion-dab.md]
---

# 04 — DLT pipeline: Bronze (Auto Loader) + Silver canônica (sem expectations)

## Resolution (2026-06-09)

Delivered: `ingestion/dlt_pipeline.py` (2 DLT nodes — Bronze
Streaming Table + Silver Materialized View) + new Spark-free helper
`nyc_taxi_case.tlc_schema` with 17 unit tests (116 total, 99 % line
coverage on `src/`).

**Architectural shape:**

- **Bronze** (`yellow_taxi_trips_raw`, streaming): Auto Loader reads
  ``${var.landing_volume_path}``, ``cloudFiles.format=parquet``,
  ``schemaEvolutionMode=addNewColumns``, ``inferColumnTypes=true``.
  Selects ``*`` plus 3 metadata columns
  (``_source_file_path``, ``_source_file_modification_time``,
  ``_ingestion_ts = current_timestamp()``). No rename, no cast, no drop
  (ADR-0001).
- **Silver** (`yellow_taxi_trips`, MV): projection built dynamically
  from `TLC_RENAME_MAP` / `canonical_type` so a TLC schema change
  surfaces at the helper boundary (pinned by `test_tlc_schema.py`)
  instead of as a runtime CAST failure. Adds `pickup_year_month`
  (`date_format(tpep_pickup_datetime, 'yyyy-MM')`, ADR-0003) and
  `file_year_month` (`regexp_extract` reusing
  `nyc_taxi_case.schema.FILE_YEAR_MONTH_PATTERN`, ADR-0004).
  `cluster_by=["pickup_year_month"]` (ADR-0006) + defensive
  `tblproperties` (ADR-0005).

**Departures from / additions to the ticket text:**

- **Helper extracted** (`src/nyc_taxi_case/tlc_schema.py`): the rename
  map + canonical type map live in a Spark-free module, not inline in
  the DLT file. Reason: the maps are load-bearing for both Silver
  (this ticket) and the Bronze warn-only expectation #7-bronze
  (ticket #05); a CI-time pytest catches schema drift at PR review
  instead of at midnight on a Databricks job. ~16 LOC of helper +
  150 LOC of tests, all Spark-free.
- **Schema validated empirically** against
  `yellow_tripdata_2023-01.parquet` (3,066,766 rows, 19 columns).
  Surprises caught and pinned:
  - `passenger_count`, `RatecodeID` arrive as **`double`** in the
    source (Arrow widens NULL-bearing integer columns); the canonical
    Silver type is **BIGINT** and the CAST round-trips cleanly. Test
    `test_integer_ids_widened_in_source_are_canonicalised_to_bigint`
    pins the fact + rationale.
  - All 9 money columns are `double` in the source; canonical type is
    `DECIMAL(10, 2)` to avoid float accumulation on EDA sums.
- **Bronze metadata propagation:** `_metadata.file_path` aliased to
  `_source_file_path` at Bronze level so the Silver SQL does not have
  to re-reach into the `_metadata` struct (and so a Bronze table SELECT
  is self-contained for audit/debug).
- **Bronze tblproperties:** added `autoOptimize.optimizeWrite` +
  `autoCompact` even though Bronze is streaming-append-only. Rationale
  (commented inline): helps SQL Warehouse listing perf, does not
  change streaming semantics. ADR-0005 only specifies these for
  Silver; Bronze inherits the same pair as a defensive default.
- **`schemaEvolutionMode=addNewColumns`** chosen over `rescue` /
  `failOnNewColumns`. Justification inline: TLC has added columns
  silently in the past (`airport_fee` showed up in 2022, per
  ADR-0007 §Context); `addNewColumns` materialises them on Bronze
  (loud schema diff) but the Silver projection ignores anything not
  in `TLC_RENAME_MAP` so the pipeline does not break.
- **No DAB pipeline definition.** The ticket asks for the pipeline to
  be "deployable individually"; that wiring lives in `resources/`
  (`pipeline.yml`) and is ticket **#06**'s scope. This file is the
  pure Python module the pipeline will reference.
- **Liquid Clustering as first attempt** (ADR-0006). Fallback to
  `partition_cols=["pickup_year_month"]` documented inline in the
  Silver `@dlt.table` block; only discoverable at runtime in
  Databricks.
- **ZSTD nivel alto via `tblproperties` not applied** — DLT does not
  expose codec-level overrides on managed tables. ADR-0005 §Decision
  item 1 explicitly authorises the fallback ("level 9+ … se DLT
  permitir override; fallback aceita default"). The
  `autoOptimize/autoCompact/tuneFileSizesForRewrites` triple does the
  storage-shrinking work in practice. Comment in the file records the
  trade-off.

**Out of scope (confirmed in later tickets):**

- 6 Silver + 1 Bronze expectations → **#05**.
- `resources/job_ingestion.yml` DAB that wires landing notebook → DLT
  pipeline → post-DLT SQL update of `landing_audit.pipeline_update_id`
  → **#06**.

**Validation:** `ruff check ✅ / ruff format ✅ / mypy --strict src/ ✅
/ pytest 116 passed / 99 % line coverage`. DLT pipeline cannot run
locally (no Spark / no `dlt` module); next exercise is a
`bundle deploy + bundle run` once #06 lands.

**Files touched:**

- `src/nyc_taxi_case/tlc_schema.py` (new)
- `ingestion/tests/test_tlc_schema.py` (new, 17 tests)
- `ingestion/dlt_pipeline.py` (new)
- `.gitignore` (ignore `yellow_tripdata_*.parquet` samples + `uv.lock`)

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
