# AGENTS.md — nyc-taxi-case

Repositório do case técnico de Data Engineering: pipeline NYC Yellow Taxi
em Databricks Free Edition. **Monorepo com 2 jobs DAB independentes**:

- `job_ingestion` — DAB + DLT + Auto Loader (landing → bronze → silver).
- `job_dbt` — dbt-databricks (gold + dim_locations + análises),
  consumindo silver via `sources.yml`.

Schedule pausado nos dois; execução manual via `bundle run`. Sem
`depends_on` entre os jobs. Espelha padrões iFood: `ifp-data-ingestions`
(DLT-puro) + `pagob2b-dbt` (dbt-puro).

## Agent skills

### Issue tracker

Local markdown sob `.scratch/issues/<feature-slug>/` (sem GitHub Issues —
case solo). Ver `docs/agents/issue-tracker.md`.

### Triage labels

Vocabulário canônico (`needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`) declarado no frontmatter YAML de cada
`.md` em `.scratch/issues/`. Ver `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` na raiz + `docs/adr/` pra decisões
arquiteturais. Ver `docs/agents/domain.md`.

## Skills relevantes

- `setup-matt-pocock-skills` — já rodou; reexecutar só se mudar issue tracker
- `grill-with-docs` — refinar plano contra CONTEXT/ADRs
- `to-prd`, `to-issues`, `triage` — workflow de tickets locais
- `tdd` — pros helpers puros em `src/nyc_taxi_case/`
- `diagnose` — quando algo quebrar no Databricks
- `databricks-cli-debugging` — operação CLI Free Edition
- `commit-messages` — Conventional Commits

## Gotchas operacionais (Free Edition + DAB + serverless)

Acumulado dos primeiros runs end-to-end. Antes de "diagnosticar" algo
que se parece com um destes, confirme se já não é um deles.

- **DAB wheel artifact path** — `bundle deploy` sobe `type: whl`
  artifacts pra `${workspace.artifact_path}/.internal/<wheel>.whl`,
  NÃO pra `${workspace.file_path}/dist/`. `environments.spec.dependencies`
  (job) e `environment.dependencies` (Lakeflow pipeline) precisam
  apontar pro primeiro. Sintoma do mismatch:
  `Library installation failed ... ERROR_NO_SUCH_FILE_OR_DIRECTORY`
  apontando pra `files/dist/`. Ver ADR-0012.
- **`sys.exit` em notebook task = task FAILED** — mesmo `sys.exit(0)`.
  Notebook tasks esperam terminação natural via cell completion ou
  `dbutils.notebook.exit()`. Convenção do projeto: SUCCESS/PARTIAL
  cai fora do `if __name__` sem `sys.exit`; FAILED faz
  `raise RuntimeError(...)` pra surfar traceback. Ver ADR-0012.
- **Spark Connect (serverless) recusa schema inference em coluna
  fully-NULL** — `createDataFrame([row])` levanta
  `PySparkValueError: [CANNOT_DETERMINE_TYPE]` se qualquer coluna for
  `None` em **todas** as rows da batch. Workaround: passar `schema=`
  explícito (`StructType`). Caso real: `landing._write_audit_row`
  com `pipeline_update_id=None`.
- **Schema/Volume UC precisam existir antes do IO** — `os.makedirs`
  contra `/Volumes/<cat>/<schema>/<vol>/...` em schema/volume
  inexistente levanta `FileNotFoundError` opaco. Landing notebook
  resolve isso com `_ensure_landing_volume` no `main()` (ADR-0012).
  Outros notebooks futuros: seguir o mesmo pattern (`_ensure_*`
  idempotente no início).
- **`event_log("<id>")` espera pipeline_id, NÃO update_id** — query
  do `update_landing_audit.sql` usa
  `event_log(TABLE(<bronze_fqn>))` justamente pra sobreviver a
  delete+recreate do pipeline. Se for olhar errors de um update
  específico, use `/api/2.0/pipelines/<pipeline_id>/events`
  (REST), não `event_log("<update_id>")` (SQLSTATE 42K03).
- **`databricks --profile <p>` CLI ≠ Databricks SDK SQL** — não tem
  subcomando `sql` nem `statement-execution`. Pra rodar SQL ad-hoc,
  use `api post /api/2.0/sql/statements`. Warehouses serverless
  estão STOPPED por default — primeira query leva ~20s de cold start.
- **Free Edition Delta default não tem `timestampNtz`** — Auto Loader
  infere TIMESTAMP_NTZ pros campos `tpep_*_datetime` da TLC, mas
  Delta default rejeita com `DELTA_FEATURES_REQUIRE_MANUAL_ENABLEMENT`.
  Duas saídas: cast pra TIMESTAMP-com-tz no schema da Bronze, ou
  `tblproperties={"delta.feature.timestampNtz": "supported"}` no
  `@dlt.table` decorator. Atualmente bloqueando `dlt_pipeline_task`
  (ticket #04 candidato a reabrir).

## Contexto rápido

- Plano completo: `docs/PLAN.md`
- Enunciado original do case: `docs/CASE.md`
- Decisões emergentes: `docs/adr/`
- Vocabulário load-bearing: `CONTEXT.md`
- Histórico de fixes operacionais: `.scratch/issues/case-implementation/06-job-ingestion-dab.md`
  (Resolution + Fix #1-#5)
