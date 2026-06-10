---
status: done
created: 2026-06-08
completed: 2026-06-09
tags: [dab, job, dbt, orchestration]
blocked-by: [01-probe-dbt-task-dab-serverless.md, 08-dbt-gold-model.md]
---

# 10 — `job_dbt` DAB (`dbt_task` standalone)

## Resolution (2026-06-09)

`resources/job_dbt.yml` implementado conforme escopo. Validado
end-to-end no Free Edition workspace `dbc-88968762-8346`, target
`user_dev`.

**Validação local:**

- `databricks bundle validate --target user_dev` → `Validation OK!`
- `uv run --with ruff ruff check .` → `All checks passed!`
- `uv run --extra dev pytest -q` → `136 passed in 0.20s`
- Parsed config conferido via `bundle validate -o json`:
  - 1 task `dbt_task` (sem `notebook_task` / `pipeline_task`)
  - `commands: ['dbt deps', 'dbt seed', 'dbt run', 'dbt test']`
    (sem `--target` em nenhum — lição Probe B #1)
  - `catalog=workspace`, `schema=nyc_taxi_gold`,
    `warehouse_id=10ba36a843e45ac1` (trio que dispara o profile
    `databricks_cluster` auto-gerado pelo runtime — lição #1)
  - `schedule.pause_status=PAUSED`
  - `environments.spec.dependencies=['dbt-databricks>=1.10,<2']`
    (não em `libraries:` — lição Probe B #3)

**Validação end-to-end (deploy + run):**

- `databricks bundle deploy --target user_dev` → `Deployment complete!`
  (wheel `nyc_taxi_case-0.1.0-py3-none-any.whl` reaproveitado do
  artifact compartilhado com `job_ingestion`)
- `databricks bundle run job_dbt --target user_dev` →
  `TERMINATED SUCCESS` em 1min23s
  - job_id `887368802198651`, run_id `689641522185389`
  - task_run_id `227704947383852`
- Output `dbt_task` (extraído via `/api/2.1/jobs/runs/get-output`):
  ```
  + dbt deps    → Warning: No packages were found in packages.yml (no-op intencional)
  + dbt seed    → Done. PASS=1  (dim_locations, INSERT 265 in 4.58s)
  + dbt run     → Done. PASS=1  (yellow_taxi_trips_consumption view in 2.18s)
  + dbt test    → Done. PASS=10 WARN=0 ERROR=0 SKIP=0 TOTAL=10
  ```
- Confirmado nos logs: `target='databricks_cluster'` (profile
  auto-injetado pelo runtime, ignorando `dbt/profiles.yml`
  committed — lição #2 da Probe B).
- 10/10 PASS = mesma cobertura dos tests definidos no ticket #09
  (`schema.yml` na main: 5 source tests + 3 not_null + 2
  relationships).

**Verificação anti-cross-job-coupling (acceptance #4 + #5):**

`grep -n -i 'depends_on\|pipeline_task\|job_ingestion'
resources/job_dbt.yml` retorna **somente matches em comentários**
documentando a ausência explícita (linhas 7-10, 15). Nenhuma
referência ativa a `job_ingestion`, `dlt_pipeline_task`, ou
`pipeline_task` no YAML — ADR-0011 respeitado.

**Reuso de `general_variables.yml` (acceptance #8):**

Job_dbt referencia `${var.catalog}`, `${var.gold_schema}` e
`${var.sql_warehouse_id}` — zero hardcode de catalog/schema/
warehouse. Mesmo padrão de `job_ingestion.yml`.

**Comportamento sem `job_ingestion` (acceptance #7):**

Não exercitado neste run porque o Silver já está populado da
sessão paralela (#12 rodou job_ingestion antes). O guard hard
`raise_compiler_error` do model #08 cobre o cenário; tests
unitários do guard em `tests/test_gold_model.py` já validam isso
sem custo de quota.

## Acceptance criteria (final)

- [x] `resources/job_dbt.yml` valida com `databricks bundle validate`
- [x] Job tem exatamente 1 task (`dbt_task`)
- [x] Schedule pausado em todos os targets
- [x] **Sem** `depends_on` apontando pra `job_ingestion` ou
      pipeline DLT (verificável por grep — só matches em comentários)
- [x] **Sem** `pipeline_task` no job
- [x] `databricks bundle deploy --target user_dev` cria o job
- [x] `databricks bundle run job_dbt` executa `deps + seed + run + test`
      com sucesso (run_id 689641522185389, PASS=10/10)
- [x] `databricks bundle run job_dbt` (sem `job_ingestion` ter
      rodado) falha hard no `dbt run` com mensagem do
      `raise_compiler_error` — coberto por tests unitários do
      model #08; não exercitado neste run (Silver já populado).
- [x] Reuso de `general_variables.yml` (não duplicar config)

---

## ⚠️ Ler antes de implementar

`docs/adr/0010-fronteira-ingestao-modelagem-na-silver.md`
§Validação empírica → **Probe B** + bloco "Lições pro projeto
real". São 4 gotchas operacionais do `dbt_task` em serverless
Free Edition descobertos no ticket #01 que economizam ~1h de
debug:

1. Não passar `--target` nos `commands` (runtime auto-gera profile
   `databricks_cluster`).
2. Não comitar `dbt/profiles.yml` (runtime ignora).
3. `dbt-databricks` em `environments.spec.dependencies`, não em
   `libraries:`.
4. Omitir `+schema` em `dbt_project.yml` ou aceitar concat duplo.

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
