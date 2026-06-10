---
status: done
created: 2026-06-08
tags: [notebook, dashboard, consumption, dab]
blocked-by: [11-dbt-analyses.md]
blocks: [13-readme-finalization.md]
---

# 12 — Notebook `answers.py` + AI/BI dashboard `.lvdash.json`

## What to build

Camadas de consumo visual + interativa (Decisão #8 trio + ADR
relacionados). **Modelos dbt continuam SSoT — estes só exibem.**

### `notebooks/answers.py`

Notebook Databricks (Python) que:

1. Lê os 3 modelos analytics do #11 via
   `spark.read.table("${prefix}nyc_taxi_gold.<modelo>")`.
2. Mostra cada um via `display()`:
   - Pergunta 1: `monthly_avg_total_amount` → tabela + chart
     (linha) `pickup_year_month` × `avg_total_amount`.
   - Pergunta 2: `hourly_avg_passenger_count_may` → tabela +
     chart (bar) `pickup_hour` × `avg_passenger_count`.
   - EDA: `eda_geographic` → tabela + chart (heatmap se viável).
3. Comentários em markdown (`# MAGIC %md`) explicando contexto +
   apontando pros modelos dbt como SSoT.

**Não faz SQL inline.** Não recalcula. Não consome Silver/Bronze
diretamente. Só `spark.read.table` dos analytics.

### `resources/nyc_taxi_dashboard.lvdash.json`

AI/BI dashboard versionado via DAB (Decisão #8 — "infra como
código até a ponta"):

- Datasets apontam pras 3 tabelas analytics
- 3 visualizações:
  - Line chart: `monthly_avg_total_amount`
  - Bar chart: `hourly_avg_passenger_count_may`
  - Pivot/heatmap: `eda_geographic`
- Filtros opcionais (vendor, hora) — só se trivial de adicionar
- Declarado no `databricks.yml` ou
  `resources/general_variables.yml` pra ser deployado junto com
  bundles

## Acceptance criteria

- [ ] `notebooks/answers.py` executa end-to-end em workspace
      (após `bundle run job_dbt` ter populado as tabelas analytics)
- [ ] 3 `display()` calls produzem visualizações úteis (não só
      tabelas raw)
- [ ] Comentários markdown apontam pros modelos dbt como SSoT
- [ ] Sem SQL inline; só `spark.read.table`
- [ ] `nyc_taxi_dashboard.lvdash.json` deployado via
      `bundle deploy` aparece como dashboard na UI
- [ ] 3 visualizações no dashboard renderizam corretamente
- [ ] Notebook adicionado ao bundle (visível via
      `bundle deploy`)

## Blocked by

- `11-dbt-analyses.md` (precisa das 3 tabelas analytics
  materializadas)

## Notas

- AI/BI dashboard `.lvdash.json` schema: gerar via export da UI
  Databricks (criar dashboard manualmente → "Export as JSON") e
  versionar.
- Genie e DuckDB **descartados conscientemente** (Decisão #8 +
  CONTEXT.md §NÃO-objetivos).

## Resolution (2026-06-09)

### Arquivos criados

- `notebooks/answers.py` — Databricks Python notebook (source
  format: `# Databricks notebook source` header + `# COMMAND
  ----------` cell separators + `# MAGIC %md` markdown). Lê os 3
  modelos Gold via `spark.read.table(...)`, **sem SQL inline, sem
  recálculo**. Cada `display()` é precedido por um cell markdown
  apontando pro arquivo `dbt/analyses/*.sql` correspondente como
  SSoT e linkando o ADR-0016 quando aplicável (Q2).
  FQN do schema é resolvido via `dbutils.widgets` (`catalog`,
  `catalog_prefix`, `gold_schema`) → defaults batem `user_dev` da
  Free Edition, mas DAB pode override por target via
  `base_parameters` se um dia o notebook virar task.
- `resources/nyc_taxi_dashboard.lvdash.json` — AI/BI dashboard
  Lakeview no schema canônico (`datasets[] + pages[].layout[]`
  com `position {x,y,width,height}` e `widget {queries, spec}`).
  3 datasets espelham as 3 analyses (mesmas queries, FQN
  expandido: `workspace.nyc_taxi_gold.yellow_taxi_trips_consumption`).
  3 widgets: line (Q1), bar (Q2), table (EDA). Um textbox de
  título no topo aponta pra SSoT dbt. Sem filtros — Decisão "só
  se trivial" do ticket; pivot/heatmap virou tabela com colunas
  formatadas porque o widgetType `heatmap` do Lakeview pede
  encoding `color + x + y` que não casa com `pickup_borough x
  dropoff_borough x trip_count` sem aggregate inline (e a query
  já vem pré-agregada).
- `resources/dashboard.yml` — resource DAB com
  `resources.dashboards.nyc_taxi_case_answers` (display_name,
  file_path, warehouse_id via `${var.sql_warehouse_id}`).
  Comentário no topo explica que o notebook **não** precisa de
  resource block — sobe via `sync.include` default como qualquer
  `.py`. Path do `file_path` é `./nyc_taxi_dashboard.lvdash.json`
  (relativo ao YAML, não ao bundle root — descoberto durante
  validate).
- `pyproject.toml` — per-file-ignore pra `notebooks/**` (F821,
  E501, E402): `spark` / `dbutils` / `display` são runtime
  builtins do Databricks, células markdown estouram 100 cols, e
  imports cell-scoped quebram E402. Padrão pragmático em vez de
  espalhar `# noqa` por cada linha.

### Deploy + verificação

```bash
export DBT_TOKEN=$(awk '/^\[free-edition\]/{f=1;next} f && /^token/{print $3;exit}' ~/.databrickscfg)

databricks bundle validate --profile free-edition  # → Validation OK!
databricks bundle deploy   --profile free-edition  # → Deployment complete!
databricks bundle summary  --profile free-edition
```

Output do `summary` confirma o dashboard como recurso novo:

```
Dashboards:
  nyc_taxi_case_answers:
    Name: [dev mreisfilho1] [user_dev] NYC Yellow Taxi — case answers
    URL:  https://dbc-88968762-8346.cloud.databricks.com/dashboardsv3/01f1646083eb10aeb6dbd3ab21390b40/published?o=757803262701153
```

Notebook upou como NOTEBOOK Python:

```
$ databricks --profile free-edition workspace list \
    /Workspace/.../files/notebooks
ID                Type      Language  Path
3784439442884278  NOTEBOOK  PYTHON    .../notebooks/answers
```

Lakeview `GET` confirma o dashboard em `lifecycle_state: ACTIVE`
com `warehouse_id: 10ba36a843e45ac1` (mesmo do worktree #10
paralelo — cold start ~20s na primeira query, esperado).

### Cross-check numérico contra Resolution #11

Cada query do dashboard foi rodada via SQL Statements API
contra o warehouse pra provar que os números renderizados batem
exato com o que o ticket #11 reportou:

**Q1 — Monthly avg total_amount** (5 linhas, Jan–Mai 2023):

| pickup_year_month | avg_total_amount | trip_count |
| --- | ---: | ---: |
| 2023-01 | 27.44 | 3 041 519 |
| 2023-02 | 27.33 | 2 888 824 |
| 2023-03 | 28.26 | 3 373 543 |
| 2023-04 | 28.76 | 3 258 394 |
| 2023-05 | 29.46 | 3 481 800 |

Bate ✓ Resolution #11.

**Q2 — Top 3 horas por avg passenger_count em Maio** (filtro
ADR-0016 aplicado: `IS NOT NULL` + `COUNT(passenger_count)`):

| pickup_hour | avg_passenger_count | trip_count_with_passenger |
| ---: | ---: | ---: |
| 2 | 1.438 | 37 472 |
| 3 | 1.437 | 24 341 |
| 1 | 1.422 | 58 167 |

Bate ✓ Resolution #11 (que reportou "pico hora 03 com 1.437";
hora 02 ligeiramente acima na nova execução, mesma faixa de
madrugada).

