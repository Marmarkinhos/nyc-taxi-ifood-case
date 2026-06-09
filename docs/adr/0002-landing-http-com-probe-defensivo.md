# 0002: Landing notebook usa HTTP direto, com probe HEAD como defesa

## Status
Accepted

## Context
PLAN.md §7 levantou risco de outbound restrita no Databricks Free
Edition bloquear o CDN da TLC (`d37ci6vzurychx.cloudfront.net`).
Risco testado empiricamente em 2026-06-08: HEAD respondeu
`STATUS=200` em 0.10s com `Content-Length=47.673.370` e
`Server: AmazonS3`. CloudFront está acessível a partir do compute
serverless do workspace alvo. Plano A (download HTTP) é viável e
deve ser o caminho principal.

## Decision
Landing notebook usa **`requests.get` direto** pra baixar parquets
TLC e escrever no Volume UC. Antes do download de cada arquivo,
executa **probe HEAD com timeout 5s** que:
- Em sucesso (2xx): segue pro download.
- Em falha (timeout, 4xx, 5xx, ConnectionError): registra
  `probe_result` no audit e tenta o próximo arquivo. Se nenhum
  arquivo passar no probe, status final = `FAILED` com mensagem
  "outbound TLC bloqueado — vide README seção `VOLUME_PREEXISTING`".

README documenta:
1. **Caminho default**: `databricks bundle run nyc_taxi_landing_job`
   baixa via HTTP automaticamente.
2. **Fallback `VOLUME_PREEXISTING`**: se o probe falhar (mudança
   futura da Databricks ou TLC), passos manuais pra subir parquets
   via `databricks fs cp` ou UI. Pipeline DLT downstream não muda.

Schema do `landing_audit` ganha `probe_results ARRAY<STRUCT<month,
probe_status, http_code>>` pra auditar capacidade real do workspace
ao longo do tempo, mais coluna `source_mode STRING`
(`HTTP` | `VOLUME_PREEXISTING`).

Alternativas consideradas e rejeitadas:
- **HTTP-only sem probe**: barato, mas se Databricks fechar
  outbound futuramente, falha será timeout 60s × 5 arquivos = 5min
  ruidosos antes de qualquer erro útil.
- **VOLUME_PREEXISTING default + HTTP bonus**: rejeitado pelo dado
  empírico — HTTP funciona, exigir upload manual sem necessidade
  é pior UX pro avaliador.
- **Dois jobs separados (`landing_http` + `landing_volume_only`)**:
  duplicação sem benefício; um notebook com fallback resolve.

Detalhe ignorado intencionalmente: TLC publica
`Content-Type: application/x-www-form-urlencoded` (header errado).
Não afeta — escrita binária direta no Volume. Não confiar em
`content-type` pra validar formato.

## Consequences
**Positivas:** runbook do README é uma linha (`bundle run ...`);
audit registra capacidade real do workspace (útil se Databricks
restringir outbound depois).
**Negativas:** ~10 LOC a mais no notebook (probe + fallback control
flow); 1 coluna nova no audit (`probe_results ARRAY<STRUCT>`) + 1
(`source_mode`).
**Neutras:** Auto Loader e DLT downstream não mudam.
