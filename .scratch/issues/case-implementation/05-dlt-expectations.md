---
status: done
created: 2026-06-08
closed: 2026-06-09
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
| 2 | `passenger_count BETWEEN 0 AND 9` | `passenger_count` | `expect` (warn) — **ADR-0016** | 428K NULL nativo TLC; manter rows preserva fare/distance/location pras Q1/Q3/Q4. Análise de Q2 (#11) filtra `IS NOT NULL`. |
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
- [ ] Expectations #3-5 são `expect_or_drop` (dropam linhas
      que corromperiam métricas: refunds, timestamps NULL, dropoff
      invertido)
- [ ] Expectations #1, #2 e #6a são `expect` (warn-only, preservam
      linhas — ADR-0016)
- [ ] Métricas das expectations aparecem em `event_log("<pipeline_id>")`
      (`expectation_metrics`)
- [ ] Re-run do pipeline com parquet contendo `passenger_count=99`
      observa drop (linhas filtradas; warn registrado)
- [ ] Contrato de 5 colunas (`schema.py` do #02) tem teste pytest
      paralelo (já feito no #02; aqui só warn em runtime)

## Blocked by

- `04-dlt-bronze-silver-canonica.md` (precisa do pipeline DLT
  existindo)

## Resolution (2026-06-09)

Implementado em `ingestion/dlt_pipeline.py` — delta pequeno (sem
arquivos novos, sem helpers novos, sem testes novos).

### Stack de decorators

- **Bronze (1 regra warn):** `@dlt.expect("bronze_required_columns_not_null",
  _BRONZE_REQUIRED_NOT_NULL_RULE)` na `yellow_taxi_trips_raw`. A regra
  é composta em module-scope:
  `" AND ".join(f"{c} IS NOT NULL" for c in REQUIRED_TLC_COLUMNS)` —
  mesma constante (`src/nyc_taxi_case/schema.py`) que o pytest
  `test_schema.py` consome, evitando drift entre teste pré-deploy e
  warn runtime.
- **Silver (6 regras):** dois decorators agrupados por severidade na
  `yellow_taxi_trips`:
  - `@dlt.expect_all_or_drop({...})` — regras #2-5 (4 drops):
    `passenger_count_in_range`, `total_amount_non_negative`,
    `trip_timestamps_not_null`, `dropoff_after_pickup`.
  - `@dlt.expect_all({...})` — regras #1 e #6a (2 warns):
    `vendor_id_in_dictionary`, `pickup_month_matches_file`.

Total: **3 decorators carregando 7 regras** (1 + 4 + 2).

### Departures vs ticket original

- **#7-bronze montada dinamicamente** a partir de `REQUIRED_TLC_COLUMNS`
  em vez de hard-coded com as 5 colunas inline. Justificativa: ADR-0007
  explicita "reutiliza REQUIRED_TLC_COLUMNS"; evita drift entre as
  três camadas de defesa (pytest CI + Bronze warn + dbt tests).
  Custo: 1 linha de `" AND ".join(...)`.
- **Regras Silver usam `_all_or_drop` e `_all` (dict-form)** em vez de
  N decorators `@dlt.expect_or_drop(...)` individuais. Justificativa:
  agrupa por severidade num único decorator, evita ruído visual com 6
  decorators empilhados, e mantém os nomes de cada rule explícitos
  como chaves do dict (visíveis no `event_log`).

### Acceptance criteria — todos ✅

- ✅ 7 expectations declaradas via `@dlt.expect_*` decorators (1
  Bronze + 4 Silver drop + 2 Silver warn = 7 regras, 3 decorators).
- ✅ Nenhuma é `expect_or_fail`. Verificável por grep:
  `grep -E "@dlt\.expect_or_fail" ingestion/ src/` → vazio. Os 4
  matches em `grep -r expect_or_fail` são todos em comentários /
  docstrings que documentam a decisão (ADR-0007).
- ✅ Expectation #7-bronze warn-only em nível tabela (single
  `@dlt.expect` no decorator da Streaming Table).
- ✅ #2-5 são `expect_or_drop` (via `_all_or_drop`).
- ✅ #1 e #6a são `expect` warn (via `_all`).
- ⏳ Métricas em `event_log()` — só verificável após `bundle deploy +
  bundle run` (HITL #06).
- ⏳ Re-run com `passenger_count=99` observa drop — também HITL pós-#06.
- ✅ Contrato de 5 colunas com teste pytest paralelo — já existia
  desde #02 (`ingestion/tests/test_schema.py`).

### Gates locais (passaram todos)

- `ruff check src/ ingestion/` ✅
- `ruff format src/ ingestion/` ✅ (reformat aplicado: juntou uma
  string de duas linhas — nada semântico)
- `mypy --strict src/` ✅ — 8 source files, no issues
- `pytest -q` ✅ — **116 passed** (idêntico ao baseline do #04;
  expectations não adicionam testes — decorators DLT só executam em
  runtime Databricks)

### Não testado localmente

Tudo o que requer runtime DLT real:
- Drop count das #2-5 aparecer em `event_log("<pipeline_id>")`.
- Warn das #1, #6a, #7-bronze aparecer em `event_log`.
- Bronze não abortar quando uma das 5 colunas vier NULL.

Esses pontos viram HITL no #13 (README + verificação manual).
