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
-- {{job.run_id}} below IS substituted at task execution time by the
-- Databricks job runner (Jobs parameter system), independent of the
-- bundle. It scopes the UPDATE to the row created by THIS run's
-- landing task.
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
WHERE job_run_id = '{{job.run_id}}'
  AND pipeline_update_id IS NULL;
