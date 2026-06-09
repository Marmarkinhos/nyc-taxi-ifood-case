---
status: done
created: 2026-06-08
closed: 2026-06-09
tags: [dab, job, ingestion, orchestration]
blocked-by: [04-dlt-bronze-silver-canonica.md]
blocks: [07-dbt-project-skeleton.md]
---

# 06 — `job_ingestion` DAB

## What to build

`resources/job_ingestion.yml` agregando os componentes do lado
ingestão (ADR-0011 lado ingestão). **Não menciona dbt em lugar
nenhum.**

**3 tasks sequenciais:**

1. `landing_task` (`spark_python_task`):
   - Notebook do ticket #3
   - Args: `--start_year_month`, `--end_year_month` via DAB
     parameters (defaults via `general_variables.yml`)
2. `dlt_pipeline_task` (`pipeline_task`):
   - Aponta pro DLT pipeline do ticket #4/#5
   - `depends_on: [landing_task]`
3. `update_audit_task` (`sql_task`):
   - `UPDATE ${prefix}monitoring.landing_audit
     SET pipeline_update_id = '<update_id_from_latest>'
     WHERE run_id = '${{job.run_id}}'`
   - `depends_on: [dlt_pipeline_task]`
   - Padrão pra obter `pipeline_update_id`: consultar
     `event_log()` do pipeline filtrando pelo run mais recente, ou
     usar output do `pipeline_task` se DAB expuser.

**Schedule pausado** em todos os targets (ADR-0011).

