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
| [09](./09-dbt-tests.md) | dbt tests (4 inventariados) | `ready-for-agent` | AFK | #08 |
| [10](./10-job-dbt-dab.md) | `job_dbt` DAB | `ready-for-agent` | AFK | #01, #08, **#15** |
| [11](./11-dbt-analyses.md) | dbt analyses (perguntas + EDA) | `ready-for-agent` | AFK | #08 |
| [12](./12-notebook-dashboard.md) | Notebook `answers.py` + AI/BI dashboard | `ready-for-agent` | AFK | #11 |
| [13](./13-readme-finalization.md) | README + monitoring view + revogação PAT | `ready-for-human` | HITL | #12 |
| [14](./14-bronze-drift-metrics.md) | Bronze drift metrics + job-level alerting (gap do ADR-0014) | `ready-for-agent` | AFK | #06 |
| [15](./15-resolve-job-context-bug.md) | Fix `_resolve_job_context()` retornando `"interactive"` no bundle | `ready-for-agent` | AFK | — |

## Caminhos críticos

- **Critical path principal:** #02 → #03 → #04 → #06 → #07 → #08 → #11 → #12 → #13 (9 tickets sequenciais)
- **Critical path dbt:** #01 (probe) → #10 (independente do critical path principal até #08)
- **Paralelizáveis após #04:** #05 (expectations) e #06 (DAB) podem rodar simultâneos
- **Paralelizáveis após #08:** #09 (tests), #10 (job_dbt, se #01 ok), #11 (analyses)

## Próximo passo

#01 PASS (2026-06-08), #02-#07 fecharam (2026-06-09), **#08 fechou
(2026-06-09)** — `workspace.nyc_taxi_gold.yellow_taxi_trips_consumption`
materializada como view, 16.044.080 rows (= Silver filtrada por janela
jan-mai 2023), 100% enriquecida com borough/zone. Bug descoberto no
caminho: `_resolve_job_context()` retorna `"interactive"` no bundle →
`pipeline_update_id` não backfilla; workaround via UPDATE manual.
Registrado em #15 (bloqueia #10).

**Próximo na critical path: #11 — dbt analyses** (perguntas Q1/Q2 +
EDA do case). #09 (tests) e #10 (job_dbt; agora bloqueado por #15)
ficam em paralelo. Critical path restante: #11 → #12 → #13.
