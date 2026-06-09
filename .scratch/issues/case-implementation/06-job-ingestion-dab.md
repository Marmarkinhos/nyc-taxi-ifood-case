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

### Fix #6 (2026-06-09) — `dlt_pipeline_task` falha em `timestampNtz`

**Sintoma:** com landing_task verde end-to-end (Fixes #2-#5), o
`dlt_pipeline_task` falha na criação da Bronze com
`[DELTA_FEATURES_REQUIRE_MANUAL_ENABLEMENT] ... timestampNtz`.

**Diagnose:** TLC parquet declara `tpep_pickup_datetime` /
`tpep_dropoff_datetime` como `timestamp[us]` sem timezone (Arrow
maps to Spark `TIMESTAMP_NTZ`). Auto Loader com
`cloudFiles.inferColumnTypes=true` respeita o tipo do parquet. Delta
default no Free Edition tem só `appendOnly` habilitado — o feature
`timestampNtz` precisa ser ativado explicitamente. Sem ele, primeiro
write na Bronze é rejeitado.

**Decisão:** ADR-0013 (H2 — `table_properties` por tabela), rejeitando
H1 (`cloudFiles.schemaHints` na Bronze) por violar ADR-0001 e acoplar
ao schema TLC.

**Fix:** `ingestion/dlt_pipeline.py` ganhou
`"delta.feature.timestampNtz": "supported"` em ambos `table_properties`
(Bronze: necessário; Silver: defensive — Silver castiga pra
TIMESTAMP-com-tz, mas mantém simetria de capacidade Delta pro caso de
futura coluna NTZ propagada da Bronze). `tlc_schema.py` inalterado
(tipo canônico da Silver continua `TIMESTAMP`). Sem regression test
Spark-free — a seam de regressão é o próprio `bundle run
job_ingestion`, mesmo princípio do Fix #3 e ADR-0012.

### Fix #7 (2026-06-09) — TLC case rename causa mass rescue na Bronze

**Sintoma:** após Fix #6 destravar o DLT, primeira run end-to-end
mostrou Silver dropando 81.5 % das rows (13.19M) na expectation
`passenger_count_in_range`. Investigação SQL:

```sql
SELECT file_month, total, rescued, 100.0*rescued/total AS pct
  FROM (
    SELECT regexp_extract(_source_file_path,
                          'yellow_tripdata_(\d{4}-\d{2})', 1) AS file_month,
           COUNT(*) AS total,
           SUM(CASE WHEN _rescued_data IS NOT NULL THEN 1 ELSE 0 END) AS rescued
      FROM workspace.nyc_taxi_bronze.yellow_taxi_trips_raw
    GROUP BY 1
  );

-- 2023-01: 3,066,766 / 0          (0.0%)
-- 2023-02: 2,913,955 / 2,913,955  (100%)
-- 2023-03: 3,403,766 / 3,403,766  (100%)
-- 2023-04: 3,288,250 / 3,288,250  (100%)
-- 2023-05: 3,513,649 / 3,513,649  (100%)
```

Uma row típica de fev-mai mostrava 6 colunas em NULL e o JSON
rescuado:

```json
{"VendorID": 2, "passenger_count": 1, "RatecodeID": 1,
 "PULocationID": 238, "DOLocationID": 42, "Airport_fee": 0.0,
 "_file_path": "..."}
```

**Diagnose:** validação local com pyarrow nos 5 parquets TLC:

- 2023-01 declara o campo como `airport_fee` (lowercase).
- 2023-02 a 2023-05 declaram como `Airport_fee` (CamelCase).

TLC renomeou silenciosamente o campo entre janeiro e fevereiro de
2023. Spark default `caseSensitive=false` + parquet vectorized
reader = quando o reader vê `Airport_fee` num arquivo onde o schema
cacheado tem `airport_fee`, ele detecta case-mismatch e despeja
**o row group inteiro** no `_rescued_data` — incluindo 5 colunas
(`VendorID`, `passenger_count`, `RatecodeID`, `PULocationID`,
`DOLocationID`) que **não tinham** problema de case-mismatch.

`passenger_count` NULL na Bronze → Silver projection retorna NULL
→ expectation `BETWEEN 0 AND 9` (NULL → FALSE) → DROP. 81.5 % loss.

**Decisão:** ADR-0014 — `cloudFiles.schemaHints` anchorando os 19
campos TLC + expectation warn-only `bronze_no_rescued_data`.
Rejeitadas: Silver lookup case-insensitive (S2, trata sintoma),
`spark.sql.caseSensitive=true` (S3, blast radius), rescue mode
permanente (S4, anula Bronze tipada).

**Fix:**

1. `src/nyc_taxi_case/tlc_schema.py` ganhou `BRONZE_SCHEMA_HINT_TYPES`
   (mapping source-name → source-side type) e
   `bronze_schema_hints()` que gera a string DDL pro Auto Loader.
   Source-side types (DOUBLE pra `passenger_count`, NÃO BIGINT) —
   Silver continua o lugar dos casts canônicos.
2. `ingestion/dlt_pipeline.py` ganhou
   `.option("cloudFiles.schemaHints", bronze_schema_hints())` no
   reader da Bronze.
3. Mesma Bronze ganhou expectation warn-only
   `bronze_no_rescued_data` (`_rescued_data IS NULL`) — drift de
   tipo / cast failure futuros viram sinal no `event_log` sem
   quebrar pipeline.
4. 6 testes pytest novos cobrindo `BRONZE_SCHEMA_HINT_TYPES` parity
   com `TLC_RENAME_MAP`, source-side types preservados, formato
   DDL válido, e a assertion crítica de que `airport_fee` está
   lowercase no hint.

**Step extra obrigatório no HITL run:** schema cacheado da Bronze
em `cloudFiles.schemaLocation` precisa ser invalidado, senão hints
ficam sem efeito. Comando exato:

```bash
# 1. Achar o pipeline_id
databricks --profile free-edition bundle summary --target user_dev \
  | grep -A1 dlt_pipeline | head -3

# 2. Disparar full-refresh (não bundle run normal)
databricks --profile free-edition api post \
  "/api/2.0/pipelines/<PIPELINE_ID>/updates" \
  --json '{"full_refresh": true}'

# OU via bundle (se DAB já tiver target configurado pra full refresh):
databricks --profile free-edition bundle run job_ingestion \
  --target user_dev --refresh-all
```

**Gaps reconhecidos** (ver ticket #14, ADR-0014 §Decision item 5):
drift estrutural (coluna nova / removida), métrica `bronze_rescued_pct`
na audit table, e alerting job-level. Fora do escopo de Fix #7.

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
- ✅ `dlt_pipeline_task` destravado por **Fix #6** (ADR-0013 —
  `delta.feature.timestampNtz: supported`). DLT roda end-to-end.
- ⚠️ Mas Silver dropou 81.5 % das rows (13.19M) na primeira run —
  **Fix #7 aplicado** (ADR-0014 — `cloudFiles.schemaHints` na Bronze
  pra resolver TLC `airport_fee`→`Airport_fee` rename + expectation
  warn-only `bronze_no_rescued_data`). Aguardando re-run com
  `--full-refresh` pra invalidar schema cacheado e recuperar as 13.12M
  rows fev-mai/2023.