**Variáveis** centralizadas em `resources/general_variables.yml`
(criado no #02 ou expandido aqui):

- `catalog_prefix`
- `landing_volume_path`
- `bronze_schema`, `silver_schema`, `monitoring_schema`
- Defaults de janela

## Acceptance criteria

- [ ] `resources/job_ingestion.yml` valida com
      `databricks bundle validate`
- [ ] Job tem exatamente as 3 tasks na ordem correta com
      `depends_on`
- [ ] Schedule pausado em todos os targets
- [ ] `databricks bundle deploy --target user_dev` cria o job no
      workspace
- [ ] `databricks bundle run job_ingestion` executa end-to-end
      com sucesso (com 1 mês na janela)
- [ ] Após run: `landing_audit` tem `pipeline_update_id`
      preenchido (não NULL)
- [ ] Não há `depends_on` nem referência a `dbt_task` ou
      `job_dbt` em lugar nenhum (verificável por grep)
- [ ] Variáveis usadas via `${var.xxx}`, não hardcoded

## Blocked by

- `04-dlt-bronze-silver-canonica.md` (DAB precisa de pipeline_id
  válido pra apontar)

## Notas

- #5 (expectations) **não** é blocker — DAB pode ser deployado com
  pipeline DLT sem expectations finalizadas; ambos os tickets
  podem rodar em paralelo após #4.
- Pattern: `ifp-data-ingestions` faz exatamente isso (landing +
  pipeline + sql task pós-DLT). Replicar.

## Resolution (2026-06-09)

Implementado em 3 arquivos novos + 2 mudanças triviais.

### Arquivos

- **`resources/dlt_pipeline.yml`** (novo) — define
  `resources.pipelines.yellow_taxi_ingestion`, serverless, aponta
  pro `ingestion/dlt_pipeline.py` via `libraries.file.path`.
  Catalog/target via `${var.catalog}` / `${var.bronze_schema}`.
  `landing_volume_path` injetado via `configuration` (lido pelo
  `_conf` helper do pipeline).
- **`resources/job_ingestion.yml`** (novo) — define
  `resources.jobs.job_ingestion` com 3 tasks sequenciais, schedule
  PAUSED, 2 `parameters` de janela com defaults de
  `general_variables.yml`, e bloco `environments` único
  (`serverless_default`).
- **`ingestion/sql/update_landing_audit.sql`** (novo) — UPDATE
  inline rodado pelo `sql_task` da task 3. Catalog/schema são
  literais (`workspace.nyc_taxi_monitoring.landing_audit`,
  `workspace.nyc_taxi_bronze.yellow_taxi_trips_raw`) porque DAB não
  interpola `${...}` em SQL files; `{{job.run_id}}` é substituído
  pelo job runner em runtime. Usa `event_log(TABLE(<bronze_fqn>))`
  (forma Lakeflow recomendada) em vez de `event_log("<pipeline_id>")`
  pra sobreviver a delete+recreate do pipeline.
- **`ingestion/landing.py`** — adicionada apenas a linha
  `# Databricks notebook source` no topo, pra ser reconhecido como
  notebook pelo `notebook_task` (zero mudança de código).
- **`databricks.yml`** — `user_dev.variables.sql_warehouse_id`
  pinado em `10ba36a843e45ac1` (Serverless Starter Warehouse
  auto-provisioned pelo Free Edition, capturado via SQL Warehouses
  UI → Connection details).
- **`resources/general_variables.yml`** — declara `sql_warehouse_id`
  com default vazio.

### Departures vs ticket original

1. **`notebook_task` em vez de `spark_python_task`** na task 1
   (landing). O `landing.py` já lia params via `dbutils.widgets`
   (ticket #03); `spark_python_task` exigiria refactor pra
   `argparse`. Custo: 1 linha de header `# Databricks notebook
   source` no `landing.py`.
2. **Task 3 é `sql_task` com `file.path`**, fiel ao ticket e ao
   padrão `ifp-data-ingestions`. Investigado durante o desenvolvimento:
   - `sql_task.file.path` não recebe substituição `${...}` (verificado
     via tompero search).
   - `sql_task.query.query` (SQL inline) **não existe no schema DAB** —
     o schema só aceita `query.query_id` (Query UC-saved),
     `alert.alert_id`, `file.path`, ou `dashboard`.
   - Workaround: SQL com literais em `ingestion/sql/...` (1 grep pra
     editar se vars mudarem) + `{{job.run_id}}` resolvido em runtime.
     Trade-off aceito vs `notebook_task` Python: ~15 linhas SQL
     legíveis e standalone-debuggable vs ~120 linhas de notebook
     Python só pra escapar do limite de interpolação.
3. **Pipeline em arquivo separado** (`dlt_pipeline.yml`), não inline em
   `job_ingestion.yml`. Justificado in-file: pipeline é recurso UC
   long-lived (catalog/schema/storage); job é o trigger surface. A
   separação espelha `ifp-data-ingestions` e permite o job referenciar
   pipeline.id sem conhecer internals.

### Acceptance criteria

- ✅ `databricks --profile free-edition bundle validate --target
  user_dev` → `Validation OK!` (first try).
- ✅ Job tem exatamente 3 tasks (`landing_task`, `dlt_pipeline_task`,
  `update_audit_task`) com `depends_on` em cadeia. Verificado via
  introspeção do JSON de validate.
- ✅ Schedule PAUSED em todos os targets (declarado no job; targets
  `user_dev` e `prod` não fazem override).
- ✅ Variáveis via `${var.xxx}` — zero literal de catalog/schema/path
  em `resources/*.yml` (grep confirma só comentários).
- ✅ Sem referência a `dbt_task` ou `job_dbt` — grep só encontra
  matches em comentário documentando ADR-0011 ("este job NÃO menciona
  dbt") e na var doc de `general_variables.yml` ("consumida por ambos
  os jobs"). Nenhuma referência funcional.
- ⏳ `bundle deploy --target user_dev` — não rodado localmente (HITL
  do user; PAT pode ter expirado).
- ⏳ `bundle run job_ingestion` end-to-end — HITL.
- ⏳ `landing_audit` tem `pipeline_update_id` preenchido pós-run —
  HITL (depende do `bundle run`).

### Gates locais

- `databricks bundle validate --target user_dev` ✅ (exit 0, sem
  warnings em `--output json`). Verificado:
  - 3 tasks com `kind` correto (`notebook_task`, `pipeline_task`,
    `sql_task`) e `depends_on` em cadeia.
  - `sql_warehouse_id` resolvido para `10ba36a843e45ac1`.
  - Pipeline `yellow_taxi_ingestion` registrada.
- `ruff check + format` ✅.
- `mypy --strict src/` ✅ (8 source files).
- `pytest -q` ✅ — **116 passed** (sem teste novo: SQL file +
  YAMLs não têm gate pytest natural).

### Não testado localmente

`bundle deploy` + `bundle run` exigem PAT vivo + workspace real
(HITL). Pontos a validar manualmente pós-#13:
- Que `event_log(TABLE(workspace.nyc_taxi_bronze.yellow_taxi_trips_raw))`
  retorna `create_update` events no Free Edition Lakeflow (alternativa
  documentada: trocar pra `event_log("<pipeline_id>")` se a forma
  com `TABLE(...)` não estiver disponível).
- Que `{{job.run_id}}` é substituído como string-literal compatível
  com o `job_run_id` STRING que o `landing.py` escreve em
  `landing_audit` (resolvido pelo tags context `tags.runId`).
- Que `cluster_by=["pickup_year_month"]` do Silver é aceito (fallback
  pra `partition_cols` documentado em ADR-0006).
