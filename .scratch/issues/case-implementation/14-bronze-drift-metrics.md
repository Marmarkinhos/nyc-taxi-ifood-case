---
status: wontfix
created: 2026-06-09
closed: 2026-06-09
tags: [bronze, drift, observability, expectations, alerting, wontfix]
blocked-by: [06-job-ingestion-dab.md]
---

# 14 — Bronze drift metrics + job-level alerting

## Background

Issue derivada de Fix #7 / ADR-0014. O fix da Fix #7 cobriu o tipo
mais provável de drift TLC (case rename via `cloudFiles.schemaHints`)
e adicionou expectation warn-only `bronze_no_rescued_data` pra
detectar drift de tipo / cast failure. Esse ticket fecha os **gaps
remanescentes** de observabilidade de drift:

1. **Drift estrutural** — TLC adiciona uma 20ª coluna ou remove uma
   das 14 não-mandatórias. ADR-0014 reconhece como gap; a expectation
   atual não detecta.
2. **% rescued no audit table** — hoje só visível via SQL ad-hoc. Pra
   ficar acionável, precisa virar coluna na `landing_audit` populada
   por SQL task pós-DLT.
3. **Job-level alerting** — `event_log` da DLT não dispara nada
   automaticamente. Precisa de critério de sucesso/falha do JOB
   (não da Bronze) que olhe a métrica e force job vermelho se
   ultrapassar limiar.
4. **Dashboard de drift** — visualização da % rescued e % drop nas
   expectations ao longo do tempo, pra detectar tendência antes
   de virar incidente.

## Acceptance criteria

### Cobertura de drift estrutural

- [ ] **SQL task pós-DLT** ou **expectation extra** que compara o
      schema atual da Bronze com a lista canônica de 19 colunas TLC
      (lê de `BRONZE_SCHEMA_HINT_TYPES` via algum mecanismo — provável:
      a SQL task lê uma view materializada do helper, ou compara
      `information_schema.columns` com uma constante exportada).
- [ ] Test pytest: se `BRONZE_SCHEMA_HINT_TYPES` mudar (adição /
      remoção), o teste avisa o desenvolvedor (já existe parity test
      contra `TLC_RENAME_MAP` — esse cobre o caso de PR consciente;
      faltam testes de "ADR de schema change foi atualizado").

### % rescued na audit table

- [ ] Adicionar coluna `bronze_rescued_pct DOUBLE` em `landing_audit`
      (ADR-0008 schema update + migration plan).
- [ ] SQL task pós-DLT no job_ingestion que atualiza a coluna pra
      última run (`UPDATE landing_audit SET bronze_rescued_pct = ...
      WHERE run_id = ...`).
- [ ] Granularidade: % por mês ou agregada? Decidir no ticket —
      provável: agregada por run + per-file breakdown via view sql.

### Job-level alerting

- [ ] Task `assert_bronze_drift_within_threshold` que falha (raise)
      se `bronze_rescued_pct > <limiar>` (ex: 1.0). Limiar configurável
      via DAB variable.
- [ ] Job_ingestion DAG: dependency da task no end do critical path
      (depois de `update_landing_audit`).
- [ ] Webhook ou notification config no DAB pra emails/Slack quando
      job falha por drift (separado de outras falhas de runtime).

### Dashboard

- [ ] Gráfico time-series em ticket #12 (notebook-dashboard) ou em
      uma view dedicada:
  - `bronze_rescued_pct` por run
  - % drop per expectation Silver por run
  - count rows per file_month per run

## Design notes

- **Gap consciente do ADR-0014**: este ticket é o follow-up registrado
  nele. Ler ADR-0014 §"Decision item 5" e §"Negativas" antes de
  começar.
- **Considerar event_log query como fonte**: `event_log(TABLE(<bronze>))`
  expõe `details:flow_progress.data_quality.expectations` com
  failed_records por expectation por update. Isso pode ser a fonte
  pro audit e pro dashboard sem precisar de SQL ad-hoc por coluna.
- **Limiar de alerting**: começar conservador (% > 0.1) pra dev,
  relaxar pra produção. O case statement do projeto é dev/MVP, então
  qualquer drift é interessante.
- **`assert_*` pattern**: tem precedente no DAB de outros projetos
  (`assert_freshness`, `assert_data_quality`); seguir convenção.

## Out of scope

- Mudanças na lógica do helper `tlc_schema.py` — esse ticket
  consome o helper, não o reformula.
- Alerting cross-job (job_dbt) — escopo deste ticket é só
  `job_ingestion`. Se virar prioridade, abrir #15.

## Blocked by

- `06-job-ingestion-dab.md` precisa estar verde end-to-end (Fix #7
  incluído) pra essa observabilidade ter sinal estável pra medir.

## Resolution: wontfix (over-engineering pro escopo do case)

**Decisão do user (2026-06-09):** não implementar.

Racional:

- O case do iFood pede pipeline funcional + 2 perguntas analíticas
  + EDA. Não pede observabilidade de drift estrutural nem alerting
  cross-job.
- O fix da Fix #7 (ADR-0014) já cobre o vetor de drift mais
  provável da fonte TLC (case rename via `cloudFiles.schemaHints`),
  e a expectation warn-only `bronze_no_rescued_data` já dá um
  primeiro sinal de drift residual visível no event_log da DLT.
- Os gaps remanescentes documentados acima (drift estrutural
  schema diff, % rescued na audit table, alerting job-level) são
  reais mas ortogonais ao critério "entregue" do case. Implementar
  agora seria gold-plating.
- Os gaps continuam **registrados aqui** e em ADR-0014 §"Gaps
  reconhecidos" — se o pipeline virar produção, este ticket pode
  ser reaberto como ponto de partida sem retrabalho de análise.
