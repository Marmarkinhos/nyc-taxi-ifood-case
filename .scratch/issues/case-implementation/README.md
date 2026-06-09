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
| [07](./07-dbt-project-skeleton.md) | dbt project + `sources.yml` + seed dim | `ready-for-agent` | AFK | #06 |
| [08](./08-dbt-gold-model.md) | dbt Gold model + filtro janela + enrichment | `ready-for-agent` | AFK | #07 |
| [09](./09-dbt-tests.md) | dbt tests (4 inventariados) | `ready-for-agent` | AFK | #08 |
| [10](./10-job-dbt-dab.md) | `job_dbt` DAB | `ready-for-agent` | AFK | #01, #08 |
| [11](./11-dbt-analyses.md) | dbt analyses (perguntas + EDA) | `ready-for-agent` | AFK | #08 |
| [12](./12-notebook-dashboard.md) | Notebook `answers.py` + AI/BI dashboard | `ready-for-agent` | AFK | #11 |
| [13](./13-readme-finalization.md) | README + monitoring view + revogação PAT | `ready-for-human` | HITL | #12 |

## Caminhos críticos

- **Critical path principal:** #02 → #03 → #04 → #06 → #07 → #08 → #11 → #12 → #13 (9 tickets sequenciais)
- **Critical path dbt:** #01 (probe) → #10 (independente do critical path principal até #08)
- **Paralelizáveis após #04:** #05 (expectations) e #06 (DAB) podem rodar simultâneos
- **Paralelizáveis após #08:** #09 (tests), #10 (job_dbt, se #01 ok), #11 (analyses)

## Próximo passo

#01 PASS (2026-06-08), #02 fechou (2026-06-09), #03 fechou
(2026-06-09), #04 fechou (2026-06-09). Próximo na critical path:
**#06 — `job_ingestion` DAB** (wiring landing notebook → DLT pipeline
→ post-DLT SQL `UPDATE landing_audit`). Paralelizável: **#05 — DLT
expectations** (6 Silver + 1 Bronze warn-only). Critical path
restante: #06 → #07 → #08 → #11 → #12 → #13.
