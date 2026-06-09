---
status: done
created: 2026-06-08
closed: 2026-06-09
tags: [landing, audit, ingestion]
blocked-by: [02-repo-skeleton-helpers-ci.md]
blocks: [04-dlt-bronze-silver-canonica.md]
---

# 03 — Landing notebook + `landing_audit`

## Resolution (2026-06-09)

Delivered: `ingestion/landing.py` (Spark/IO entry point) + three pure
helpers `nyc_taxi_case.{landing_paths,audit,probe}` with 50 new unit
tests (99 total, 99% coverage on `src/`).

**Departures from the original ticket text:**

- Used existing `nyc_taxi_case.window.expand_window`; the ticket
  referenced `list_months` which never existed.
- Volume path follows `general_variables.yml` single-source-of-truth
  (`/Volumes/${catalog}/${bronze_schema}/landing/yellow/...`), not the
  `raw_data/landing/nyc_taxi/yellow/...` path the ticket sketched.
  General_variables wins; ticket text was stale vs ADR-0008 fan-out.
- Audit row implements the **17-column ADR-0008 schema** (the ticket
  listed a partial subset); column `source_mode` (per ADR-0008), not
  `landing_mode` (the ticket's draft name).
- Acceptance criterion "Notebook executável standalone via
  `databricks workflows submit`" deferred to **ticket #06** (Free
  Edition is serverless-only; the DAB job wires `spark_python_task`).
  The Spark-free orchestration seams (`_process_month`,
  `_audit_row_to_spark_row`) are exhaustively pytested instead.
- CI bundle-validate job removed in this ticket — `bundle validate`
  always calls SCIM `/Me` and Free Edition cannot use service
  principals. See `.github/workflows/ci.yml` comment block.

## What to build

## What to build

Notebook `ingestion/landing.py` (executado como `spark_python_task`)
que baixa parquets TLC pra Volume UC e escreve linha de audit.

**Fluxo:**

1. Lê args `--start_year_month` + `--end_year_month` via
   `dbutils.widgets` (defaults: último mês fechado).
2. Pra cada mês na janela inclusiva (usa
   `nyc_taxi_case.window.list_months`):
   - **Probe HEAD 5s** na URL TLC (ADR-0002). Decide
     `landing_mode`:
     - `HTTP` se status 200 — baixa via `requests.get` byte-a-byte
       (md5 preservado).
     - `VOLUME_PREEXISTING` se 404/timeout — apenas valida que o
       arquivo já existe no Volume (fallback documentado em
       CONTEXT.md).
   - Escreve em
     `/Volumes/<catalog>/raw_data/landing/nyc_taxi/yellow/
     year=YYYY/month=MM/yellow_tripdata_YYYY-MM.parquet`.
3. Ao final, INSERT uma linha em
   `${prefix}monitoring.landing_audit` com schema do ADR-0008
   (`run_id`, `job_start_ts`, `job_end_ts`, `start_year_month`,
   `end_year_month`, `landing_mode`, `bytes_downloaded`,
   `bytes_total_in_volume`, `months_skipped`, `job_run_id`,
   `job_url`, `pipeline_update_id=NULL` — preenchido depois pelo
   SQL task do ticket #6).

**Criação da tabela audit:** primeiro run cria via
`CREATE TABLE IF NOT EXISTS` com schema do ADR-0008. Schema é
load-bearing — qualquer mudança vira breaking change (consumido
pelo Gold via `sources.yml` no ticket #8).

**Não inclui** Bronze/Silver/DLT — só landing + audit pre-Bronze.

## Acceptance criteria

- [ ] Notebook executável standalone via `databricks workflows
      submit` (ou equivalente) com args de janela
- [ ] Probe HEAD funciona contra TLC CloudFront (validado em
      2026-06-08 com status 200 / 0.10s — CONTEXT.md)
- [ ] Path no Volume segue `year=YYYY/month=MM/` Hive-partitioned
- [ ] Conteúdo do parquet é byte-idêntico ao baixado da TLC
      (md5 preservável)
- [ ] Tabela `${prefix}monitoring.landing_audit` criada com schema
      ADR-0008 completo
- [ ] 1 linha inserida na audit por run, com `pipeline_update_id`
      NULL (preenchido depois)
- [ ] `landing_mode` registrado corretamente (HTTP vs
      VOLUME_PREEXISTING) baseado no probe
- [ ] Fallback `VOLUME_PREEXISTING` testado pelo menos
      manualmente (uploadar parquet fora do notebook +
      forçar 404 mock no probe)
- [ ] Não consome `nyc_taxi_case.schema` ainda (validação de
      colunas é problema da Bronze/DLT — só verifica que o arquivo
      aterrissou)

## Blocked by

- `02-repo-skeleton-helpers-ci.md` (precisa de `nyc_taxi_case.window`
  + `tlc_urls`)
