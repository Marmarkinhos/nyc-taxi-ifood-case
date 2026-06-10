# dbt/models/gold/

## O que é

Camada **Gold**: 4 views dbt-databricks que respondem o case. SSoT da
lógica analítica (notebook e dashboard só consomem daqui).

- [`yellow_taxi_trips_consumption.sql`](yellow_taxi_trips_consumption.sql)
  — projeção consumível da Silver (joins com `dim_locations`, alias
  amigáveis). É a base que as outras 3 views usam via `ref()`.
- [`monthly_avg_total_amount.sql`](monthly_avg_total_amount.sql) —
  **Q1**: média mensal de `total_amount`, Jan–Mai 2023.
- [`hourly_avg_passenger_count_may.sql`](hourly_avg_passenger_count_may.sql)
  — **Q2**: média de `passenger_count` por hora em Maio 2023 (ver
  ADR-0016 sobre tratamento de NULL nativo TLC).
- [`eda_geographic.sql`](eda_geographic.sql) — EDA bônus: matriz de
  fluxo borough × borough, base do heatmap no notebook.

Tests + descrições: [`schema.yml`](schema.yml) (~20 dbt tests
hard-fail). Sources: [`../sources.yml`](../sources.yml) declara a
Silver `workspace.nyc_taxi_silver.yellow_taxi_silver` como contrato
cross-job único (ADR-0010).

## O que NÃO está aqui

- **Pipeline de ingestão (Landing/Bronze/Silver).** Vive em
  [`../../../ingestion/`](../../../ingestion/). A fronteira
  ingestão↔modelagem está na Silver: ADR-0010.
- **Camada de exibição.** Notebook em
  [`../../../notebooks/answers.py`](../../../notebooks/answers.py) e
  dashboard em
  [`../../../resources/nyc_taxi_dashboard.lvdash.json`](../../../resources/nyc_taxi_dashboard.lvdash.json).
  Ambos consomem as views daqui via `SELECT`; mudou número, muda aqui.
- **Seed `dim_locations`.** Vive em
  [`../../seeds/taxi_zone_lookup.csv`](../../seeds/taxi_zone_lookup.csv)
  (265 zonas TLC).

## Onde olhar a contraparte

- Sources (contrato Silver→Gold): [`../sources.yml`](../sources.yml)
- Schemas + tests: [`schema.yml`](schema.yml)
- Seed: [`../../seeds/taxi_zone_lookup.csv`](../../seeds/taxi_zone_lookup.csv)
- Orquestração: [`../../../resources/job_dbt.yml`](../../../resources/job_dbt.yml)
- Surfaces de consumo: "Trio de consumo" no [README raiz](../../../README.md#trio-de-consumo-cobertura-assim%C3%A9trica)
- Decisões: ADR-0009 (dim_locations no escopo), ADR-0010 (fronteira),
  ADR-0016 (passenger_count warn).
