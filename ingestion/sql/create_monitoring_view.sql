-- create_monitoring_view.sql
--
-- Fourth task of job_ingestion (ticket #13, PLAN.md §10): expose the
-- Lakeflow Declarative Pipeline event log as a queryable view under
-- the ``nyc_taxi_monitoring`` schema, so the evaluator can audit
-- the last N updates of ``yellow_taxi_ingestion`` from the SQL
-- editor (or a Lakeview dashboard) without invoking
-- ``event_log()`` directly.
--
-- ``CREATE OR REPLACE VIEW`` is intentionally idempotent: running
-- this task on every job_ingestion run rebinds the view to whatever
-- the pipeline currently is. No-op when the view definition has not
-- changed, cheap when it has.
--
-- Why literal catalog/schema (not ``${var.*}``):
-- same reasoning as ``update_landing_audit.sql`` — DAB does not
-- substitute ``${...}`` inside SQL bodies referenced via
-- ``sql_task.file.path``. Free Edition pins these to:
--   catalog       = workspace
--   bronze_schema = nyc_taxi_bronze
--   monitoring_sch = nyc_taxi_monitoring
-- A future target override means editing this file in lockstep with
-- ``general_variables.yml`` — a single grep keeps it discoverable.
--
-- Why ``event_log(TABLE(<bronze_fqn>))`` instead of
-- ``event_log("<pipeline_id>")``:
-- the TABLE form resolves the right event log via the published
-- Bronze table reference, so the view survives a pipeline
-- ``delete + recreate`` cycle (which mints a new ``pipeline_id``).
-- The AGENTS.md "gotchas operacionais" section calls this out
-- explicitly. ``event_log("<update_id>")`` is a third, distinct
-- form (UPDATE-scoped) and would not work here either way.
--
-- Filter rationale (event_type whitelist):
--   ``flow_progress``       — per-flow rowcounts + status (the
--                             closest thing to "how many Bronze /
--                             Silver rows did this update write?").
--   ``expectation_metrics`` — the DLT expectations declared in
--                             ``ingestion/dlt_pipeline.py`` (#05),
--                             with pass / fail / warn counts.
--   ``pipeline_done``       — terminal status of each update so the
--                             evaluator can spot a FAILED update
--                             without scrolling.
-- Everything else (``planning``, ``cluster_resources``,
-- ``user_action``, etc.) is intentionally omitted to keep the view
-- focused on data quality + run outcome.

CREATE OR REPLACE VIEW workspace.nyc_taxi_monitoring.gold_pipeline_observability AS
SELECT
  timestamp,
  event_type,
  message,
  details
FROM event_log(TABLE(workspace.nyc_taxi_bronze.yellow_taxi_trips_raw))
WHERE event_type IN (
  'flow_progress',
  'expectation_metrics',
  'pipeline_done'
)
ORDER BY timestamp DESC;
