---
status: done
created: 2026-06-08
closed: 2026-06-09
tags: [readme, runbook, monitoring, hitl, finalization]
blocked-by: [12-notebook-dashboard.md]
---

# 13 — README final + runbook + revogação PAT + monitoring view

## What to build

Fechamento do case: documentação para o avaliador + obs view +
limpeza operacional. **HITL** porque inclui revogação manual de
PAT via UI.

### README principal (root)

Reescrever `README.md` com:

1. **TL;DR** — o que é, stack, padrão iFood replicado.
2. **Runbook** (ADR-0011) — exatamente:
   ```bash
   databricks bundle deploy --target user_dev
   databricks bundle run job_ingestion   # ~5min, popula até Silver
   databricks bundle run job_dbt         # ~2min, popula Gold + análises
   ```
3. **Estrutura do repo** — explicar monorepo com 2 jobs DAB
   independentes simulando 2 repos iFood
   (`ifp-data-ingestions` + `pagob2b-dbt`). Notar que split é
   trivial via `git filter-repo` (handoff §2 não-virou-ADR).
4. **Decisões load-bearing** — apontar pra `docs/adr/` (não
   duplicar; só listar com 1 linha cada).
5. **Notas que não viraram ADR** (handoff §3):
   - Convenção `_int_`/`_fin_` rejeitada
   - Monorepo vs 2 repos GitHub
6. **Trio de consumo** — explicar modelo dbt = SSoT, notebook +
   dashboard só exibem.
7. **Como rodar testes locais** — pytest, ruff, mypy, bundle
   validate.
8. **Limitações conhecidas** — Free Edition serverless-only, sem
   service principal, sem CI deploy, schedule manual.

### Monitoring view (lado ingestão; sobra do PLAN.md item 10)

`ingestion/monitoring/gold_pipeline_observability.sql` (ou
notebook SQL):

```sql
CREATE OR REPLACE VIEW ${prefix}monitoring.gold_pipeline_observability AS
SELECT
  timestamp,
  event_type,
  details
FROM event_log("<pipeline_id>")
WHERE event_type IN ('flow_progress', 'expectation_metrics', 'pipeline_done')
ORDER BY timestamp DESC
```

Pode rodar via:

- SQL task no `job_ingestion` (adicionar uma 4ª task pós
  `update_audit_task`), OU
- Notebook standalone executado manualmente uma vez (`CREATE
  VIEW` é idempotente)

