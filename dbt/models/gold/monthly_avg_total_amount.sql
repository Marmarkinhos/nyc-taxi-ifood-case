{{ config(materialized='view') }}
{#-
  Gold model #2 — Case question 1: "Qual a média mensal de total_amount?"

  Materialization: ``view`` (thin aggregation over the 16M-row Gold
  consumption view, cheap to rebuild; promoted from ``analyses/`` to
  ``models/`` so the notebook in ``notebooks/answers.py`` can
  ``spark.read.table(...)`` it without re-rendering compile-only SQL).

  Source: ``ref('yellow_taxi_trips_consumption')`` (Gold view, already
  scoped to the latest complete ingestion window by
  ``landing_audit.pipeline_update_id`` — ADR-0003).

  Semantics:
    * ``AVG(total_amount)`` is the unweighted mean across every trip
      in the month. ``total_amount`` is the TLC fare-total field
      (fare + tip + tolls + surcharges + congestion + airport_fee);
      see CONTEXT.md "Silver columns".
    * ``trip_count`` is ``COUNT(*)`` — every Gold row has a non-NULL
      ``total_amount`` by Silver expectations (#07 drops negatives /
      sentinels), so ``COUNT(*)`` and ``COUNT(total_amount)`` agree
      here. We keep the explicit ``COUNT(*)`` for legibility of "trips
      per month" as an EDA sanity check.
    * ``pickup_year_month`` is a STRING ('YYYY-MM'), so lexical
      ordering equals chronological ordering for the 2023 window.
-#}

SELECT
    pickup_year_month,
    AVG(total_amount) AS avg_total_amount,
    COUNT(*)          AS trip_count
FROM {{ ref('yellow_taxi_trips_consumption') }}
GROUP BY pickup_year_month
ORDER BY pickup_year_month
