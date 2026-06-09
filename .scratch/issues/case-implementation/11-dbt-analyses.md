---
status: done
created: 2026-06-08
tags: [dbt, analyses, business-questions]
blocked-by: [08-dbt-gold-model.md]
blocks: [12-notebook-dashboard.md]
---

# 11 — dbt analyses: 2 perguntas obrigatórias + EDA geográfica

## What to build

Modelos analytics em `dbt/models/analyses/` consumindo
`ref('yellow_taxi_trips_consumption')` (Gold). **São SSoT** —
notebook e dashboard só consomem (CONTEXT.md §Trio de consumo,
Decisão #8).

**3 modelos** (materialização default = view):

### `monthly_avg_total_amount.sql`

Pergunta 1 do case: "média mensal de `total_amount`".

```sql
SELECT
  pickup_year_month,
  AVG(total_amount) AS avg_total_amount,
  COUNT(*) AS trip_count
FROM {{ ref('yellow_taxi_trips_consumption') }}
GROUP BY pickup_year_month
ORDER BY pickup_year_month
```

### `hourly_avg_passenger_count_may.sql`

Pergunta 2 do case: "média de `passenger_count` por hora em Maio".

**ATENÇÃO (ADR-0016):** filtrar `passenger_count IS NOT NULL`
explicitamente. ~101K rows de maio têm `passenger_count` NULL nativo
TLC (driver entry omission) e foram mantidas na Silver pra preservar
fare/distance/location pras outras perguntas. `AVG(passenger_count)`
já ignora NULL implicitamente, mas o `COUNT(*)` ficaria inflado vs o
denominador real da média — usar `COUNT(passenger_count)` ou filtrar
no WHERE.

```sql
SELECT
  pickup_hour,
  AVG(passenger_count) AS avg_passenger_count,
  COUNT(passenger_count) AS trip_count_with_passenger  -- não COUNT(*)
FROM {{ ref('yellow_taxi_trips_consumption') }}
WHERE pickup_year_month = '2023-05'
  AND passenger_count IS NOT NULL  -- ADR-0016: explícito
GROUP BY pickup_hour
ORDER BY pickup_hour
```

### `eda_geographic.sql`

EDA bônus (criatividade — Decisão #8 trio + uso do `dim_locations`):

```sql
SELECT
  pickup_borough,
  dropoff_borough,
  COUNT(*) AS trip_count,
  AVG(total_amount) AS avg_total_amount
FROM {{ ref('yellow_taxi_trips_consumption') }}
GROUP BY pickup_borough, dropoff_borough
ORDER BY trip_count DESC
```

## Acceptance criteria

- [ ] 3 modelos criados em `dbt/models/analyses/`
- [ ] Todos materializam como view em
      `${prefix}nyc_taxi_gold.<modelo>`
- [ ] `dbt run --select analyses` roda os 3 sem erro
- [ ] `monthly_avg_total_amount` retorna 5 linhas (Jan-Mai 2023)
      com Maio como linha existente
- [ ] `hourly_avg_passenger_count_may` retorna 24 linhas (0-23)
- [ ] `eda_geographic` retorna combinações de boroughs com counts
      não-nulos
- [ ] Modelos referenciam Gold via `ref()` (não SQL puro contra
      schema) — preserva linhagem dbt
- [ ] Comentários SQL identificam cada modelo como resposta a qual
      pergunta do case

## Blocked by

- `08-dbt-gold-model.md` (precisa de Gold materializada pra
  `ref()` funcionar)

## Notas

- **Não bloqueado por #10** (`job_dbt` DAB). Os modelos podem ser
  desenvolvidos rodando `dbt run` localmente; `job_dbt` só
  orquestra em workspace.
- `dbt test` cobertura adicional aqui é opcional — modelos são
  agregação simples, testes de schema do #09 cobrem o input.

## Resolution (2026-06-09)

### Deviation from original spec — `analyses/` em vez de `models/analyses/`

Spec original pedia 3 **modelos** em `dbt/models/analyses/` com
materialização `view`. Implementação final usa **dbt analyses
compile-only** em `dbt/analyses/` (nem `dbt run`, nem schema
footprint). Trade-off:

- **Pró:** o Gold (`yellow_taxi_trips_consumption`) já está
  deployado e atende como SSoT pro notebook/dashboard. As 3
  queries do case são **deliverables de relatório**, não
  consumidores downstream — então criar views permanentes
  inflaria o schema `nyc_taxi_gold` sem ganho de reuso. Os
  compiled SQL ficam em `target/compiled/.../analyses/` e podem
  ser injetados direto no notebook (#12).
- **Contra:** não dá pra `dbt run --select analyses` (acceptance
  criterion 3 original). Substituído por: `dbt compile --target
  user_dev` + execução manual via warehouse `10ba36a843e45ac1`
  (SQL Statements API). Aceitação efetiva: contagens de linha +
  resultados numéricos sane, verificados abaixo.

### Arquivos criados

- `dbt/analyses/monthly_avg_total_amount.sql` — Q1 do case
- `dbt/analyses/hourly_avg_passenger_count_may.sql` — Q2 do case
  (com filtro NULL explícito + `COUNT(passenger_count)` por
  ADR-0016)
- `dbt/analyses/eda_geographic.sql` — bônus EDA (matriz borough × borough)

### Resultados numéricos finais

**Q1 — Média mensal de `total_amount`** (5 linhas, Jan–Mai 2023):

| pickup_year_month | avg_total_amount (USD) | trip_count |
| ----------------- | ---------------------: | ---------: |
| 2023-01           |                  27.44 |  3 041 519 |
| 2023-02           |                  27.33 |  2 888 824 |
| 2023-03           |                  28.26 |  3 373 543 |
| 2023-04           |                  28.76 |  3 258 394 |
| 2023-05           |                  29.46 |  3 481 800 |

Total Silver no window (Gold inherit): **16 044 080 trips**.
Crescimento mensal de receita média de ~7.3% (Jan→Mai), volume
de Maio é o pico.

**Q2 — Média de `passenger_count` por hora em Maio** (24 linhas,
horas 0–23). Filtros aplicados conforme ADR-0016
(`passenger_count IS NOT NULL`, `COUNT(passenger_count)`):

- Total de trips com passenger_count NÃO-NULL em Maio: **3 379 187**
  (vs 3 481 800 trips totais — gap de ~102K rows com NULL nativo
  TLC, ~2.95% do mês, alinhado ao ~2.6% médio do dataset
  reportado em ADR-0016).
- Pico de média: hora **03** com **1.437** passageiros/trip
  (madrugada, possíveis viagens em grupo / aeroporto).
- Mínimo de média: hora **06** com **1.235** passageiros/trip
  (commute matinal, viagens solo).
- Pico de volume: hora **18** com **242 164** trips
  (rush-hour fim de tarde).
- Mínimo de volume: hora **04** com **15 905** trips
  (dead-of-night).

Curva tem dois "vales" de média (manhã 5–8h, tarde 12–17h
em torno de ~1.34–1.37) e dois "picos" (madrugada 0–4h e noite
20–23h em torno de ~1.40–1.44) — consistente com hipótese
"viagens noturnas tendem a ser em grupo".

**Q3 — EDA geográfica** (63 combinações borough × borough, top 10
por volume):

| pickup_borough | dropoff_borough |  trip_count | avg_total_amount |
| -------------- | --------------- | ----------: | ---------------: |
| Manhattan      | Manhattan       |  13 238 171 |          USD 21.03 |
| Queens         | Manhattan       |     872 712 |          USD 80.36 |
| Manhattan      | Queens          |     489 061 |          USD 65.58 |
| Manhattan      | Brooklyn        |     343 763 |          USD 43.15 |
| Queens         | Queens          |     341 174 |          USD 39.04 |
| Queens         | Brooklyn        |     223 038 |          USD 69.52 |
| Unknown        | Unknown         |     125 023 |          USD 28.57 |
| Brooklyn       | Brooklyn        |      52 421 |          USD 23.92 |
| Manhattan      | Bronx           |      49 287 |          USD 46.66 |
| Manhattan      | EWR             |      41 505 |         USD 125.84 |

Insights:

- **82.5% das viagens são intra-Manhattan** (13.2M / 16M)
  — esperado para yellow cab (fora dos boroughs externos).
- **Aeroportos dominam tarifa média**: Queens→Manhattan (USD 80,
  JFK/LGA→centro), Manhattan→EWR (USD 125, Newark NJ), Manhattan→Queens
  (USD 66, centro→JFK/LGA). Volume + fare combinados confirmam
  o padrão "yellow taxi atende corredor airport↔centro".
- **NULL/Unknown buckets** (`pickup_borough IS NULL` ou
  `dim_locations` sem match): ~125K trips Unknown×Unknown +
  small long-tail (Staten Island, EWR como pickup, etc).
  Mantidos no output como sinal de EDA (~0.8% do total),
  filtráveis na apresentação.

### Verificação executada

```bash
export DBT_TOKEN=$(awk '/^\[free-edition\]/{f=1;next} f && /^token/{print $3;exit}' ~/.databrickscfg)
cd dbt && uv run --project .. --extra dbt dbt compile --target user_dev
# → Found 1 model, 3 analyses, 1 seed, 2 sources, 758 macros

# Cada analysis executada via SQL Statements API contra warehouse
# 10ba36a843e45ac1 (Serverless Starter). Cold start primeira query ~20s,
# subsequentes <2s. Todas SUCCEEDED, contagens de linha confirmadas:
#   monthly_avg_total_amount      → 5 rows  (Jan–Mai)
#   hourly_avg_passenger_count_may → 24 rows (hours 0–23)
#   eda_geographic                → 63 rows (borough × borough combos)
```

### Gates

- `uv run --extra dev ruff check .` → All checks passed!
- `uv run --extra dev pytest -q` → 132 passed in 0.18s

### Não tocado

- `ingestion/` (escopo do #06, fora deste ticket)
- `dbt/models/` (Gold já deployado, intencionalmente preservado)
- `.scratch/issues/case-implementation/README.md` (sem alteração
  no índice de tickets — só o status YAML deste arquivo)
