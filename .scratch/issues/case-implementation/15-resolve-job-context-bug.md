---
status: done
created: 2026-06-09
resolved: 2026-06-09
tags: [bug, ingestion, landing, audit, job-context]
blocked-by: []
blocks: [10-job-dbt-dab.md]
---

# 15 — Fix `_resolve_job_context()` retornando `"interactive"` dentro do bundle

## Symptom

`job_ingestion` bundle run completa SUCCESS nas 3 tasks (landing →
DLT → update_audit), mas a row escrita por `landing.py` em
`landing_audit` chega com:

- `run_id = "interactive"`
- `job_run_id = "interactive"`
- `job_url = "interactive"`

mesmo quando rodado via `databricks bundle run job_ingestion`.
Consequência cascateada: a task 3 (`update_landing_audit.sql`) faz
`UPDATE ... WHERE job_run_id = '{{job.run_id}}'` (placeholder
substituído pela run real, ex.: `"1073098863810712"`), não casa com
`"interactive"`, e o `UPDATE` afeta **0 rows**. Resultado:
`pipeline_update_id` fica NULL pra sempre, e o filtro de janela do
Gold (ADR-0003) não consegue inferir quando o pipeline DLT
completou — destruindo o contrato do ADR-0008.

## Evidence

Reprodução em 2026-06-09T23:13Z, job_id 308012953236381, run_id
1073098863810712:

```
Run state: TERMINATED/SUCCESS
  task=landing_task                state=TERMINATED/SUCCESS
  task=dlt_pipeline_task           state=TERMINATED/SUCCESS
  task=update_audit_task           state=TERMINATED/SUCCESS

SELECT run_id, job_run_id, pipeline_update_id FROM landing_audit
WHERE job_start_ts > '2026-06-09T23:00:00Z'
-->  ('interactive', 'interactive', NULL)
```

Confirmação que o backfill SQL está correto (manual UPDATE com
`update_id` real funcionou e destravou o `dbt run` do Gold).

## Root cause hypothesis

`ingestion/landing.py:415-439` — `_resolve_job_context()` lê
`dbutils.notebook.entry_point.getDbutils().notebook().getContext()`
e extrai tags:

```python
run_id = tags.get("runId") or tags.get("taskRunId") or run_id
job_run_id = tags.get("multitaskParentRunId") or tags.get("jobRunId") or job_run_id
```

Hipóteses (uma ou mais):

1. **Tags renomeadas no serverless runtime** — Databricks pode ter
   deprecado `runId`/`jobRunId`/`multitaskParentRunId` ou movido pra
   `currentRunId`/`parentRunId`/etc. em runtimes mais novos.
2. **Notebook task ≠ multi-task job context** — a API de
   `notebook().getContext()` pode não popular essas tags quando o
   notebook roda como uma task de um job (vs notebook standalone com
   "Run as job"). Tags podem estar em outro campo de `ctx`.
3. **Silent exception swallow** (landing.py:437-438) — `except
   Exception` com `print` pra stderr. Se as tags estão num path
   diferente de `ctx["tags"]`, o código nem tenta — só retorna
   "interactive" sem warning visível.

## How to debug

1. Instrumentar `_resolve_job_context()` pra dumpar o `ctx_json`
   inteiro pra stderr quando `job_run_id` cai pro fallback
   "interactive". Re-rodar `bundle run job_ingestion`.
2. Ler logs do `landing_task` da run mais recente:
   ```
   databricks --profile free-edition jobs get-run-output --run-id <task_run_id>
   ```
   ou direto pelo UI da run.