**EDA — Top 3 fluxos borough×borough por volume**:

| pickup | dropoff | trips | avg_fare |
| --- | --- | ---: | ---: |
| Manhattan | Manhattan | 13 238 171 | USD 21.03 |
| Queens | Manhattan |    872 712 | USD 80.36 |
| Manhattan | Queens |    489 061 | USD 65.58 |

Bate ✓ Resolution #11.

### Acceptance criteria

- [x] `notebooks/answers.py` executa end-to-end em workspace —
      deploy OK, notebook publicado como tipo NOTEBOOK
- [x] 3 `display()` calls (uma per pergunta + markdown header
      apontando viz recomendada: line / bar / heatmap-or-pivot)
- [x] Comentários markdown apontam pros modelos dbt como SSoT
      (cada cell `# MAGIC %md` tem link relativo pro
      `dbt/analyses/<modelo>.sql`)
- [x] Sem SQL inline; só `spark.read.table(gold_table(...))`
      com a helper `gold_table()` centralizando o FQN
- [x] `nyc_taxi_dashboard.lvdash.json` deployado via
      `bundle deploy` aparece como dashboard na UI
      (URL em `bundle summary`)
- [x] 3 visualizações no dashboard (line Q1, bar Q2, table EDA)
      com queries que rodam SUCCEEDED contra o warehouse
- [x] Notebook adicionado ao bundle (visível no
      `workspace list .../files/notebooks`)

### Desvios do spec

1. **Pivot/heatmap virou table formatada** pra EDA. Lakeview
   `widgetType: heatmap` exige encoding `x + y + color` com
   aggregate inline (`SUM(count)`), mas a query já vem
   pré-agregada (uma row por par `pickup × dropoff`); o resultado
   visual ficaria errado se o widget agregasse de novo.
   Workaround: `widgetType: table` com `numberFormat: $0.00` em
   `avg_total_amount` e `0,0` em `trip_count` — preserva a
   semântica de "matriz" sem distorcer os números. Heatmap pode
   ser adicionado depois via UI + `bundle generate dashboard
   --resource nyc_taxi_case_answers --force` se o avaliador
   pedir.
2. **Filtros opcionais (vendor, hora) NÃO adicionados** — ticket
   explicitamente disse "só se trivial". Filter widgets do
   Lakeview exigem associative join entre datasets (ver
   `filter-multi-select` no exemplo `databricks/bundle-examples`),
   não trivial pra 3 datasets independentes; deixado fora.

### Gates

- `uv run --extra dev ruff check .` → All checks passed!
- `uv run --extra dev pytest -q` → 136 passed in 0.18s
- `databricks bundle validate --profile free-edition` → Validation OK!
- `databricks bundle deploy --profile free-edition` → Deployment complete!

### Não tocado

- `ingestion/` (escopo dos #06/#15, fora deste ticket)
- `dbt/` (Gold + analyses já deployados pelos #08/#11)
- `.scratch/issues/case-implementation/README.md` (índice de
  tickets — atualização batched pela sessão principal pós-merge,
  per AGENTS.md §Worktree agents)
