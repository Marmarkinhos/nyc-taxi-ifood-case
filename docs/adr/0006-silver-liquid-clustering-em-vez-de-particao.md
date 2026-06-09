# 0006: Silver usa Liquid Clustering em vez de partição estática

## Status
Accepted

## Context
PLAN.md §3 (decisão #6) propôs `PARTITIONED BY pickup_year_month` na
Silver, justificado por "Pruning ótimo nas 2 perguntas. ~17M
linhas/partição = sweet spot Delta. Sobrevive ao full load (~200
partições)". Três problemas com essa justificativa no escopo deste
case:

1. **Escopo case (Jan–Maio 2023) gera 5 partições, ~1.2 GB total
   pós-compaction (ADR-0005).** Databricks recomenda explicitamente
   não particionar tabelas menores que ~1 TB — three orders of
   magnitude abaixo do threshold. Particionamento em tabela pequena
   sofre de small-files problem e overhead de metadata.

2. **"Sobrevive ao full load (~200 partições)"** é argumento de
   produção projetado num case que não vai rodar full load. Avaliador
   roda Jan–Maio 2023, vê 5 partições, e a pergunta "por que
   particionar 1.2 GB?" fica sem resposta defensável.

3. **Liquid Clustering é a feature recomendada pela Databricks** pra
   tabelas onde o padrão de acesso pode evoluir. Particionamento
   estático é o legado; Liquid Clustering é o sucessor.

## Decision
Silver usa `CLUSTER BY (pickup_year_month)` (Liquid Clustering) em
vez de `PARTITIONED BY pickup_year_month`. Mudança operacional:
trocar `partition_cols=["pickup_year_month"]` por
`cluster_by=["pickup_year_month"]` no `@dlt.table` da Silver.

Benefícios sobre partição estática:
- **Pruning equivalente** pra Pergunta 1 (`GROUP BY pickup_year_month`).
- **Sem small-files problem** no escopo case (~1.2 GB).
- **Evolutivo**: permite adicionar `tpep_pickup_datetime` ou
  `vendor_id` como clustering key sem rewrite completo — particionamento
  estático forçaria reescrita total.
- **Menos overhead de listagem** na SQL Warehouse Free Edition (menos
  arquivos pequenos).

Validação pré-implementação: confirmar suporte DLT pra Liquid
Clustering (disponível desde meados de 2024 — checar no probe inicial
do projeto). Fallback explícito: se DLT em Free Edition não suportar,
volta a `partition_cols=["pickup_year_month"]` e atualiza este ADR
para `Superseded`.

Alternativas rejeitadas:
- **`PARTITIONED BY pickup_year_month`** (decisão original do plano):
  argumento "sweet spot Delta" não se sustenta em ~1.2 GB; argumento
  "sobrevive ao full load" projeta cenário fora do escopo.
- **Sem partição nem clustering**: Delta resolve com data skipping
  nativo (column stats no footer); ainda funciona, mas perde sinal
  de "pensei em performance".
- **Z-ORDER por `pickup_year_month`**: legado do legado; Liquid
  Clustering é o sucessor explícito.

## Consequences
**Positivas:** alinha com recomendação atual Databricks; remove
small-files problem; evolutivo (pode adicionar clustering keys depois
sem rewrite); reduz overhead de I/O na SQL Warehouse Free Edition.
Bullet "Liquid Clustering como futuro" da seção 8 do PLAN.md sai
porque virou presente.
**Negativas:** acoplamento ao suporte DLT pra Liquid Clustering (se
runtime não suportar, fallback exige update do ADR); ~1 LOC de
diferença no código (custo desprezível).
**Neutras:** comportamento das 2 consultas do case idêntico (pruning
em `pickup_year_month`).