- ❌ Fix #7 deployado + full-refresh (update_id
  `76e62ba1-33a7-41bf-a54d-88da2be9b47e`, confirmed `full_refresh: true`
  + `state: COMPLETED` via REST) **NÃO resolveu o rescue**. Bronze
  pós-fix mostra jan=0 rescued / feb-mai=100% rescued — exatamente
  como pré-fix. Hints anchoraram o nome (DESCRIBE da Bronze tem só
  `airport_fee` lowercase, não inferiu `Airport_fee` da maioria), mas
  o `_rescued_data` continua populado em feb-mai com `Airport_fee` no
  JSON.
- ⚠️ **Fix #8 (2026-06-09)** — adicionado
  `.option("readerCaseSensitive", "false")` no reader Auto
  Loader em `ingestion/dlt_pipeline.py`. (Inicialmente tentado como
  `cloudFiles.readerCaseSensitive` — quebrou com
  `CF_UNKNOWN_OPTION_KEYS_ERROR`; key é format-specific, sem prefixo
  `cloudFiles.*`.) Update `66ccf5f0-7724-4408-b2d1-5fab510ea697`
  COMPLETED com full_refresh, **mas o rescue persistiu idêntico**
  ao pré-Fix #7. Hipótese "100% case-mismatch" descartada
  empiricamente. ADR-0014 §"Follow-up correction" deixou o estado do
  Fix #8 como "aguardando validação"; resultado real entra agora no
  Fix #9.
- ✅ **Fix #9 (2026-06-09)** — root cause real identificado via
  diff de schema pyarrow nos 5 parquets TLC: TLC mudou tipos físicos
  de 6 colunas entre jan e feb-mai. ADR-0015 (supersede parcial do
  0014) aplica:
  - `cloudFiles.schemaEvolutionMode` muda de `addNewColumns` →
    `addNewColumnsWithTypeWidening`.
  - `delta.enableTypeWidening: "true"` adicionado ao
    `table_properties` da Bronze (prereq Databricks).
  - 5 colunas type-drifting (`VendorID`/`passenger_count`/
    `RatecodeID`/`PULocationID`/`DOLocationID`) **removidas** de
    `BRONZE_SCHEMA_HINT_TYPES` (hints disable widening).
  - `_build_silver_projection` ganha `_RESCUED_RECOVERY` map pros 2
    cols sem path de widening (`passenger_count`, `RatecodeID`),
    recuperando via `F.coalesce(typed, F.get_json_object(
    F.col("_rescued_data"), "$.<source>").cast(...))`.
  - `test_tlc_schema.py` inverte o contract: 14 cols devem estar
    hinted, 5 type-drifting NÃO devem.
  - Update `acc127b0-95da-4a01-942e-2a0577b40b41` COMPLETED.
    Validação: Silver passa de 2.97M → 15.62M rows; expectations
    `passenger_count_in_range` cai de 13.19M → 428K drops (96.7 %
    redução), `vendor_id_in_dictionary` cai de 13.12M → 0.
    `_rescued_data` Bronze feb-mai continua 100 % populado (só
    `passenger_count`/`RatecodeID` no JSON agora), e isso é
    correto: schema-drift detector permanece loud, Silver recupera.
- ⏳ `update_audit_task` (`pipeline_update_id` backfill) — agora
  pode ser validado end-to-end (Fix #9 verde).
