---
status: ready-for-agent
created: 2026-06-08
tags: [dbt, skeleton, sources, seed, dim]
blocked-by: [06-job-ingestion-dab.md]
blocks: [08-dbt-gold-model.md]
---

# 07 — dbt project skeleton + `sources.yml` + seed `dim_locations`

## What to build

Esqueleto do projeto dbt no monorepo + contrato com Silver via
`sources.yml` + seed da `dim_locations` em schema gold.

**Estrutura:**

```
dbt/
  dbt_project.yml          # default materialization: view
  profiles.yml             # databricks profile (catalog + schema gold)
  models/
    sources.yml            # silver.yellow_taxi_trips + monitoring.landing_audit
  seeds/
    taxi_zone_lookup.csv   # TLC zone lookup (260 zonas)
  packages.yml             # vazio ou dbt_utils se precisar
```

**`dbt_project.yml`:**

- `name: nyc_taxi`
- `+materialized: view` como default global (ADR-0011 §notas)
- `seeds: +schema: gold`, `+column_types: {location_id: int}` pro
  seed (ADR-0009 editado)
- `models: +schema: gold` (single schema; `job_dbt` só escreve em
  gold — ADR-0011 invariante)
- **Sem convenção `_int_`/`_fin_`** (rejeitada no handoff —
  over-engineering pra 3 modelos; vira nota README)

**`sources.yml`:**

```yaml
sources:
  - name: silver
    database: "{{ env_var('CATALOG_PREFIX', '') }}nyc_taxi_silver"
    tables:
      - name: yellow_taxi_trips
  - name: monitoring
    database: "{{ env_var('CATALOG_PREFIX', '') }}monitoring"
    tables:
      - name: landing_audit
```

**`taxi_zone_lookup.csv`** — download da TLC
(https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv).
260 linhas, ~10 KB. Schema:
`LocationID,Borough,Zone,service_zone`. Renomear colunas pra
snake_case no seed config (`column_types` + rename hooks ou colunas
no CSV já em snake_case).

**Materialização:** `dim_locations` vive em
`${prefix}nyc_taxi_gold.dim_locations` (ADR-0009).

## Acceptance criteria

- [ ] `dbt/dbt_project.yml` valida com `dbt parse`
- [ ] `dbt deps` roda sem erro
- [ ] `dbt seed --target user_dev` cria
      `${prefix}nyc_taxi_gold.dim_locations` com 260 linhas
- [ ] `location_id` é INT (não STRING) pra casar com source Silver
      no `relationships` test do #9
- [ ] `dbt source freshness` (se aplicável) roda contra
      `silver.yellow_taxi_trips` sem erro
- [ ] `default materialization: view` aplica globalmente (sem
      precisar repetir nos modelos)
- [ ] Schema gold criado se não existir (via `+post-hook` ou
      `on-run-start` se DLT não criou ainda — provavelmente DLT só
      cria silver/bronze/monitoring)
- [ ] Profile `databricks` usa SQL Warehouse 2X-Small via
      `http_path` + token (mesmo padrão do probe Opção A)
- [ ] **Sem** convenção de prefix `_int_`/`_fin_`
- [ ] Modelo Gold ainda não criado — fica pro #08

## Blocked by

- `06-job-ingestion-dab.md` (`sources.yml` precisa apontar pra
  tabela Silver real existente no workspace; rodar `dbt source
  freshness` ou `dbt run --select gold` sem tabela Silver = erro)
