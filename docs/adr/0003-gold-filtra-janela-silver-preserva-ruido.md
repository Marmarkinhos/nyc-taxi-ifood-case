# 0003: Gold view filtra pickup_year_month pela janela declarada do run; Silver preserva ruído

## Status
Accepted

## Context
TLC entrega arquivos com ruído temporal real: `yellow_tripdata_2023-01.parquet`
contém linhas com `tpep_pickup_datetime` em 2001, 2087, etc. PLAN.md §3
(decisão #6 + expectation #6) propunha derivar `pickup_year_month` do
timestamp e usar expectation `expect` (warn-only) contra a janela de
ingestão. Consequência não endereçada: a Silver materializa partições
espúrias (`2087-09`, etc.) que vazam pra Pergunta 1 do case
(`AVG(total_amount) GROUP BY pickup_year_month`) gerando resultado
com linhas absurdas no relatório final.

## Decision
**Silver preserva o ruído** (rastreabilidade + EDA). Expectation #6a
valida `pickup_year_month = file_year_month` com severidade `expect`
(observa, não dropa). Adiciona coluna `file_year_month STRING` derivada
de `_metadata.file_path` (parse do nome do arquivo TLC) — ver ADR-0004.

**Gold (modelo dbt) filtra** `WHERE pickup_year_month BETWEEN
<min(months_requested)> AND <max(months_requested)>`. A janela vem do
último run de ingestão registrado em `landing_audit` (LATEST por
`job_end_ts`). Resultado: Gold e análises dbt só veem pickups dentro
da janela solicitada; lixo temporal não aparece no resultado oficial
mas continua auditável via Silver.

Comportamento em "primeiro run" (audit vazia): Gold dbt falha com
mensagem explícita via `{{ exceptions.raise_compiler_error(...) }}`
no Jinja ("nenhum run de ingestão registrado em landing_audit; rode
`bundle run job_ingestion` primeiro").

Alternativas rejeitadas:
- **Dropar lixo na Silver (`expect_or_drop`)**: perde sinal pra EDA;
  exige consulta no `event_log` pra saber "quantas linhas eram lixo".
- **Filtrar em cada `.sql` de resposta**: acopla filtro de validade
  à pergunta; repetido em N lugares; quebra "Gold é a camada de
  consumo final".
- **Janela como variável dbt (`--vars '{start_ym: ..., end_ym: ...}'`)
  passada no `bundle run job_dbt`**: rejeitado. Quebra a separação
  dos 2 jobs (avaliador teria que descobrir e passar a janela duas
  vezes — uma no `job_ingestion`, outra no `job_dbt`). Lendo do
  `landing_audit`, dbt herda automaticamente o que foi ingerido,
  mantendo o contrato `sources.yml` como única ponte entre os 2
  jobs (ADR-0011).

## Consequences
**Positivas:** distinção Silver/Gold ganha segundo propósito além de
projeção de colunas (projeção de validade temporal); Pergunta 1
entrega resultado limpo sem mascarar ruído da fonte; lixo continua
auditável (Silver intacta, `event_log` registra warnings de #6a).
**Negativas:** Gold dbt fica dependente de `landing_audit` (acoplamento
cross-schema). `sources.yml` declara duas sources — `silver.yellow_taxi_trips`
E `monitoring.landing_audit` — tornando o acoplamento explícito no
contrato. Requer decisão de comportamento em "primeiro run" (definido
acima: falha explícita via Jinja).
**Neutras:** comportamento do DLT não muda; só dono e mecânica de
materialização da Gold (view DLT → modelo dbt). Lógica de filtro
idêntica.
