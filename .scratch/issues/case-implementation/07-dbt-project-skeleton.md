---
status: done
created: 2026-06-08
completed: 2026-06-09
tags: [dbt, skeleton, sources, seed, dim]
blocked-by: [06-job-ingestion-dab.md]
blocks: [08-dbt-gold-model.md]
---

# 07 — dbt project skeleton + `sources.yml` + seed `dim_locations`

## Resolution (2026-06-09): ✅ DONE

Skeleton entregue, `dim_locations` materializada em
`workspace.nyc_taxi_gold.dim_locations` (265 rows, `location_id INT`,
8 boroughs distintos). Schema gold auto-criado pelo adapter
dbt-databricks. `dbt source freshness` PASS contra Silver real.

**Artefatos entregues:**

- `dbt/dbt_project.yml` — `name: nyc_taxi_case`, profile
  `nyc_taxi_case`, default `materialized: view`, seed config força
  `location_id INT`, `+alias: dim_locations` (CSV chama
  `taxi_zone_lookup`, tabela final chama `dim_locations`).
- `dbt/profiles.yml` — targets `user_dev` + `prod`, credenciais via
  `env_var('DBT_TOKEN')`. Schema/catalog escritos diretos (sem concat
  `<target>_<config>`) por omitir `+schema` no project.
- `dbt/models/sources.yml` — 2 sources: `silver.yellow_taxi_trips` +
  `monitoring.landing_audit`. **Critical:** schema da Silver é
  `nyc_taxi_bronze` (não `nyc_taxi_silver` como sugere o nome da var)
  — Free Edition uses single workspace catalog (handoff caveat,
  AGENTS.md). `loaded_at_field` + `freshness` dentro de `config:`
  (dbt 1.11+ deprecation).
- `dbt/packages.yml` — vazio (YAGNI, `dbt deps` no-op).
- `dbt/seeds/taxi_zone_lookup.csv` — 265 rows, headers já em
  snake_case na fonte (sem rename hooks).
- `dbt/.gitignore` — `target/`, `dbt_packages/`, `logs/`, `.user.yml`.
- `pyproject.toml` — extra `dbt = ["dbt-databricks>=1.10,<2"]`
  separado de `dev` (ingestão não puxa dbt).

**Runbook validado (local CLI):**

```bash
export DBT_TOKEN=$(awk '/^\[free-edition\]/{f=1;next} f && /^token/{print $3;exit}' ~/.databrickscfg)
cd dbt
uv run --project .. dbt deps               # no-op (packages vazio)
uv run --project .. dbt parse --target user_dev          # ✅ clean
uv run --project .. dbt seed --target user_dev           # ✅ INSERT 265, ~18s
uv run --project .. dbt source freshness --target user_dev  # ✅ PASS, ~5s
```

**Notas operacionais:**

- `dbt parse` mostra 1 warning "unused configuration paths:
  `models.nyc_taxi_case`" — esperado pro skeleton; some quando #08
  adiciona o primeiro modelo Gold.
- Cold start do warehouse Serverless Starter é ~10-18s no primeiro
  `dbt seed` (depois fica warm, ~2-3s).
- `dbt-databricks 1.12.0` + `dbt-core 1.11.8` — mesma versão que o
  probe B (ADR-0010), runtime serverless do `dbt_task` vai resolver
  o mesmo conjunto.

## What to build (original)

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

- [x] `dbt/dbt_project.yml` valida com `dbt parse`
- [x] `dbt deps` roda sem erro (no-op, `packages.yml` vazio)
- [x] `dbt seed --target user_dev` cria
      `workspace.nyc_taxi_gold.dim_locations` com **265 linhas**
      (TLC atualizou; ticket dizia ~260, OK)
- [x] `location_id` é **INT** (não STRING/BIGINT) — validado via
      `DESCRIBE TABLE` no warehouse
- [x] `dbt source freshness` roda contra
      `silver.yellow_taxi_trips` sem erro (PASS, ~5s)
- [x] `default materialization: view` aplica globalmente via
      `models.nyc_taxi_case.+materialized` no `dbt_project.yml`
- [x] Schema gold criado **automaticamente pelo adapter
      dbt-databricks** na primeira escrita — não precisou de
      `+post-hook` nem `on-run-start`
- [x] Profile `nyc_taxi_case` usa SQL Warehouse `10ba36a843e45ac1`
      via `http_path: /sql/1.0/warehouses/10ba36a843e45ac1` + token
      via `env_var('DBT_TOKEN')`
- [x] **Sem** convenção de prefix `_int_`/`_fin_`
- [x] Modelo Gold ainda não criado — fica pro #08

## Blocked by

- `06-job-ingestion-dab.md` (`sources.yml` precisa apontar pra
  tabela Silver real existente no workspace; rodar `dbt source
  freshness` ou `dbt run --select gold` sem tabela Silver = erro)
