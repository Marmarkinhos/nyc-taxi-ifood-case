---
status: ready-for-agent
created: 2026-06-08
tags: [dlt, expectations, data-quality]
blocked-by: [04-dlt-bronze-silver-canonica.md]
---

# 05 — DLT expectations (6 Silver + 1 Bronze warn)

## What to build

Adicionar as 7 expectations ao pipeline DLT do ticket #4. Todas
seguem ADR-0007: **nenhuma é `expect_or_fail`**; contrato de
schema é protegido por pytest CI + warn na Bronze.

**Bronze — 1 expectation warn-only:**

| # | Regra | Coluna(s) | Severidade |
|---|---|---|---|
| 7-bronze | Contrato: 5 colunas exigidas presentes (`VendorID`, `tpep_pickup_datetime`, `tpep_dropoff_datetime`, `passenger_count`, `total_amount`) | nível tabela | `expect` (warn) |

**Silver — 6 expectations:**

| # | Regra | Coluna(s) | Severidade | Razão |
|---|---|---|---|---|
| 1 | `vendor_id IN (1, 2, 6, 7)` | `vendor_id` | `expect` (warn) | Dicionário TLC; observa drift. Redundante intencional com dbt test (ticket #9). |
| 2 | `passenger_count BETWEEN 0 AND 9` | `passenger_count` | `expect_or_drop` | Pergunta 2 = média; lixo enviesa. |
| 3 | `total_amount >= 0` | `total_amount` | `expect_or_drop` | Pergunta 1 = média; refunds enviesam. |
| 4 | `tpep_pickup_datetime IS NOT NULL AND tpep_dropoff_datetime IS NOT NULL` | timestamps | `expect_or_drop` | Sem pickup → sem partição válida. |
| 5 | `tpep_dropoff_datetime >= tpep_pickup_datetime` | timestamps | `expect_or_drop` | Corrupção; dropa. |
| 6a | `pickup_year_month = file_year_month` | derivada | `expect` (warn) | Detecta pickups fora do mês do arquivo (TLC tem ruído real: 2001/2087). Silver preserva ruído, Gold filtra pela janela. |

**Métricas:** as 7 expectations materializam em `event_log()` →
consumidas pela view `gold_pipeline_observability` (criada no
ticket #13).

## Acceptance criteria

- [ ] 7 expectations declaradas via `@dlt.expect_*` decorators
- [ ] Nenhuma é `expect_or_fail` (verificável por grep no código)
- [ ] Expectation #7-bronze é warn-only e aplica em nível tabela
- [ ] Expectations #2-5 são `expect_or_drop` (dropam linhas
      inválidas)
- [ ] Expectations #1 e #6a são `expect` (warn-only, preservam
      linhas)
- [ ] Métricas das expectations aparecem em `event_log("<pipeline_id>")`
      (`expectation_metrics`)
- [ ] Re-run do pipeline com parquet contendo `passenger_count=99`
      observa drop (linhas filtradas; warn registrado)
- [ ] Contrato de 5 colunas (`schema.py` do #02) tem teste pytest
      paralelo (já feito no #02; aqui só warn em runtime)

## Blocked by

- `04-dlt-bronze-silver-canonica.md` (precisa do pipeline DLT
  existindo)
