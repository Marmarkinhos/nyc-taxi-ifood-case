{{ config(materialized='view') }}
{#-
  Gold model #4 — Bonus EDA (case "creativity" axis, plan Decisão #8):
  pickup-borough × dropoff-borough flow matrix with trip volume and
  average fare.

  Materialization: ``view``. Promoted from ``analyses/`` to ``models/``
  so the notebook in ``notebooks/answers.py`` can read it as a regular
  Spark table — see header of ``monthly_avg_total_amount.sql`` for the
  rationale.

  What it answers:
    * "Which inter-borough flows carry the most yellow-cab volume
      in 2023-01..05?" — ordered by ``trip_count DESC``.
    * "How does average fare vary across those flows?" —
      Manhattan↔airport pairs (JFK/LGA in Queens) typically dominate
      ``avg_total_amount`` while intra-Manhattan dominates volume.

  Source: ``ref('yellow_taxi_trips_consumption')`` (Gold already joins
  ``dim_locations`` for borough/zone — ADR-0009 — so this query is a
  pure aggregation, no extra joins needed).

  NULL handling:
    * ``pickup_borough`` / ``dropoff_borough`` can be NULL when the
      Silver ``LocationID`` is outside the 260 published TLC zones
      (drift, sentinel codes). We KEEP the NULL buckets in the output
      rather than filtering — they're a useful EDA signal ("how much
      traffic falls outside the published zones?") and dropping them
      would silently shrink ``trip_count``. The notebook /
      dashboard can choose to filter at the presentation layer.
    * No NULL filter on ``total_amount`` — Gold inherits Silver's
      drop-on-negative / drop-on-zero expectations (#07), so every
      surviving row has a usable fare.
-#}

SELECT
    pickup_borough,
    dropoff_borough,
    COUNT(*)          AS trip_count,
    AVG(total_amount) AS avg_total_amount
FROM {{ ref('yellow_taxi_trips_consumption') }}
GROUP BY pickup_borough, dropoff_borough
ORDER BY trip_count DESC
