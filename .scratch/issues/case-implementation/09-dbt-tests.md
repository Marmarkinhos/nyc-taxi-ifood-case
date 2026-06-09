---
status: ready-for-agent
created: 2026-06-08
tags: [dbt, tests, data-quality]
blocked-by: [08-dbt-gold-model.md]
---

# 09 — dbt tests (4 inventariados)

## What to build

Adicionar os 4 testes inventariados em ADR-0007 item 3 + CONTEXT.md
§dbt tests. Vivem em `dbt/models/sources.yml` (pros source tests)
+ `dbt/models/gold/schema.yml` (pros Gold tests).

**4 testes:**

1. **`not_null` em 5 colunas exigidas do source Silver**
   (`yellow_taxi_trips`):
   - `vendor_id`, `passenger_count`, `total_amount`,
     `tpep_pickup_datetime`, `tpep_dropoff_datetime`
   - Hard-fail equivalente à expectation #7-bronze, mas pós-Silver.

2. **`accepted_values: [1, 2, 6, 7]` em `vendor_id` do source
   Silver:**
   - **Redundância intencional** com expectation #1 (warn).
   - dbt vira o ponto onde valor desconhecido bloqueia propagação
     pra Gold (hard-fail por default).

3. **`relationships` Gold → `dim_locations`** em
   `pickup_location_id` e `dropoff_location_id`:
   - Field: `location_id`
   - Pega LocationID novo sem entrada no seed (TLC adicionou zonas
     em 2023/2024).

4. **`not_null` em colunas Gold derivadas:**
   - `pickup_year_month` (materializada Silver, deve passar)
   - `pickup_borough`, `dropoff_borough` (enriquecimento; falha
     se JOIN com `dim_locations` deixar nulo).

**Sem custom tests além desses 4** — minimalismo intencional
(ADR-0007). Tests adicionais (ex.: `unique` em algum
business key) ficam pra evolução pós-case.

## Acceptance criteria

- [ ] `dbt test` roda os 4 tests sem erro contra dataset esperado
- [ ] `dbt test --select source:silver` roda os 2 source tests
- [ ] `dbt test --select yellow_taxi_trips_consumption` roda os 2
      Gold tests
- [ ] Test `relationships` falha de propósito se um
      LocationID novo (não no seed) for adicionado manualmente na
      Silver (verificação manual)
- [ ] Test `accepted_values` falha de propósito se
      `vendor_id=99` for INSERTado na Silver
- [ ] Severidade default (`error`) em todos — sem warn (warn é
      papel das expectations DLT)
- [ ] schema.yml respeita conventions dbt (`columns:` block, etc.)

## Blocked by

- `08-dbt-gold-model.md` (Gold tests precisam do modelo existindo)
