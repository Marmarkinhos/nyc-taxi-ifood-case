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

## Contexto rápido

- Plano completo: `docs/PLAN.md`
- Enunciado original do case: `docs/CASE.md`
- Decisões emergentes: `docs/adr/`
- Vocabulário load-bearing: `CONTEXT.md`
