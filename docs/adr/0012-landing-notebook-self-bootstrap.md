# 0012: Landing notebook é self-bootstrap (schema + Volume idempotentes; raise em FAILED)

## Status
Accepted

## Context

Primeiro `bundle run job_ingestion` end-to-end (2026-06-09, depois de
#06 deployar com sucesso) expôs três bugs distintos e independentes,
todos rooted no mesmo princípio violado: **o landing notebook
assumia setup externo que ninguém fazia**.

1. **Wheel path mismatch** — `dependencies` no `job_ingestion.yml` /
   `dlt_pipeline.yml` apontavam pra `${workspace.file_path}/dist/`,
   mas `databricks bundle deploy` sobe `type: whl` artifacts pra
   `${workspace.artifact_path}/.internal/`. Resultado:
   `ERROR_NO_SUCH_FILE_OR_DIRECTORY` na install da env serverless.
   Sintoma muda de `ModuleNotFoundError` (pre-fix) pra erro de
   install, dando a impressão de progresso quando na verdade só
   tinha mudado a etapa que falha.
2. **`sys.exit` em notebook task** — `landing.py` rodava `sys.exit(0)`
   no SUCCESS, mas notebook tasks tratam **qualquer** `SystemExit`
   (mesmo `0`) como workload failure. Notebooks esperam ou
   terminação natural via cell completion, ou
   `dbutils.notebook.exit()`. Resultado: task verde virava task
   vermelha com `SystemExit: 0` no error trace, audit row no SUCCESS
   estado.
3. **Landing schema/Volume não existem** — PLAN.md §setup mencionava
   "criar Volume manualmente" como passo HITL, mas nenhum ticket
   programaticamente garantia existência de
   `${catalog}.${bronze_schema}` ou do Volume
   `${landing_volume_name}`. Resultado: probe HEAD respondia 200 OK,
   download abria, mas `os.makedirs("/Volumes/.../year=YYYY/...")`
   falhava com `FileNotFoundError` (Volume inexistente), o
   `except Exception` do `_process_month` swallowed em `sys.stderr`
   (que não chega na jobs API), e a audit row reportava
   `status=FAILED` com mensagem genérica `outbound TLC bloqueado` —
   diagnóstico errado pra causa errada.

Os três bugs juntos fizeram parecer que o problema era rede de saída
do Free Edition (ADR-0002's failure mode), quando na verdade o
CloudFront da TLC estava acessível e o setup do workspace é que
estava incompleto.

Causa-raiz comum: **o notebook delegava implicitamente pra "alguém
mais" (operador, ticket separado, bundle config) a garantia de
pré-condições UC e o protocolo de exit-status do runtime**. Esse
acoplamento não é detectável em pytest (Spark-free) nem em
`bundle validate` (offline), então só explodiu no primeiro
`bundle run` num workspace fresh.

## Decision

O landing notebook (`ingestion/landing.py`) **garante todas as suas
pré-condições UC e usa o exit protocol correto do notebook task**.
Especificamente:

1. **Idempotência de schema + Volume.** `main()` chama
   `_ensure_landing_volume(session, params)` logo após
   `_ensure_audit_table`, executando:
   ```sql
   CREATE SCHEMA IF NOT EXISTS ${catalog}.${bronze_schema};
   CREATE VOLUME IF NOT EXISTS ${catalog}.${bronze_schema}.${landing_volume_name};
   ```
   Path decomposto via `nyc_taxi_case.landing_paths.parse_volume_base`
   (puro, testado), evitando que o widget contract precise expor
   schema/volume separadamente (continua sendo só `landing_volume_path`).
2. **Exit protocol.** Notebook entry-point é `main()` (não
   `sys.exit(main())`). SUCCESS / PARTIAL caem fora do `if __name__`
   naturalmente. FAILED levanta `RuntimeError(error_message)` — a
   única forma documentada de sinalizar erro num notebook task com
   traceback útil.
3. **DAB artifact paths.** `dependencies` em
   `resources/job_ingestion.yml` (`environments.spec.dependencies`)
   e `resources/dlt_pipeline.yml` (`environment.dependencies`)
   referenciam `${workspace.artifact_path}/.internal/<wheel>.whl`,
   NÃO `${workspace.file_path}/dist/`. O comentário em
   `databricks.yml` explica a distinção:
   - `${workspace.file_path}` recebe arquivos via `sync.include`
     (source tree).
   - `${workspace.artifact_path}/.internal/` recebe `type: whl` /
     `type: jar` artifacts.

Alternativas rejeitadas:

- **Documentar setup manual no README** — viola o princípio "o
  notebook é a fonte da verdade pra suas dependências"; primeiro
  avaliador num workspace novo cai no mesmo loop.
- **Mover schema/Volume bootstrap pra `databricks.yml`
  `resources.schemas` / `resources.volumes`** — DAB suporta isso,
  mas acopla bootstrap ao deploy (refresh do schema/Volume só roda
  com `bundle deploy`, não com `bundle run`). Pra um workspace que
  já tem o bundle deployado mas perdeu o Volume (drop manual,
  workspace fresh com state importado, etc), só `bundle run`
  reconstrói. Manter no notebook é mais robusto.
- **Catchear `FileNotFoundError` no `_download_to_volume` e criar
  Volume on-demand** — espalha o bootstrap pelo IO path; mais
  difícil de raciocinar e de testar.
- **`dbutils.notebook.exit()` no SUCCESS** — funciona mas adiciona
  acoplamento ao runtime Databricks no entry-point. Terminação
  natural via `main()` mantém o módulo importável em pytest.

## Consequences

**Positivas:**
- `bundle run job_ingestion` é one-shot num workspace fresh: o
  notebook cria seu schema, seu Volume, sua audit table, baixa os
  parquets, grava a audit row. Zero pré-requisitos UC fora do
  catalog (que é Free Edition default).
- Erros do landing aparecem com traceback útil no Databricks UI
  (RuntimeError com `error_message`), não como `SystemExit` opaco.
- Pattern reutilizável: qualquer notebook futuro do projeto que
  precise de UC objects segue o mesmo formato (`_ensure_*` helpers
  idempotentes + raise em failure).

**Negativas:**
- `parse_volume_base` adiciona uma forma do path Volume ser inválido
  (poucos segmentos) — coberto por 9 tests novos, mas é mais um
  contrato pra manter.
- Dois `CREATE ... IF NOT EXISTS` extras por run (custo desprezível
  vs probe HTTP de 5s + download de ~50 MB/mês, mas é IO Spark adicional).
- Audit row's `error_message` continua genérico ("all months failed
  probe/download") quando `_download_to_volume` falha após probe OK
  — fix #4 só destravou o caso `Volume inexistente`; outros download
  failures (timeout no body, disk full, etc) continuam sem
  observabilidade rica. Issue separada se virar prioridade.

**Neutras:**
- `databricks.yml` `artifacts` block não muda; só os
  `dependencies` consumers.
- ADR-0002 (probe HEAD defensivo) continua válido — o probe
  funcionou perfeitamente neste workspace; o bug era downstream do
  probe. ADR-0002's failure-mode (outbound bloqueado) continua sendo
  um cenário real pra outros workspaces.
- ADR-0008 (audit schema) inalterado.

## Cross-references

- Fix #2, #3, #4, #5 documentados em detalhe em
  `.scratch/issues/case-implementation/06-job-ingestion-dab.md`
  (Resolution section).
- ADR-0002 — probe HEAD que isolou que a falha NÃO era de rede.
- ADR-0008 — schema da `landing_audit` que essa decisão preserva.
