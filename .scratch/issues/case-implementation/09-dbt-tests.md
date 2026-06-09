---
status: done
created: 2026-06-08
resolved: 2026-06-09
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

## Resolution (2026-06-09)

Implementados os 4 testes inventariados como YAML data tests em
`dbt/models/sources.yml` (Silver source) e `dbt/models/gold/schema.yml`
(novo arquivo, Gold model). Todos `error` severity por default.

### Mapeamento conceito → nodes dbt

Os "4 testes" do inventário se expandem em **10 test nodes** porque
dbt cria um node por (coluna × generic test). O selector contract do
acceptance criteria continua válido:

| Inventário | Localização | Nodes dbt |
|---|---|---|
| 1. `not_null` em 5 cols Silver | `sources.yml` | 4 nodes (`vendor_id`, `total_amount`, `tpep_pickup_datetime`, `tpep_dropoff_datetime`) — ver Desvio abaixo |
| 2. `accepted_values [1,2,6,7]` vendor_id | `sources.yml` | 1 node |
| 3. `relationships` Gold → seed | `gold/schema.yml` | 2 nodes (`pickup_location_id`, `dropoff_location_id`) |
| 4. `not_null` em 3 cols Gold | `gold/schema.yml` | 3 nodes (`pickup_year_month`, `pickup_borough`, `dropoff_borough`) |

`dbt test --select source:silver` → 5 nodes PASS.
`dbt test --select yellow_taxi_trips_consumption` → 5 nodes PASS.
`dbt test` (full) → 10/10 PASS em 11.26s contra dataset real (~16M
rows Silver, Gold scope ~2.5M na window ativa do `landing_audit`).

### Desvio do spec original: `not_null` em `passenger_count` removido

O ticket lista `passenger_count` como uma das 5 cols `not_null`. O
ticket foi escrito em 2026-06-08, **antes** do ADR-0016 (aceito
depois) mover `passenger_count_in_range` de `expect_all_or_drop` pra
warn-only. Essa decisão preserva intencionalmente ~428K rows
(~2.6%) na Silver onde TLC ship `passenger_count = NULL` na origem
(driver entry omission, irrecuperável até via `_rescued_data` — query
de prova no ADR-0016 §Context).

Primeira execução de `dbt test` confirmou: `not_null` em
`passenger_count` retornou `FAIL 427746` — exatamente o número
documentado no ADR-0016. Manter o teste:

1. Faz o `job_dbt` falhar hard em **toda** execução contra o dataset
   real (não condicional a regression).
2. Contradiz uma ADR aceita (ADR-0016 §Decision).
3. Não captura nenhum vetor que outro mecanismo não cubra — a
   contagem de NULLs vira métrica observável via DLT event log /
   audit, não algo a bloquear propagação.

Decisão: removido `not_null` de `passenger_count`. Mantidos os outros
4 `not_null` no source (totalizam 4 cols Silver com hard-fail, não
5). Análises que dependem de `passenger_count` (Q2: média de
passageiros/hora em maio) filtram `WHERE passenger_count IS NOT NULL`
explicitamente, per ADR-0016 §Decision. Desvio anotado in-line em
`sources.yml` (~12 linhas de comentário sob "Deviation from ticket
#09 spec").

Se em revisão futura quisermos hard-fail nesse vetor, a forma
correta seria um custom test (`dbt-utils:expression_is_true` com
`passenger_count IS NOT NULL OR <regra-de-aceitação>`) explicitando
qual fração de NULL é tolerada — escopo fora deste ticket.

### Acceptance criteria

- [x] `dbt test` roda os 4 tests (= 10 nodes) sem erro contra dataset
      esperado
- [x] `dbt test --select source:silver` roda os 5 source test nodes
- [x] `dbt test --select yellow_taxi_trips_consumption` roda os 5
      Gold test nodes
- [x] Test `relationships` falharia se LocationID novo (não no seed)
      aparecer na Silver — verificação por inspeção do SQL gerado
      em `target/compiled/.../relationships_*.sql` (LEFT JOIN +
      `WHERE child.location_id IS NULL` clássico do generic test;
      teste inversamente verificado pelo PASS atual contra 260 zones
      do seed)
- [x] Test `accepted_values` falharia se `vendor_id=99` for INSERTado
      na Silver — mesma verificação por inspeção do SQL gerado
- [x] Severidade default (`error`) em todos — sem warn (confirmado
      no output: nenhum `WARN` no resumo final)
- [x] schema.yml respeita conventions dbt (`columns:` block, `data_tests:`,
      args sob `arguments:` per dbt 1.11+ deprecation)

### Gotchas operacionais durante implementação

1. **dbt 1.11+ deprecation `MissingArgumentsPropertyInGenericTestDeprecation`**:
   args de generic tests (`values:`, `to:`, `field:`) precisam ficar
   sob `arguments:`. Primeira versão usava o formato antigo top-level;
   `dbt parse` gerou WARNING. Ajustado os 3 calls (`accepted_values`,
   2× `relationships`) — agora `dbt parse --no-partial-parse` silent.

2. **`relationships.to` referencia node name, NÃO alias**: usar
   `ref('taxi_zone_lookup')` (node name do seed), não
   `ref('dim_locations')` (alias materializado). Mesma armadilha
   documentada no header do `yellow_taxi_trips_consumption.sql` —
   reusada aqui no header do `gold/schema.yml`.

3. **`uv run dbt` direto não funciona** (CLI não está no env do
   projeto): `uv run --with dbt-databricks dbt ...` resolve. Mesma
   regra pra ruff/pytest (`--with ruff` / `--with pytest`).

### Arquivos tocados

- `dbt/models/sources.yml` — adicionado `columns:` block sob
  `yellow_taxi_trips` com 4 `not_null` + 1 `accepted_values`
- `dbt/models/gold/schema.yml` — novo arquivo, 5 test nodes
- `dbt/models/gold/yellow_taxi_trips_consumption.sql` — **intocado**
  (já deployado, conforme briefing)
- `ingestion/` — **intocado**

### Validação

```
$ uv run --with dbt-databricks dbt test --target user_dev
Done. PASS=10 WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=10
$ uv run --with ruff ruff check .
All checks passed!
$ uv run --with pytest pytest -q
132 passed in 0.21s
```
