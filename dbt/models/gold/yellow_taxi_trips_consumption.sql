{#-
  Gold model — per-trip projection of the Silver canonical table,
  filtered to the window of the most recent COMPLETE ``job_ingestion``
  run and enriched with borough/zone via ``dim_locations``.

  Materialization: ``view`` (inherited from ``dbt_project.yml``;
  intentional — Gold here is a thin projection over a 16M-row Silver,
  cheap to rebuild, and analyses in #11 do their own aggregation).

  Why this exists (ADR-0010, ADR-0011):
    Modelling does not share job dependencies with ingestion. The only
    coupling is ``sources.yml`` + this query. The "active window" of
    Gold is therefore inferred from ``landing_audit`` rather than
    hardcoded, so a re-run of ``job_ingestion`` for a different
    year-month range automatically becomes the new Gold window with no
    code change on the modelling side (ADR-0003).

  Window contract (ADR-0003, ADR-0008):
    A row in ``landing_audit`` counts as a COMPLETE ingestion run
    when ``pipeline_update_id IS NOT NULL`` — the post-DLT SQL task
    (``update_landing_audit.sql``, ticket #06) only backfills this
    column AFTER the DLT update finishes, so its presence is the
    audit's way of saying "Silver is up to date for this window".
    Rows from interactive landing runs (notebook only, no DLT
    triggered) leave it NULL and are filtered out.

    The "most recent" run is chosen by ``MAX(job_start_ts)`` among
    those complete rows — re-running the same year-month window
    overwrites the previous Gold definition rather than carrying it.

  First-run hard-fail (acceptance criterion #4):
    If no complete run exists, the model errors at compile time with
    an actionable message instead of producing an empty (or
    silently-wrong) view. This makes the ``job_ingestion``
    → ``job_dbt`` ordering an enforced invariant rather than a wiki
    note (ADR-0011 §Comportamento do job_dbt).
-#}

{%- set audit_check_query -%}
  SELECT COUNT(*) AS n
  FROM {{ source('monitoring', 'landing_audit') }}
  WHERE pipeline_update_id IS NOT NULL
{%- endset -%}

{%- if execute -%}
  {%- set result = run_query(audit_check_query) -%}
  {%- if result and result.columns[0].values()[0] == 0 -%}
    {{ exceptions.raise_compiler_error(
      "landing_audit has no rows with pipeline_update_id (no complete "
      ~ "ingestion run on record). Run `databricks bundle run "
      ~ "job_ingestion --target user_dev` first so the post-DLT SQL "
      ~ "task backfills pipeline_update_id, then re-run dbt."
    ) }}
  {%- endif -%}
{%- endif -%}

WITH latest_complete_run AS (
    -- Window of the most recent ``job_ingestion`` run that completed
    -- through the post-DLT SQL backfill (pipeline_update_id filled).
    -- Returned as two scalars so the downstream filter is a cheap
    -- range comparison rather than a join.
    SELECT
        start_year_month,
        end_year_month
    FROM {{ source('monitoring', 'landing_audit') }}
    WHERE pipeline_update_id IS NOT NULL
    ORDER BY job_start_ts DESC
    LIMIT 1
),

trips_in_window AS (
    -- Per-trip projection of Silver columns the case asks for, scoped
    -- to the active window. ``pickup_year_month`` is the Silver
    -- clustering key (DLT-materialised), so the BETWEEN below is a
    -- partition prune, not a full scan.
    SELECT
        s.vendor_id,
        s.passenger_count,
        s.total_amount,
        s.tpep_pickup_datetime  AS pickup_at,
        s.tpep_dropoff_datetime AS dropoff_at,
        s.pickup_year_month,
        HOUR(s.tpep_pickup_datetime) AS pickup_hour,
        s.pu_location_id        AS pickup_location_id,
        s.do_location_id        AS dropoff_location_id
    FROM {{ source('silver', 'yellow_taxi_trips') }} AS s
    WHERE s.pickup_year_month BETWEEN
            (SELECT start_year_month FROM latest_complete_run)
        AND (SELECT end_year_month   FROM latest_complete_run)
)

SELECT
    t.vendor_id,
    t.passenger_count,
    t.total_amount,
    t.pickup_at,
    t.dropoff_at,
    t.pickup_year_month,
    t.pickup_hour,
    t.pickup_location_id,
    t.dropoff_location_id,
    -- Borough/zone via ``dim_locations`` (ADR-0009). LEFT JOIN so an
    -- unknown LocationID surfaces as NULL rather than dropping the
    -- trip — the seed covers the 260 published TLC zones and any
    -- drift should be visible, not silent.
    pu.borough AS pickup_borough,
    pu.zone    AS pickup_zone,
    do_.borough AS dropoff_borough,
    do_.zone    AS dropoff_zone
FROM trips_in_window AS t
-- ``taxi_zone_lookup`` is the seed node name; ``dim_locations`` is
-- the materialised table alias (``+alias`` in dbt_project.yml). dbt
-- ``ref()`` resolves by node name, not alias — calling
-- ``ref('dim_locations')`` raises "node not found".
LEFT JOIN {{ ref('taxi_zone_lookup') }} AS pu
       ON t.pickup_location_id  = pu.location_id
LEFT JOIN {{ ref('taxi_zone_lookup') }} AS do_
       ON t.dropoff_location_id = do_.location_id
