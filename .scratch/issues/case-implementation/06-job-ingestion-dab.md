---
status: ready-for-agent
created: 2026-06-08
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
