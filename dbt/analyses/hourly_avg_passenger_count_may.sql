{#-
  Analysis #2 — Case question 2: "Qual a média de passenger_count por
  hora do dia, considerando todas as viagens de Maio?"

  Compile-only analysis. See ``monthly_avg_total_amount.sql`` for the
  rationale on living under ``analyses/`` rather than ``models/``.

  ADR-0016 — load-bearing decision in this query:

    ``passenger_count`` is NULL in ~2.6 % of TLC rows (driver entry
    omission; ~101K rows in May 2023). These rows are KEPT in Silver
    because dropping them would corrupt the answers to the other
    case questions (Q1 total_amount, Q3+Q4 geographic) that use the
    same row's fare / distance / location columns. The trade-off is
    pushed down to the analysis layer: queries that aggregate
    ``passenger_count`` must filter the NULLs explicitly so the
    denominator is the population of trips WITH a recorded passenger
    count, not the population of all trips.

    * ``AVG(passenger_count)`` already ignores NULL implicitly per
      ANSI SQL — the average value is correct without the WHERE
      clause. The risk is the COUNT we report alongside it:
      ``COUNT(*)`` would surface the full-month row count (e.g.
      3.5M) which is NOT the denominator of the average and reads
      as a 2.6 % discrepancy under audit.
    * We therefore (a) ``WHERE passenger_count IS NOT NULL``
      explicitly so the row set is unambiguous and (b) use
      ``COUNT(passenger_count)`` for the same reason — defence in
      depth, since either alone would suffice.

  Source + window: ``ref('yellow_taxi_trips_consumption')`` is already
  filtered to the latest complete ingestion window (ADR-0003); the
  ``pickup_year_month = '2023-05'`` predicate narrows to May within
  that window.

  Grouping key: ``pickup_hour`` is ``HOUR(tpep_pickup_datetime)``
  pre-computed in Gold (0..23), so the GROUP BY is a cheap integer
  bucket rather than a recomputed function call.
-#}

SELECT
    pickup_hour,
    AVG(passenger_count)    AS avg_passenger_count,
    -- ADR-0016: COUNT(passenger_count) — NOT COUNT(*) — so the
    -- denominator reported matches the denominator of the AVG.
    COUNT(passenger_count)  AS trip_count_with_passenger
FROM {{ ref('yellow_taxi_trips_consumption') }}
WHERE pickup_year_month = '2023-05'
  -- ADR-0016: explicit NULL filter so the row set is unambiguous to
  -- the reader (AVG already ignores NULL; this makes the contract
  -- visible at the SQL level rather than implicit in ANSI semantics).
  AND passenger_count IS NOT NULL
GROUP BY pickup_hour
ORDER BY pickup_hour