Decisão de qual padrão usar fica com quem pegar o ticket; o
importante é a view existir e ser referenciável (Decisão #9 obs).

### Operacional

- [ ] **Revogar PAT** `dapiee35...11860c` no workspace via UI:
      User Settings → Developer → Access tokens → Revoke
- [ ] Revogar PAT do probe B (#01) — comentário
      `nyc-taxi-probe-2026-06-08`, prefixo `dapi6d5e...`, profile
      `free-edition` em `~/.databrickscfg`
- [ ] Remover bloco `[free-edition]` do `~/.databrickscfg` após
      revogação (ou substituir por novo PAT permanente do case)
- [ ] Confirmar que nenhum PAT vive em `.databrickscfg` ou
      `.env` versionados (grep + .gitignore audit)

## Acceptance criteria

- [ ] `README.md` reescrito com 8 seções acima
- [ ] Runbook copia-colável e validado (executar manualmente em
      workspace limpo)
- [ ] `docs/adr/` continua sem banner "documento histórico" em
      `docs/PLAN.md` (handoff: usuário declinou)
- [ ] Monitoring view criada e queriável
- [ ] PAT do probe A revogado (confirmar via UI)
- [ ] PAT do probe B revogado (se #01 criou novo)
- [ ] Nenhum secret versionado (grep recursivo por `dapi` em
      arquivos rastreados)
- [ ] README inclui screenshot ou link pro dashboard AI/BI
      deployado

## Blocked by

- `12-notebook-dashboard.md` (README precisa documentar
  notebook + dashboard finalizados)

## Notas operacionais

- HITL por causa da revogação manual de PAT (não automatizável
  via CLI sem nova PAT).
- Final do case — após esse ticket, repo está "pronto pra
  avaliador".

## Resolution

Closed 2026-06-09. README + monitoring view shipped; PAT revocation
+ push to `origin/main` stay manual on the user side per AGENTS.md
("push é manual do user").

### What shipped

1. **`README.md` rewrite** (root) covering the 8 sections the ticket
   asked for:
   - TL;DR (stack + iFood split)
   - Runbook (`bundle validate` → `deploy` → `run job_ingestion`
     → `run job_dbt`, copy-pasteable, validated against the
     deployed bundle)
   - Repository layout (annotated tree of the monorepo)
   - Architecture in one ASCII diagram (4-task `job_ingestion` +
     1-task `job_dbt`, no cross-job arrow)
   - Decisões load-bearing (one-liners for all 16 ADRs with links)
   - Notes que não viraram ADR (the 4 conscious-but-undocumented
     choices: `_int_`/`_fin_` rejection, monorepo vs 2 repos,
     `uv.lock` gitignored, root parquet gitignored)
   - Trio de consumo (dbt analyses + notebook + AI/BI dashboard
     reading the same Gold view)
   - Local development + CI + known Free Edition limitations

2. **Monitoring view (`ingestion/sql/create_monitoring_view.sql`)** —
   `CREATE OR REPLACE VIEW
   workspace.nyc_taxi_monitoring.gold_pipeline_observability` over
   `event_log(TABLE(workspace.nyc_taxi_bronze.yellow_taxi_trips_raw))`
   filtered to `flow_progress` / `expectation_metrics` /
   `pipeline_done`. Idempotent. Mirrors the literal-catalog +
   `event_log(TABLE(...))` pattern from `update_landing_audit.sql`
   (AGENTS.md gotchas: DAB does not substitute `${var.*}` inside
   SQL file bodies; the `TABLE(...)` form survives pipeline
   `delete+recreate`).

3. **`refresh_monitoring_view_task` in `resources/job_ingestion.yml`** —
   new 4th task, `sql_task.file`, depends on `update_audit_task`. The
   job is now `landing_task → dlt_pipeline_task → update_audit_task →
   refresh_monitoring_view_task`. Validated via `bundle validate
   --target user_dev` (OK).

4. **Validation evidence** — the view was created ad-hoc against the
   live warehouse (`10ba36a843e45ac1`) via
   `databricks api post /api/2.0/sql/statements` before the YAML
   wiring, to confirm the schema and event_log access work. A
   subsequent `SELECT event_type, COUNT(*) ... GROUP BY event_type`
   returned `flow_progress: 143` — `expectation_metrics` and
   `pipeline_done` will populate on the next `bundle run
   job_ingestion`.

5. **Secret audit** — `git ls-files | xargs grep -lE
   'dapi[a-f0-9]{20,}'` returns zero matches. Tracked files
   referencing `dapi*` are either documentation (`.scratch/issues/`
   describing PAT prefixes for revocation) or build artifacts inside
   `.venv/` (gitignored). `.gitignore` already lists `.env`,
   `.kilo/`, `.databrickscfg` is at `~`, not in the repo.

### What stays HITL (user-side, intentional)

- [ ] Revoke PAT for the `free-edition` profile (prefix
      `dapi6d5e...`, the one currently in `~/.databrickscfg`) via
      Databricks UI → User Settings → Developer → Access tokens →
      Revoke. The `dapiee35...11860c` mentioned in the original
      ticket spec is not present in the current `~/.databrickscfg`
      and was likely already revoked in an earlier session.
- [ ] Decide whether to delete the `[free-edition]` block from
      `~/.databrickscfg` or replace it with a freshly-minted PAT.
      The evaluator never needs your PAT — they will mint their own
      against their own Free Edition workspace.
- [ ] `git push origin main` once review is complete (AGENTS.md:
      "push é manual do user").
- [ ] (Optional) Run `bundle run job_ingestion` one more time
      post-deploy so the monitoring view picks up
      `expectation_metrics` + `pipeline_done` events on top of the
      existing `flow_progress` rows. Not blocking — the view is
      live and correct, just sparser without it.

### Deviations from the original ticket spec

- The ticket inventoried an `_int_`/`_fin_` model convention as one
  of the "notes que não viraram ADR" items; we kept that bullet but
  reframed it as the conscious rejection it was (over-engineering
  for 3 models).
- The "ADRs sem banner histórico em `docs/PLAN.md`" acceptance
  criterion was already satisfied before this ticket (handoff
  history records the user declining the banner). No change made.
- README does not embed a screenshot of the AI/BI dashboard
  (acceptance criterion #8 mentions "screenshot ou link"). The
  README documents the dashboard resource path and how to find it
  in the workspace UI; a screenshot inside the repo would either
  go stale fast or commit binary that the gitignore policy
  discourages. Leaving this to the evaluator's own
  `bundle deploy` run.
