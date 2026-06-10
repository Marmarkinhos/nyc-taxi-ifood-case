# Feature: case-implementation

Implementação completa do case NYC Yellow Taxi, quebrada via skill
`to-issues` em 13 vertical slices.

## Contexto

- Plano arquitetural: `docs/PLAN.md` (histórico)
- Decisões correntes: `docs/adr/` (ADRs 0001-0011, todos Accepted)
- Vocabulário load-bearing: `CONTEXT.md`
- Handoff de origem: `/tmp/handoff-wTX7WG.md` (fim da sessão grilling pt4)

## Tickets (ordem de dependência)

| # | Título | Status | Tipo | Bloqueado por |
|---|---|---|---|---|
| [01](./01-probe-dbt-task-dab-serverless.md) | Probe Opção B `dbt_task` no DAB serverless | `done` ✅ PASS | HITL | — |
| [02](./02-repo-skeleton-helpers-ci.md) | Repo skeleton + helpers + CI | `done` ✅ | AFK | — |
| [03](./03-landing-notebook.md) | Landing notebook + `landing_audit` | `done` ✅ | AFK | #02 |
| [04](./04-dlt-bronze-silver-canonica.md) | DLT Bronze + Silver canônica | `done` ✅ | AFK | #03 |
| [05](./05-dlt-expectations.md) | DLT expectations (6 Silver + 1 Bronze warn) | `done` ✅ | AFK | #04 |
| [06](./06-job-ingestion-dab.md) | `job_ingestion` DAB | `done` ✅ | AFK | #04 |
| [07](./07-dbt-project-skeleton.md) | dbt project + `sources.yml` + seed dim | `done` ✅ | AFK | #06 |
| [08](./08-dbt-gold-model.md) | dbt Gold model + filtro janela + enrichment | `done` ✅ | AFK | #07 |
| [09](./09-dbt-tests.md) | dbt tests (4 inventariados) | `done` ✅ | AFK | #08 |
| [10](./10-job-dbt-dab.md) | `job_dbt` DAB | `done` ✅ | AFK | #01, #08, #15 |
| [11](./11-dbt-analyses.md) | dbt analyses (perguntas + EDA) | `done` ✅ | AFK | #08 |
| [12](./12-notebook-dashboard.md) | Notebook `answers.py` + AI/BI dashboard | `done` ✅ | AFK | #11 |
| [13](./13-readme-finalization.md) | README + monitoring view + revogação PAT | `done` ✅ (PAT revogação manual HITL pendente do user) | HITL | #12 |
| [14](./14-bronze-drift-metrics.md) | Bronze drift metrics + job-level alerting (gap do ADR-0014) | `wontfix` (over-engineering, user decidiu) | AFK | — |
| [15](./15-resolve-job-context-bug.md) | Fix `_resolve_job_context()` retornando `"interactive"` no bundle | `done` ✅ | AFK | — |

## Caminhos críticos (histórico)

- **Critical path principal:** #02 → #03 → #04 → #06 → #07 → #08 → #11 → #12 → #13 (9 tickets sequenciais)
- **Critical path dbt:** #01 (probe) → #10 (independente do critical path principal até #08)
- **Paralelizáveis após #04:** #05 (expectations) e #06 (DAB) rodaram simultâneos
- **Paralelizáveis após #08:** #09 (tests), #10 (job_dbt, bloqueado por #15), #11 (analyses)
- **Última onda paralela (2026-06-09):** #10 (job_dbt DAB) + #12 (notebook +
  dashboard) via Agent Manager worktrees, zero overlap, ambos mergeados
  limpos.

## Status final

**13 de 14 tickets fechados** (#14 marcado `wontfix` por decisão do
user). Case end-to-end pronto pra avaliador:

- Silver `workspace.nyc_taxi_bronze.yellow_taxi_trips` — 16.04M rows
- Gold `workspace.nyc_taxi_gold.yellow_taxi_trips_consumption` — 16.04M
  rows enriquecidas com borough/zone
- `dim_locations` seed — 265 rows
- `job_ingestion` (id `308012953236381`, 4 tasks: landing →
  dlt_pipeline → update_audit → refresh_monitoring_view) e `job_dbt`
  (id `887368802198651`, 1 task: dbt deps/seed/run/test), ambos
  independentes (ADR-0011), ambos com schedule pausado, execução
  manual via `bundle run`
- Notebook `notebooks/answers.py` + AI/BI dashboard (DAB) renderizando
  Q1/Q2 + EDA contra o Gold
- Monitoring view `workspace.nyc_taxi_monitoring.gold_pipeline_observability`
  expondo o event_log do DLT (#13)
- README root reescrito cobrindo TL;DR + runbook + arquitetura +
  ADRs + limitações Free Edition (#13)

**HITL pendente do user** (não bloqueia avaliador, é higiene):
revogar PAT Free Edition na UI da Databricks + `git push origin main`
dos commits locais.
