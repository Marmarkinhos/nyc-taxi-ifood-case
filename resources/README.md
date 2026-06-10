# resources/

## O que é

[Databricks Asset Bundle](https://docs.databricks.com/dev-tools/bundles/)
(DAB) resources: a definição declarativa de tudo que é deployado pro
workspace por `databricks bundle deploy`. Entry-point é
[`../databricks.yml`](../databricks.yml) na raiz, que inclui esses
arquivos via `include:`.

Arquivos:

- [`job_ingestion.yml`](job_ingestion.yml) — job DAB com 4 tasks
  (download HTTP, DLT pipeline, audit backfill, monitoring view).
- [`job_dbt.yml`](job_dbt.yml) — job DAB com 1 task que roda
  `dbt deps → seed → run → test`.
- [`dlt_pipeline.yml`](dlt_pipeline.yml) — Lakeflow Declarative
  Pipeline (Bronze + Silver) referenciado por `job_ingestion`.
- [`dashboard.yml`](dashboard.yml) — Lakeview AI/BI dashboard
  (Q1 + Q2), arquivo serializado em
  [`nyc_taxi_dashboard.lvdash.json`](nyc_taxi_dashboard.lvdash.json).
- [`general_variables.yml`](general_variables.yml) — variáveis DAB
  compartilhadas (catalog, schemas, paths de Volume, warehouse id).

Os 2 jobs são **independentes** (zero `depends_on` entre eles) por
escolha arquitetural: ADR-0011.

## O que NÃO está aqui

- **Código source.** Notebooks/Python vivem em
  [`../ingestion/`](../ingestion/) e [`../notebooks/`](../notebooks/);
  dbt models em [`../dbt/`](../dbt/). DAB só referencia.
- **Targets** (`user_dev`, `production`, etc). Estão em
  [`../databricks.yml`](../databricks.yml). Default deste case é
  `--target user_dev`.

## Onde olhar a contraparte

- Entry-point DAB: [`../databricks.yml`](../databricks.yml)
- Código referenciado pelos jobs: [`../ingestion/`](../ingestion/),
  [`../notebooks/`](../notebooks/), [`../dbt/`](../dbt/)
- Como rodar: [`../docs/RUNBOOK.md`](../docs/RUNBOOK.md) +
  "Reproduzir" no [README raiz](../README.md#reproduzir-num-workspace-free-edition)
- Decisões: ADR-0011 (2 jobs independentes), ADR-0012 (self-bootstrap).
