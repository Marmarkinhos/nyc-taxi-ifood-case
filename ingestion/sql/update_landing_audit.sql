-- update_landing_audit.sql
--
-- Third task of job_ingestion (ADR-0011, ADR-0008): backfill the
-- pipeline_update_id column of the landing_audit row written by the
-- landing task earlier in the same job run, with the update_id of the
-- DLT pipeline that just finished.
--
-- Why catalog/schema are LITERAL strings and not ${var.*}:
-- the Databricks Asset Bundle does NOT perform ${...} substitution
-- inside SQL files referenced via sql_task.file.path (verified against
-- both tompero docs and Databricks docs — the schema only accepts
-- query_id / alert_id / file.path / dashboard inside sql_task; there
-- is no inline-query form). Free Edition pins these to:
--   catalog        = workspace
--   bronze_schema  = nyc_taxi_bronze
--   monitoring_sch = nyc_taxi_monitoring
-- If a future target overrides those vars, this file must be edited in
-- lockstep — a single grep keeps it discoverable. The literals are
-- intentionally bare (no jinja, no templating) so the SQL is runnable
-- standalone from the Databricks SQL editor for debugging.
--
-- :job_run_id is the documented Databricks named-parameter binding
-- (see Lakeflow Jobs > Access parameter values from a task — "Use
-- named parameters in SQL"). The value is supplied by the
-- ``sql_task.parameters`` block in ``resources/job_ingestion.yml``,
-- which itself substitutes ``{{job.run_id}}`` at task-execution time
-- via the Jobs dynamic-value-reference system. The pair is coupled
-- by construction to the ``job_run_id`` widget that
-- ``ingestion/landing.py`` writes into ``landing_audit`` (#15 fix).
--
-- The previous form (``WHERE job_run_id = '{{job.run_id}}'`` inline)
-- looked correct but never matched a row: dynamic-value references
-- are substituted only in task-configuration fields (YAML
-- parameters), NOT inside the body of a SQL file referenced via
-- ``sql_task.file.path``. The placeholder was treated as a literal
-- string ``{{job.run_id}}`` and the UPDATE silently affected 0 rows
-- on every run. Surfaced while validating ticket #15 (which fixed
-- the audit-row side of the same dance).
--
-- event_log(TABLE(<bronze_fqn>)) is the Lakeflow recommended form
-- (vs event_log("<pipeline_id>")): it locates the right event_log via
-- the published table reference, so the SQL survives a pipeline
-- delete+recreate that would change the pipeline_id.

UPDATE workspace.nyc_taxi_monitoring.landing_audit
SET pipeline_update_id = (
  SELECT origin.update_id
  FROM event_log(TABLE(workspace.nyc_taxi_bronze.yellow_taxi_trips_raw))
  WHERE event_type = 'create_update'
  ORDER BY timestamp DESC
  LIMIT 1
)
WHERE job_run_id = :job_run_id
  AND pipeline_update_id IS NULL;
