---
status: ready-for-agent
created: 2026-06-09
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