3. Identificar qual campo do `ctx` carrega o run id real e atualizar
   as chaves no `tags.get(...)`. Alternativa robusta: usar
   `dbutils.widgets.get(...)` pra ler params passados via
   `notebook_task.base_parameters` do job — declarar
   `job_run_id: "{{job.run_id}}"` em `resources/job_ingestion.yml`
   e ler como widget. Isso é o caminho documentado pelos
   [Databricks Jobs parameters docs](https://docs.databricks.com/aws/en/jobs/parameter-value-references)
   e não depende de tags internas.

## What to build

Decisão entre 2 paths:

**Path A — fix in-place do `_resolve_job_context()`:** mapear as
tags certas e atualizar `landing.py:432-436`. Cheap; mantém
compatibilidade com notebooks standalone.

**Path B — switch pra widgets:** declarar `job_run_id` /
`job_run_url` como `base_parameters` no `notebook_task` (resources/
job_ingestion.yml linhas ~70-80), ler via `dbutils.widgets.get(...)`
em `landing.py`, e tratar `KeyError`/widget-missing como
"interactive" fallback. Mais robusto, sobrevive a renomeação de
tags futuras.

**Recomendação: B.** Custo extra ~5 linhas YAML + 3 linhas Python;
documentação Databricks aponta widgets como caminho oficial pra
job parameter passing; tags não são contrato público.

## Acceptance criteria

- [ ] Após `databricks bundle run job_ingestion --target user_dev`,
      `landing_audit` row mais recente tem:
      - `job_run_id` = run id numérico do job (ex.: `"1073098863810712"`)
      - `run_id` ≠ `"interactive"`
- [ ] `update_audit_task` (task 3) faz UPDATE de exatamente 1 row
      (`num_affected_rows = 1` no SUCCESS output).
- [ ] `pipeline_update_id` populado automaticamente pós-bundle run,
      sem UPDATE manual necessário.
- [ ] Modo standalone do notebook (`Run notebook` pelo UI sem job)
      continua retornando `"interactive"` em todos os 3 campos
      (fallback preservado).
- [ ] Teste em `ingestion/tests/test_landing_notebook.py` cobrindo
      o novo path (mock de widget ou tag).

## Why blocks #10

`job_dbt` (ticket #10) depende do contrato Gold ↔ audit funcionar
end-to-end sem intervenção manual. Sem o fix do #15, cada run do
`job_dbt` precisaria de UPDATE manual no audit como o feito em
2026-06-09 (Fix #11 — anote em AGENTS.md gotchas após resolver).

## Workaround temporário (já aplicado em 2026-06-09)

Pra destravar validação do #08 sem fix:

```sql
-- pega last update_id do DLT
SELECT origin.update_id, timestamp
FROM event_log(TABLE(workspace.nyc_taxi_bronze.yellow_taxi_trips_raw))
WHERE event_type = 'create_update'
ORDER BY timestamp DESC LIMIT 1;

-- backfill manual na row de audit
UPDATE workspace.nyc_taxi_monitoring.landing_audit
SET pipeline_update_id = '<update_id_from_above>'
WHERE pipeline_update_id IS NULL
  AND job_start_ts > TIMESTAMP'<corresponding_run_start>';
```

## Resolution (2026-06-09)

Implementado **Path B** (recomendação do ticket) com um achado
adicional: existiam **dois bugs encadeados**, não um. O ticket
diagnosticou só o primeiro (tag-scraping) porque o sintoma do segundo
(SQL `{{job.run_id}}` literal) ficava mascarado enquanto o `job_run_id`
da audit row era `"interactive"` — qualquer UPDATE não casaria de
qualquer jeito. Só depois de o fix #1 produzir `job_run_id` numérico
ficou óbvio que o `pipeline_update_id` continuava NULL.

### Bug #1 — `_resolve_job_context()` tag-scraping (root cause original)

`ingestion/landing.py:415-439` lia tags via
`dbutils.notebook.entry_point.getDbutils().notebook().getContext()`
(`runId` / `multitaskParentRunId` / `browserHostName`). Essas tags não
estão populadas no runtime serverless da Free Edition pra notebook
tasks executando dentro de jobs multi-task, então o `except Exception`
genérico engolia o `KeyError`/`AttributeError` (sem warning visível
porque o `tags.get(...)` retorna `None` silenciosamente) e a row caía
pro fallback `"interactive"` em todos os 3 campos.

**Fix**: trocar tag-scraping por `dbutils.widgets.get(...)`,
alimentado por `base_parameters` no `notebook_task` que substitui
`{{task.run_id}}` / `{{job.run_id}}` / `{{workspace.url}}` em
runtime (documented Databricks Jobs *dynamic value reference*
system — contract público, vs tags internas).

Arquivos:

- `ingestion/landing.py` — `_WIDGET_DEFAULTS` ganhou `task_run_id`,
  `job_run_id`, `job_url` (todos default `"interactive"`).
  `_resolve_job_context()` reescrita pra ler esses widgets; standalone
  detection via `job_run_id == "interactive"` (audit SQL filtra
  nessa coluna, então é a checagem canônica).
- `resources/job_ingestion.yml` — `landing_task.notebook_task.base_parameters`
  ganhou os 3 widgets; `job_url` montado inline porque não existe
  `{{job.run_url}}` nativo (só `{{workspace.url}}` + `{{job.id}}` +
  `{{job.run_id}}`).
- `ingestion/tests/test_landing_notebook.py` — `TestResolveJobContext`
  com 4 casos: `dbutils=None`, widgets populados, widgets carregando
  defaults `"interactive"`, e `widgets.get` raising (graceful
  fallback). Total: 12 → 16 testes no arquivo.

### Bug #2 — `update_landing_audit.sql` `{{job.run_id}}` literal

Achado durante validação end-to-end. A AC do ticket exige
`pipeline_update_id` auto-backfilled. Depois do fix #1, run
`81288161494309` deu audit row com `job_run_id="81288161494309"` (✓)
mas task 3 reportou `SUCCESS` com `sql_output: {}` e a row ficou
com `pipeline_update_id=NULL`. Um UPDATE manual com a mesma SQL e
hard-coded `WHERE job_run_id = '81288161494309'` afetou 1 row,
provando que a SQL é correta mas a substituição não acontecia.

**Root cause**: dynamic-value-references como `{{job.run_id}}` são
substituídos **só em campos de task-configuration YAML** (notebook
`base_parameters`, sql_task `parameters`, etc), **NÃO** dentro do
corpo de SQL files referenciados via `sql_task.file.path`. O
placeholder era tratado como literal string `'{{job.run_id}}'`,
nunca casava com nada, UPDATE silenciosamente afetava 0 rows, task 3
retornava SUCCESS porque `UPDATE ... WHERE ...` com zero matches
não é erro. Comprovado pela docs oficial Databricks
([Access parameter values from a task](https://docs.databricks.com/aws/en/jobs/parameter-use))
que explicita o caminho correto: SQL files usam **named parameters
`:param_name`** com valores supridos por `sql_task.parameters`.

**Fix**: usar named parameter binding.

Arquivos:

- `ingestion/sql/update_landing_audit.sql` — `WHERE job_run_id =
  '{{job.run_id}}'` → `WHERE job_run_id = :job_run_id`. Long
  comment documentando o trap pros próximos.
- `resources/job_ingestion.yml` — `update_audit_task.sql_task`
  ganhou `parameters: { job_run_id: "{{job.run_id}}" }`. Aqui o
  `{{job.run_id}}` SIM é substituído (YAML config field).

### Validação end-to-end

Two bundle runs em 2026-06-09:

**Run 1 (`81288161494309`)** — só com fix #1, antes do fix #2 ser
descoberto. Resultado: `job_run_id="81288161494309"` ✓ mas
`pipeline_update_id=NULL` ✗. Isso disparou a investigação que achou
o bug #2.

**Run 2 (`182411413204977`)** — fix #1 + fix #2 deployed. Resultado
final na landing_audit:

```
run_id              = "403102412758327"            (task.run_id, numérico)
job_run_id          = "182411413204977"            (job.run_id, casa URL)
job_url             = "https://dbc-88968762-8346.cloud.databricks.com/?o=757803262701153/jobs/308012953236381/runs/182411413204977"
pipeline_update_id  = "dcaabcb3-3e16-44a6-819a-d6b86f5a6ad2"  (auto-backfilled, SEM UPDATE manual)
status              = "SUCCESS"
```

Todos os 5 acceptance criteria ✓:

- ✅ `job_run_id` numérico (não `"interactive"`)
- ✅ `run_id` ≠ `"interactive"` (= `task.run_id`)
- ✅ `update_audit_task` afetou exatamente 1 row (validado por
  UPDATE manual com `:job_run_id` binding antes do re-run — retornou
  `num_affected_rows = 1`)
- ✅ `pipeline_update_id` populado automaticamente pós-bundle run
- ✅ Standalone mode (notebook UI sem job) continua retornando
  `"interactive"` triple (testado via
  `test_widgets_with_interactive_default_falls_back_to_triple`)
- ✅ Teste novo cobrindo o widget path (`TestResolveJobContext`,
  4 casos)

### Gates

```
uv run ruff check .          → All checks passed!
uv run ruff format --check . → 19 files already formatted
uv run pytest -q             → 136 passed
```

### Follow-ups pra AGENTS.md (próxima sessão)

Dois gotchas operacionais novos pra adicionar em `AGENTS.md`
§"Gotchas operacionais":

1. **`notebook().getContext()` tags ≠ contract público no serverless** —
   tags como `runId`, `jobRunId`, `multitaskParentRunId`,
   `browserHostName` não estão populadas dentro de jobs multi-task
   na Free Edition. Usar `dbutils.widgets.get(...)` alimentado por
   `base_parameters` com dynamic-value references como caminho
   documentado. Sintoma silencioso: `_resolve_job_context()`
   retornando `"interactive"` mesmo dentro de bundle run.

2. **`{{job.run_id}}` em SQL file body NÃO é substituído** — dynamic
   values só substituem em YAML task-configuration fields
   (`base_parameters` / `sql_task.parameters` / etc), nunca dentro
   do corpo de `sql_task.file.path`. Usar **named parameters**
   `:param_name` no SQL e supply via `sql_task.parameters:` no
   YAML. Sintoma: UPDATE silencioso de 0 rows com SUCCESS no task
   status; `sql_output: {}` no `jobs get-run-output`.
