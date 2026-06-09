---
status: ready-for-agent
created: 2026-06-08
tags: [dab, job, dbt, orchestration]
blocked-by: [01-probe-dbt-task-dab-serverless.md, 08-dbt-gold-model.md]
---

# 10 — `job_dbt` DAB (`dbt_task` standalone)

## What to build

`resources/job_dbt.yml` com `dbt_task` standalone (ADR-0011 lado
modelagem). **Não menciona pipeline DLT, landing notebook, nem
schemas de ingestão.**

**1 task:**

- `dbt_task`:
  - `project_directory: ../dbt`
  - `commands:`
    - `dbt deps`
    - `dbt seed`
    - `dbt run`
    - `dbt test`
  - Profile: `databricks` (mesmo do #07)
  - Sem `depends_on` cross-job, sem referência a `job_ingestion`,
    sem `pipeline_task`.

**Schedule pausado** em todos os targets.

**Comportamento esperado se `job_ingestion` nunca rodou:**

- `dbt deps` ok
- `dbt seed` cria `dim_locations` ok
- `dbt run` falha hard via `raise_compiler_error` do #08 com
  mensagem acionável
- `dbt test` não chega a rodar

## ⚠️ Dependência do ticket #1

**Se probe Opção B (#1) FALHOU:**

- Este ticket **deixa de existir** como está.
- Substituir por nova issue: "Runbook dbt CLI: documentar
  `cd dbt && dbt run` no README como step manual pós-`bundle run
  job_ingestion`".
- ADR-0010 §Consequências já cobre esse fallback.

**Se probe Opção B (#1) PASSOU:** seguir conforme escopo acima.

## Acceptance criteria

- [ ] `resources/job_dbt.yml` valida com `databricks bundle validate`
- [ ] Job tem exatamente 1 task (`dbt_task`)
- [ ] Schedule pausado em todos os targets
- [ ] **Sem** `depends_on` apontando pra `job_ingestion` ou
      pipeline DLT (verificável por grep)
- [ ] **Sem** `pipeline_task` no job
- [ ] `databricks bundle deploy --target user_dev` cria o job
- [ ] `databricks bundle run job_dbt` (após `job_ingestion` ter
      rodado) executa `deps + seed + run + test` com sucesso
- [ ] `databricks bundle run job_dbt` (sem `job_ingestion` ter
      rodado) falha hard no `dbt run` com mensagem do
      `raise_compiler_error` visível nos logs
- [ ] Reuso de `general_variables.yml` (não duplicar config)

## Blocked by

- `01-probe-dbt-task-dab-serverless.md` (probe Opção B; resultado
  define se este ticket existe na forma atual ou vira fallback)
- `08-dbt-gold-model.md` (precisa de modelos pra rodar)
