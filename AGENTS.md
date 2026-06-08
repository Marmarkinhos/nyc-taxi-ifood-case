# AGENTS.md — nyc-taxi-case

Repositório do case técnico de Data Engineering: pipeline NYC Yellow Taxi
em Databricks Free Edition (DAB + DLT + Auto Loader).

## Issue tracker

Local markdown sob `.scratch/issues/` (padrão Matt Pocock). Sem GitHub
Issues — case roda solo, sem time.

## Triage labels (frontmatter dos .md em .scratch/issues/)

- `needs-triage` — recém-criada, não revisada
- `needs-info` — falta contexto pra começar
- `ready-for-agent` — pronta pra execução autônoma
- `ready-for-human` — precisa decisão antes de prosseguir
- `wontfix` — descartada

## Domain docs

`CONTEXT.md` (raiz) + `docs/adr/` (Architecture Decision Records).

## Skills relevantes

- `setup-matt-pocock-skills` — roda 1x pra popular `docs/agents/`
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
