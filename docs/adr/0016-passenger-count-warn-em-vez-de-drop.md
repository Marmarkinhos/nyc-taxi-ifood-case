# 0016: `passenger_count_in_range` como warn em vez de drop pra preservar fare/distance/location

## Status

Accepted. Refina ADR-0007 (expectations) e complementa ADR-0015
(type-drift recovery).

## Context

Pós ADR-0015 a Silver tinha 15.62M rows com **428.665 rows ainda
dropadas** pela expectation `passenger_count_in_range` (`passenger_count
BETWEEN 0 AND 9`, dentro de `@dlt.expect_all_or_drop`).

Investigação dessa sessão (não cabia no ADR-0015) provou que esses
428K **não são recuperáveis**:

| Mês | Total Bronze | NULL em col typed **E** JSON `_rescued_data` |
|---|---|---|
| 2023-01 | 3.066.766 | 71.743 |
| 2023-02 | 2.913.955 | 76.817 |
| 2023-03 | 3.403.766 | 87.619 |
| 2023-04 | 3.288.250 | 90.690 |
| 2023-05 | 3.513.649 | 101.796 |
| **Total** | **16.186.386** | **428.665** |

Query de validação (Bronze):

```sql
SELECT regexp_extract(_source_file_path, 'yellow_tripdata_(\d{4}-\d{2})', 1) AS m,
       COUNT(*) AS total,
       SUM(CASE WHEN passenger_count IS NULL
                  AND (get_json_object(_rescued_data, '$.passenger_count') IS NULL
                       OR get_json_object(_rescued_data, '$.passenger_count') = 'null')
                THEN 1 ELSE 0 END) AS truly_null_pc
FROM workspace.nyc_taxi_bronze.yellow_taxi_trips_raw
GROUP BY 1 ORDER BY 1;
```

São rows onde TLC ship o parquet com `passenger_count` **NULL na
origem** (driver entry omission — padrão conhecido do dataset TLC,
~2.6% do total). O coalesce do ADR-0015 não tem fonte alternativa pra
buscar.

### O problema com manter como `or_drop`

A row inteira é dropada por causa de **uma única coluna NULL**. Isso
destrói as outras colunas válidas:

- `fare_amount`, `total_amount` — usadas em **Q1** ("média de
  total_amount por mês") e **Q3/Q4**
- `tpep_pickup_datetime`, `pu_location_id`, `do_location_id` — usadas
  em todas as agregações geográficas e temporais
- `trip_distance`, `payment_type` — análises EDA

Pra responder **Q1** ("Qual a média de total_amount recebido em um mês
considerando todos os yellow táxis"), dropar 428K rows válidas em
total_amount porque `passenger_count` é NULL **degrada a resposta sem
ganho de qualidade**.

### Alternativas consideradas

**A1 — Manter `or_drop` (status quo).** Perde 428K rows pra todas as
perguntas do case. Justificativa "Silver pura" não compensa o custo.

**A2 — Recovery extra na Silver (e.g., `coalesce(passenger_count, 1)`).**
Inventa dado. Pior que dropar — degrada Q2 silenciosamente.

**A3 (escolhida) — Mover `passenger_count_in_range` pra `expect_all`
(warn-only).** Silver mantém as 428K rows com `passenger_count = NULL`;
análises de Q2 ("média passageiros por hora em maio") filtram
explicitamente `WHERE passenger_count IS NOT NULL` no dbt; análises de
Q1/Q3/Q4 usam as 428K rows normalmente.

Custo: 1 linha de código no `dlt_pipeline.py`. Benefício: 428K rows
adicionais nas perguntas que não dependem de `passenger_count`,
narrativa de qualidade defensável no README.

## Decision

1. **Mover `passenger_count_in_range` de `@dlt.expect_all_or_drop` pra
   `@dlt.expect_all`** em `ingestion/dlt_pipeline.py:386-405`. Continua
   sendo monitorada (warn-only no UI), não dropa rows.

2. **As 3 expectations que continuam em `or_drop`** são as que **corromperiam
   métricas se passassem**:
   - `total_amount_non_negative` — refunds não devem entrar em
     "valor médio recebido" (Q1).
   - `trip_timestamps_not_null` — sem timestamps, row é inutilizável
     pra qualquer análise temporal.
   - `dropoff_after_pickup` — timestamps invertidos quebram cálculo de
     duração.

3. **Análises dbt que dependem de `passenger_count` (Q2 e EDA de
   passageiros) DEVEM filtrar `WHERE passenger_count IS NOT NULL`
   explicitamente**. Documentar no `analyses/` SQL com comment
   referenciando este ADR.

4. **README explica a decisão** na seção "Qualidade de dados": "428K
   rows (2.6%) têm `passenger_count` NULL nativo TLC; mantidas na
   Silver pra preservar fare/distance/location; análises de
   passageiros filtram explicitamente."

## Relação com ADR-0007 e ADR-0015

- **ADR-0007** estabeleceu o princípio "zero `expect_or_fail`" e
  inventário de expectations. Este ADR refina o critério de
  `or_drop` vs `or` (warn): **drop só quando manter a row corromperia
  uma resposta**; warn quando o problema é ortogonal às outras colunas.
- **ADR-0015** recuperou ~12.65M rows via `_rescued_data` coalesce. Os
  428K deste ADR são o resíduo que o coalesce não alcança (NULL na
  origem, não no rescue). ADR-0016 fecha o gap restante via política
  de severidade.

## Consequences

**Positivas:**

- Silver vai de 15.62M → **16.04M rows** (validado update
  `2811b96d-9440-4f6d-bdc3-a12c0730b7dd`, 2026-06-09).
- Q1/Q3/Q4 do case ganham 2.6% mais dados.
- Narrativa de README mais defensável: "preservamos rows onde só uma
  coluna ortogonal está faltando".

**Negativas:**

- `passenger_count_in_range` continua disparando warning no DLT UI
  (428K records flagged). Operador precisa saber ler ADR-0016 pra não
  achar que é bug.
- Análises de Q2 precisam lembrar do filtro `IS NOT NULL` —
  responsabilidade movida pra camada dbt. Mitigação: comment SQL no
  modelo `analyses/passenger_count_per_hour.sql` (ticket #11) com link
  pra este ADR.

**Neutras:**

- Outras 3 expectations `or_drop` inalteradas — política só foi
  reavaliada pra `passenger_count_in_range`.
- ADR-0015 inalterado (recovery via `_rescued_data` continua
  necessária pros 12.65M que TLC ship typed-NULL mas com valor no JSON).

## Cross-references

- **ADR-0007** — política geral de expectations. Este ADR refina o
  critério `or_drop` vs `or`.
- **ADR-0015** — recovery via `_rescued_data`. Este ADR cobre o
  resíduo não recuperável.
- **`docs/CASE.md`** §2 — perguntas Q1 (total_amount) e Q2
  (passenger_count) usadas como argumento.
- **`ingestion/dlt_pipeline.py:386-405`** — implementação.
- **AGENTS.md** §"Gotchas operacionais" — entrada nova sobre o
  trade-off `or_drop` vs `or` (warn).
