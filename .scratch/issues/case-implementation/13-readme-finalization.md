---
status: ready-for-human
created: 2026-06-08
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
