# ingestion/

## O que é

Lado da ingestão do pipeline: **Landing → Bronze → Silver canônica**.
Dois arquivos source executados como tasks do `job_ingestion` DAB:

- [`landing.py`](landing.py) — notebook task que baixa parquet TLC via
  HTTP pro Volume UC. Self-bootstrap de schema/volume (ADR-0012).
- [`dlt_pipeline.py`](dlt_pipeline.py) — Lakeflow Declarative Pipeline
  que materializa Bronze (Streaming Table) e Silver canônica
  (Materialized View) via Auto Loader + 7 expectations warn-only.

Plus [`sql/`](sql/) (2 tasks SQL: monitoring view + audit backfill) e
[`tests/`](tests/) (pytest do contrato externo + helpers).

## O que NÃO está aqui

- **Helpers puros (sem Spark, sem IO).** Vivem em
  [`src/nyc_taxi_case/`](../src/nyc_taxi_case/) pra serem importáveis
  por `landing.py`, `dlt_pipeline.py` e pelos tests sem precisar de
  cluster.
- **Camada Gold + análises.** Vivem em [`dbt/`](../dbt/). A fronteira
  ingestão↔modelagem está na Silver (ADR-0010); dbt lê via
  `sources.yml`.
- **Orquestração e parâmetros (cluster, schedule, env).** Vivem em
  [`resources/job_ingestion.yml`](../resources/job_ingestion.yml) e
  [`resources/dlt_pipeline.yml`](../resources/dlt_pipeline.yml).

## Onde olhar a contraparte

- Helpers puros: [`../src/nyc_taxi_case/`](../src/nyc_taxi_case/)
- Tests da ingestão: [`tests/`](tests/)
- Orquestração: [`../resources/`](../resources/)
- Decisões: ADR-0001 (Silver canônica), ADR-0010 (fronteira),
  ADR-0012 (self-bootstrap), ADR-0013 a ADR-0016 (drift TLC).
