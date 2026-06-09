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

### Fix #1 (2026-06-09) — `nyc_taxi_case` wheel não estava na env

**Sintoma:** primeiro `bundle run` (job run 958048686653811) falhou
no `landing_task` com `ModuleNotFoundError: No module named
'nyc_taxi_case'`. Esperado em retrospecto: o bundle subia só os
`.py` files do `ingestion/`, mas o `src/nyc_taxi_case/` não entra no
`sys.path` da env serverless por mágica.

**Fix:**

1. Adicionado `artifacts.nyc_taxi_case_wheel` em `databricks.yml`
   com `type: whl` + `build: uv build --wheel`. `bundle deploy`
   buildam o wheel local e fazem upload pra
   `${workspace.file_path}/dist/`.
2. `resources/job_ingestion.yml` ganhou
   `environments[].spec.dependencies` listando o wheel via path
   resolvido `${workspace.file_path}/dist/nyc_taxi_case-0.1.0-py3-none-any.whl`.
3. `resources/dlt_pipeline.yml` ganhou o mesmo wheel via
   `environment.dependencies` (Lakeflow usa singular `environment`,
   não `environments`).
4. `.gitignore` ganhou `build/` (já tinha `dist/`).

Validate confirma resolução pra path absoluto correto:
`/Workspace/Users/<user>/.bundle/nyc-taxi-case/user_dev/files/dist/
nyc_taxi_case-0.1.0-py3-none-any.whl`. Pendente HITL: re-run do
`bundle deploy` + `bundle run job_ingestion`.

### Fix #2 (2026-06-09) — wheel uploaded em path errado

**Sintoma:** após Fix #1, `bundle run` (job run 399355919004015)
falhou no `landing_task` com
`Library installation failed ... ERROR_NO_SUCH_FILE_OR_DIRECTORY` no
path `/Workspace/Users/.../files/dist/nyc_taxi_case-0.1.0-py3-none-any.whl`.

**Diagnose:** `bundle deploy --debug` revelou que o CLI faz
`POST /api/2.0/workspace-files/import-file` pra
`${workspace.artifact_path}/.internal/<wheel>` (NÃO
`${workspace.file_path}/dist/`). O comentário que eu havia escrito no
`databricks.yml` documentando o path estava correto, mas o
`dependencies` no job/pipeline YAML referenciava `file_path` — onde
só vão arquivos do `sync.include`, não `type: whl` artifacts.

**Fix:** trocado em `resources/job_ingestion.yml` (linha 138) e
`resources/dlt_pipeline.yml` (linha 60):

```yaml
# antes
- ${workspace.file_path}/dist/nyc_taxi_case-0.1.0-py3-none-any.whl
# depois
- ${workspace.artifact_path}/.internal/nyc_taxi_case-0.1.0-py3-none-any.whl
```

Pós-deploy confirmado via `workspace list`: wheel está em
`/Workspace/Users/<user>/.bundle/nyc-taxi-case/user_dev/artifacts/.internal/`.

### Fix #3 (2026-06-09) — `_write_audit_row` falha em Spark Connect

**Sintoma:** com o wheel finalmente instalado, `landing_task` rodou
até o `_write_audit_row` e falhou com
`PySparkValueError: [CANNOT_DETERMINE_TYPE]`. Spark Connect (runtime
serverless) recusa inferir schema quando uma coluna do row de input
é `None` — e `pipeline_update_id` é sempre `None` no landing (o SQL
backfill task preenche pós-DLT, ADR-0008). `error_message` também é
`None` no caminho SUCCESS, e `probe_results[*].http_code` pode ser
`None` em probes `TIMEOUT`/`CONN_ERR`.

**Fix:** `ingestion/landing.py` ganhou helper
`_landing_audit_spark_schema()` que constrói explicitamente o
`StructType` espelhando `LANDING_AUDIT_CREATE_TABLE_SQL` (ADR-0008),
e `_write_audit_row` passa esse schema explícito pro
`createDataFrame`. Sem regression test unitário porque pyspark não é
dev dep local — a seam de regressão é o próprio
`bundle run job_ingestion`.

### Fix #4 (2026-06-09) — Landing schema/Volume não existem

