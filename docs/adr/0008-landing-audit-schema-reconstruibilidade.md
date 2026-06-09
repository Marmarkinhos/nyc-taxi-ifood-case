# 0008: `landing_audit` schema com `pipeline_update_id`, contagens desambiguadas e link UI

## Status
Accepted

## Context
PLAN.md §3 (decisão #9) propôs `monitoring.landing_audit` como tabela
de auditoria do gap pre-Bronze (download HTTP → Volume). ADR-0002
adicionou `source_mode` e `probe_results`. Schema resultante (13
colunas) ainda tem **cinco problemas operacionais** que comprometem
a reconstruibilidade de uma execução:

1. **Sem `pipeline_update_id`** — audit não liga ao DLT `event_log`.
   Avaliador olhando uma linha do audit não consegue responder "qual
   update DLT processou esses arquivos?".
2. **Sem `months_skipped`** — `requested − downloaded − failed` não
   cobre o caso "arquivo já estava no Volume". Run idempotente
   (segundo rerun) gera audit ambígua.
3. **`total_bytes` ambíguo** — mistura "bytes baixados neste run" com
   "bytes totais no Volume" (incluindo pré-existentes). Avaliador vê
   audit dizendo "2 arquivos, 95 MB" mas DLT processa 5 arquivos /
   240 MB — números não batem.
4. **Sem `job_run_id`** separado de `run_id` (task-level vs job-level
   no Databricks).
5. **Sem `job_url`** — link clicável pro UI mata 80% do tempo de
   debug; sem ele, avaliador navega manualmente.

## Decision
Schema final do `${prefix}monitoring.landing_audit`:

```
run_id                  STRING       -- task run id (databricks)
job_run_id              STRING       -- job-level run id (databricks)
job_url                 STRING       -- URL clicável pro UI
pipeline_update_id      STRING       -- preenchido pela SQL task pós-DLT
job_start_ts            TIMESTAMP
job_end_ts              TIMESTAMP
source_mode             STRING       -- HTTP | VOLUME_PREEXISTING
probe_results           ARRAY<STRUCT<
                          month: STRING,
                          probe_status: STRING,  -- OK|TIMEOUT|HTTP_ERR|CONN_ERR
                          http_code: INT
                        >>
start_year_month        STRING
end_year_month          STRING
months_requested        ARRAY<STRING>
months_downloaded       ARRAY<STRING>
months_skipped          ARRAY<STRING>   -- já no Volume (idempotência)
months_failed           ARRAY<STRING>
bytes_downloaded        BIGINT          -- só HTTP deste run
bytes_total_in_volume   BIGINT          -- soma de tudo no path final
status                  STRING          -- SUCCESS | PARTIAL | FAILED
error_message           STRING
```

**Mecânica de preenchimento de `pipeline_update_id`:**
- Landing notebook escreve linha com `pipeline_update_id = NULL`.
- SQL task pós-DLT (`notebooks/monitoring/gold_pipeline_observability.sql`,
  já no PLAN.md §6 item 8) executa
  `UPDATE monitoring.landing_audit SET pipeline_update_id =
  (SELECT latest update_id FROM event_log) WHERE run_id =
  '${job.run_id}'`. ~3 linhas SQL.

Alternativas rejeitadas:
- **Tabela separada `landing_to_dlt_link`** ou **view de join
  `audit_with_dlt`**: ambos custam mais que `UPDATE` direto na audit.
- **Manter schema 13-col original**: aceita 5 problemas de
  reconstruibilidade em troca de menos LOC; troca ruim porque audit é
  o ponto único de entrada pra debug.

## Consequences
**Positivas:** audit table é ponto único de entrada pra reconstruir
qualquer execução; `pipeline_update_id` liga pre-Bronze → DLT;
`months_skipped` desambigua idempotência; `bytes_downloaded` vs
`bytes_total_in_volume` resolve discrepância audit↔DLT; `job_url` mata
tempo de debug. Sinal forte de "pensei em reconstruibilidade" pro
avaliador.
**Negativas:** schema com 17 colunas (vs 13 original); cada coluna
nova é compromisso (mudança de schema futura exige migration);
acoplamento `UPDATE` cross-task entre landing notebook e SQL pós-DLT.
**Neutras:** Auto Loader e DLT downstream não veem audit; isolamento
preservado.
