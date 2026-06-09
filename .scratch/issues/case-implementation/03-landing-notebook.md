---
status: ready-for-agent
created: 2026-06-08
tags: [landing, audit, ingestion]
blocked-by: [02-repo-skeleton-helpers-ci.md]
blocks: [04-dlt-bronze-silver-canonica.md]
---

# 03 — Landing notebook + `landing_audit`

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