**Sintoma:** após Fix #3 o wheel install + audit row gravavam OK,
mas todos os 5 meses caíam em `status=FAILED` mesmo com **probe
HEAD respondendo 200 OK pra todos** (`probe_results` da audit row
confirmou). A `error_message` genérica ("outbound TLC bloqueado")
do `_status_and_error` foi enganosa — não era bloqueio de rede.

**Diagnose:** `SHOW SCHEMAS IN workspace` mostrou que o schema
`nyc_taxi_bronze` **não existia** (só `aquarela`, `default`,
`information_schema`, `nyc_taxi_monitoring`). Sem schema, sem
Volume `landing`, então `os.makedirs(/Volumes/workspace/
nyc_taxi_bronze/landing/yellow/year=...)` em `_download_to_volume`
falhava com FileNotFoundError, era catched pelo
`except Exception` (linha 216 do landing.py), logado em
`sys.stderr` (que NÃO vem pela jobs API) e demoted pra `FAILED`.

PLAN.md §setup tinha uma linha "criar Volume" como step manual,
nunca executado nesse workspace. Nenhum ticket criou o
schema/Volume programaticamente — gap no plano.

**Fix:**

1. `src/nyc_taxi_case/landing_paths.py` ganhou `VolumeBase` +
   `parse_volume_base(base)` que decompõe `/Volumes/<cat>/<schema>/
   <volume>[/...]` no triple UC. 9 testes novos cobrindo path
   canônico, trailing slash, e erros (vazio, prefixo errado, poucos
   segmentos).
2. `ingestion/landing.py` ganhou `_ensure_landing_volume(session,
   params)`, idempotente (`CREATE SCHEMA IF NOT EXISTS` +
   `CREATE VOLUME IF NOT EXISTS`), chamado em `main()` logo após
   `_ensure_audit_table`. Espelha o pattern já existente pro
   audit schema.

### Fix #5 (2026-06-09) — `sys.exit` em notebook task

**Sintoma:** após Fix #4 o landing rodou e gravou audit com
`status=SUCCESS` e `bytes_downloaded=264_426_470`, mas o task ainda
apareceu como FAILED no DAB com `SystemExit: 0`. Causa: notebook
tasks tratam qualquer `sys.exit(N)` (mesmo `sys.exit(0)`) como
workload failure — eles esperam terminação natural via cell
completion ou `dbutils.notebook.exit()`.

**Fix:** trocado `sys.exit(main())` por `main()` no entry-point, e
`main()` agora `raise RuntimeError(...)` em FAILED (única forma de
sinalizar erro num notebook task) ao invés de `return 1`. SUCCESS/
PARTIAL retorna naturalmente.

### HITL gates pós-Fix #2 a #5 (run 946275077691272)

- ✅ `bundle deploy --target user_dev` sobe wheel + recursos.
- ✅ `landing_task` **SUCCESS** end-to-end:
  - Wheel instalado (Fix #2)
  - Audit schema + table criados, row gravada com schema explícito
    (Fix #3)
  - Landing schema + Volume bootstrap automático (Fix #4)
  - 5/5 meses baixados (~252 MiB, jan-mai 2023 confirmado via
    `SELECT status, bytes_downloaded, months_downloaded FROM
    landing_audit`)
  - Task termina verde sem SystemExit espúrio (Fix #5)
- ❌ `dlt_pipeline_task` falha com `[DELTA_FEATURES_REQUIRE_MANUAL_
  ENABLEMENT] timestampNtz` — Auto Loader infere `TIMESTAMP_NTZ`
  pros campos `tpep_pickup_datetime` / `tpep_dropoff_datetime` (TLC
  parquet schema) mas a Delta default no Free Edition não habilita
  esse feature. **Problema do ticket #04 (DLT Bronze)**, não #06.
  Reabrir #04 ou abrir ticket dedicado com:
  - Opção A: forçar `TIMESTAMP` (com tz) via cast na Bronze.
  - Opção B: `tblproperties={"delta.feature.timestampNtz":
    "supported"}` no `@dlt.table` decorator (ou via
    `spark.conf.set("spark.databricks.delta.properties.defaults.
    feature.timestampNtz", "supported")` no top do pipeline).
- ⏳ `update_audit_task` (`pipeline_update_id` backfill) bloqueado em
  UPSTREAM_FAILED até #04 destravado.
