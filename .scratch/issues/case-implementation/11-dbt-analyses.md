---
status: ready-for-agent
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
