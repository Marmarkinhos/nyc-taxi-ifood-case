# NYC Yellow Taxi — iFood data engineering case

End-to-end ingestion + modelling + analytics pipeline for the NYC TLC
Yellow Taxi trips dataset (Jan–May 2023), running on **Databricks Free
Edition** serverless. Built as a monorepo with **two independent
Databricks Asset Bundle (DAB) jobs** that mirror the canonical iFood
split between an ingestion repo (`ifp-data-ingestions`) and a dbt repo
(`pagob2b-dbt`).

The original case statement lives in [`docs/CASE.md`](./docs/CASE.md).
The load-bearing vocabulary (Landing, Bronze, Silver, Gold,
`pickup_year_month`, Janela de ingestão, …) lives in
[`CONTEXT.md`](./CONTEXT.md). The accepted architectural decisions
live in [`docs/adr/`](./docs/adr/).

## TL;DR

- **Stack:** Databricks Free Edition (serverless only) + Unity Catalog
  + Lakeflow Declarative Pipelines (DLT) + Auto Loader + `dbt-databricks`
  + AI/BI (Lakeview) dashboard. All orchestration via DAB.
- **Two DAB jobs, no cross-job `depends_on`:** `job_ingestion`
  (Landing → Bronze → Silver, 4 tasks) and `job_dbt` (Silver → Gold +
  seed + tests, 1 task). Single contract is the Silver table in UC
  (`dbt/models/sources.yml`). See ADR-0010 and ADR-0011.
- **Manual run model:** schedules are PAUSED in every target;
  execution is `bundle run job_ingestion` then `bundle run job_dbt`.
  Free Edition has no service principal and no instance pools.
- **Case answers ship two ways:** `dbt/analyses/*.sql` (compile-only
  source of truth) + `notebooks/answers.py` (interactive `display()`)
  + `resources/nyc_taxi_dashboard.lvdash.json` (AI/BI dashboard, one
  URL for the evaluator). All three read the same Gold view → numbers
  cannot drift.

## Runbook

Assumes a Free Edition workspace and `~/.databrickscfg` with a
`free-edition` profile pointing at it.

```bash
# 1) Schema-validate the bundle offline (no workspace round-trip)
databricks --profile free-edition bundle validate --target user_dev

# 2) Deploy artifacts (wheel + notebooks + SQL + DAB resources)
databricks --profile free-edition bundle deploy --target user_dev

# 3) Run ingestion: TLC parquet → Landing Volume → Bronze → Silver
#    (~5 min the first time; ~3 min on subsequent incremental runs)
databricks --profile free-edition bundle run job_ingestion --target user_dev

# 4) Run modelling: dbt deps + seed (dim_locations) + run (Gold) +
#    test (10 dbt tests)   (~1m30s)
databricks --profile free-edition bundle run job_dbt --target user_dev
```

After step 4:

- Silver: `workspace.nyc_taxi_bronze.yellow_taxi_trips` (~16.04 M
  rows for Jan–May 2023).
- Gold view: `workspace.nyc_taxi_gold.yellow_taxi_trips_consumption`
  — per-trip projection filtered to the active ingestion window via
  `landing_audit` and enriched with borough/zone via `dim_locations`.
- `dim_locations` seed: `workspace.nyc_taxi_gold.dim_locations`
  (265 rows from the TLC zone lookup).
- Operational audit:
  `workspace.nyc_taxi_monitoring.landing_audit` +
  `workspace.nyc_taxi_monitoring.gold_pipeline_observability` (view
  over `event_log(TABLE(<bronze>))` filtered to `flow_progress`,
  `expectation_metrics`, `pipeline_done`).
- AI/BI dashboard:
  `[user_dev] NYC Yellow Taxi — case answers`, queryable from the
  Dashboards menu in the workspace UI.

Override the ingestion window per run:

```bash
databricks --profile free-edition bundle run job_ingestion \
  --target user_dev \
  --params start_year_month=2023-03,end_year_month=2023-03
```

## Repository layout

Monorepo simulating two iFood repos. The split is intentionally
shallow: `git filter-repo --path ingestion/ --path resources/` (plus
the `databricks.yml` bits that reference `job_ingestion`) would carve
`job_ingestion` out into its own repo; the dbt half is already
self-contained under `dbt/`.

```
.
├── databricks.yml                 # Root DAB bundle + wheel artifact + targets
├── resources/
│   ├── general_variables.yml      # catalog / schema / volume / warehouse vars
│   ├── dlt_pipeline.yml           # Lakeflow Declarative Pipeline (Bronze + Silver)
│   ├── job_ingestion.yml          # 4-task DAB job (landing + DLT + audit + monitoring view)
│   ├── job_dbt.yml                # 1-task DAB job (dbt deps/seed/run/test)
│   ├── dashboard.yml              # AI/BI Lakeview dashboard resource
│   └── nyc_taxi_dashboard.lvdash.json
├── src/nyc_taxi_case/             # Pure Python helpers (Spark-free, unit-tested)
│   ├── window.py                  # Ingestion window parsing/expansion
│   ├── tlc_urls.py                # TLC CloudFront URL builder
│   ├── tlc_schema.py              # cloudFiles.schemaHints (ADR-0014, ADR-0015)
│   ├── schema.py                  # 5-column case contract + filename regex
│   ├── landing_paths.py           # Volume UC Hive-partitioned layout
│   ├── probe.py                   # HEAD probe classifier (ADR-0002)
│   └── audit.py                   # landing_audit row + DDL (ADR-0008)
├── ingestion/
│   ├── landing.py                 # Notebook entry point: HTTP → Volume + audit row
│   ├── dlt_pipeline.py            # @dlt.table definitions for Bronze + Silver
│   ├── sql/
│   │   ├── update_landing_audit.sql      # Backfill pipeline_update_id post-DLT
│   │   └── create_monitoring_view.sql    # gold_pipeline_observability view
│   └── tests/                     # pytest unit suite for src/ + landing.py
├── dbt/
│   ├── dbt_project.yml            # No --target on the runtime; see ADR-0010
│   ├── profiles.yml               # ONLY used by local CLI runs
│   ├── packages.yml
│   ├── models/
│   │   ├── sources.yml            # The one cross-job contract (Silver + landing_audit)
│   │   └── gold/
│   │       ├── yellow_taxi_trips_consumption.sql   # Gold view (window-scoped + enriched)
│   │       └── schema.yml         # 5 dbt tests (relationships + not_null)
│   ├── seeds/taxi_zone_lookup.csv # → dim_locations (265 rows, ADR-0009)
│   └── analyses/                  # 3 compile-only case answers + EDA
│       ├── monthly_avg_total_amount.sql        # Q1
│       ├── hourly_avg_passenger_count_may.sql  # Q2
│       └── eda_geographic.sql                  # Q3/Q4 EDA
├── notebooks/
│   └── answers.py                 # display()-driven render of the 3 analyses
├── docs/
│   ├── CASE.md                    # Original iFood case statement
│   ├── PLAN.md                    # Historical execution plan
│   └── adr/                       # ADRs 0001–0016, all Accepted
├── CONTEXT.md                     # Load-bearing vocabulary (read first)
├── AGENTS.md                      # Agent rules + operational gotchas
└── .github/workflows/ci.yml       # ruff + mypy + pytest (no bundle deploy)
```

## Architecture in one diagram

```
                ┌─────────────────────────────────────────────┐
                │  job_ingestion  (manual `bundle run`)       │
                │                                             │
TLC parquet ───▶│ 1. landing_task (notebook)                  │
(CloudFront)    │    HTTP probe + download → Volume UC        │
                │    + landing_audit row (pipeline_update_id  │
                │      = NULL)                                │
                │             │                               │
                │             ▼                               │
                │ 2. dlt_pipeline_task (Lakeflow DLT)         │
                │    Auto Loader → Bronze ST → Silver MV      │
                │    (schemaHints + type widening, 7 DLT      │
                │     expectations — ADR-0014/0015/0016)      │
                │             │                               │
                │             ▼                               │
                │ 3. update_audit_task (sql_task)             │
                │    Backfill landing_audit.pipeline_update_id│
                │    from event_log(TABLE(bronze))            │
                │             │                               │
                │             ▼                               │
                │ 4. refresh_monitoring_view_task (sql_task)  │
                │    CREATE OR REPLACE VIEW                   │
                │      gold_pipeline_observability            │
                └────────────────────┬────────────────────────┘
                                     │
              Silver  (UC table: nyc_taxi_bronze.yellow_taxi_trips)
              landing_audit (UC table: nyc_taxi_monitoring.landing_audit)
                                     │
                                     ▼
                ┌─────────────────────────────────────────────┐
                │  job_dbt  (manual `bundle run`)             │
                │                                             │
                │ 1. dbt_task (dbt-databricks)                │
                │    dbt deps → seed (dim_locations) →        │
                │    run (Gold view, window-filtered via      │
                │           landing_audit) →                  │
                │    test (5 dbt tests, hard-fail)            │
                └────────────────────┬────────────────────────┘
                                     │
              Gold view (nyc_taxi_gold.yellow_taxi_trips_consumption)
                                     │
                  ┌──────────────────┼──────────────────┐
                  ▼                  ▼                  ▼
        dbt analyses/         notebooks/answers.py   AI/BI dashboard
        (compile only,        (display() interactive)(single URL,
         SSoT for SQL)                               viewer-first)
```

No arrow connects `job_ingestion` to `job_dbt`. The only contract is
the Silver table (`dbt/models/sources.yml`). Re-running ingestion for
a new window automatically becomes the new Gold window with zero code
change on the modelling side — see ADR-0003.

## Decisões load-bearing (ADRs)

One line each; full text under `docs/adr/`.

- **[ADR-0001](./docs/adr/0001-silver-canonica-nao-fiel-a-fonte.md)** —
  Silver is canonical (snake_case, typed), not byte-fidelity. Byte
  fidelity lives in Landing.
- **[ADR-0002](./docs/adr/0002-landing-http-com-probe-defensivo.md)** —
  Landing uses HTTP + a HEAD probe before each GET.
- **[ADR-0003](./docs/adr/0003-gold-filtra-janela-silver-preserva-ruido.md)** —
  Gold filters to the latest complete ingestion window via
  `landing_audit`; Silver keeps everything.
- **[ADR-0004](./docs/adr/0004-silver-materializa-file-year-month.md)** —
  Silver materialises `file_year_month` from the source filename.
- **[ADR-0005](./docs/adr/0005-silver-canonica-ajustes-defensivos-quota.md)** —
  Defensive `tblproperties` on Silver (column mapping + quota).
- **[ADR-0006](./docs/adr/0006-silver-liquid-clustering-em-vez-de-particao.md)** —
  Liquid Clustering on Silver (not partitioning) for Free Edition.
- **[ADR-0007](./docs/adr/0007-expectations-sem-expect-or-fail.md)** —
  DLT expectations are warn-only (no `expect_or_fail`); dbt is the
  hard-fail layer.
- **[ADR-0008](./docs/adr/0008-landing-audit-schema-reconstruibilidade.md)** —
  `landing_audit` schema is "reconstruible" (everything needed to
  re-derive a run from scratch).
- **[ADR-0009](./docs/adr/0009-dim-locations-dentro-do-escopo.md)** —
  `dim_locations` is a dbt seed from the TLC zone lookup.
- **[ADR-0010](./docs/adr/0010-fronteira-ingestao-modelagem-na-silver.md)** —
  Boundary between ingestion and modelling lives at Silver canonical.
- **[ADR-0011](./docs/adr/0011-orquestracao-dois-jobs-dab-independentes.md)** —
  Two DAB jobs, no cross-job `depends_on`.
- **[ADR-0012](./docs/adr/0012-landing-notebook-self-bootstrap.md)** —
  Landing notebook self-bootstraps schema + Volume, exits cleanly.
- **[ADR-0013](./docs/adr/0013-timestampntz-feature-flag.md)** —
  Bronze + Silver enable `delta.feature.timestampNtz` because Free
  Edition Delta default rejects TIMESTAMP_NTZ.
- **[ADR-0014](./docs/adr/0014-bronze-schema-hints-e-rescued-data-expectation.md)** —
  Bronze pins `cloudFiles.schemaHints` + warn-only expectation on
  `_rescued_data` (superseded in part by 0015).
- **[ADR-0015](./docs/adr/0015-bronze-type-widening-e-silver-rescued-recovery.md)** —
  Bronze uses `addNewColumnsWithTypeWidening`; Silver coalesces from
  `_rescued_data` for columns without a widening path.
- **[ADR-0016](./docs/adr/0016-passenger-count-warn-em-vez-de-drop.md)** —
  `passenger_count` expectation is warn (not drop) — dropping NULLs
  would corrupt Q1 / Q3 / Q4 answers for those rows.

## Notes that did not graduate to an ADR

These are conscious choices that did not need their own decision
record but are easy to second-guess from the outside.

- **No `_int_` / `_fin_` model prefix convention in dbt.** Three models
  total (Gold + seed + analyses) — model-prefix taxonomies pay off at
  ≥10 models. Rejected as over-engineering.
- **Monorepo, not two GitHub repos.** Splitting into
  `ifp-data-ingestions` + `pagob2b-dbt` shapes is a one-shot
  `git filter-repo` away (`ingestion/` + half of `resources/` →
  ingestion repo; `dbt/` → modelling repo). Keeping them together
  during the case keeps grep / commit history / ADRs in one place.
- **`uv.lock` is gitignored.** Dependencies live in `pyproject.toml`;
  forcing every contributor onto `uv` via a committed lock is friction
  without payoff at this scale.
- **`yellow_tripdata_*.parquet` at the repo root is gitignored.** A
  copy lives there from a one-off local schema-inspection session; the
  pipeline only ever reads parquets from the Volume.

## Trio de consumo

PLAN.md Decisão #8: the case answers ship three ways from the same
Gold view, so the numbers cannot drift.

| Surface | Path | Why |
|---|---|---|
| **dbt analyses** | `dbt/analyses/*.sql` | Compile-only SQL, version-controlled SSoT for the answer queries. Anyone can `dbt compile` and inspect the rendered SQL. |
| **Notebook** | `notebooks/answers.py` | Code-first: open notebook → run cell → interactive chart via `display()`. Source SQL is one click away from any chart. |
| **AI/BI dashboard** | `resources/nyc_taxi_dashboard.lvdash.json` (deployed via DAB) | Viewer-first: a single URL produces the 3 charts without anyone editing code. Reads the same Gold view. |

All three call the same underlying Gold view. Adding a 4th surface
(`/api/2.0/sql/statements`, a Power BI tile, …) means adding a query
against `workspace.nyc_taxi_gold.yellow_taxi_trips_consumption`, not
duplicating analytics logic.

## Local development

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and the
[Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html)
with a `free-edition` profile in `~/.databrickscfg`.

```bash
# Create venv + install package and dev tooling
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

# Run the same checks CI runs (no Databricks round-trip needed)
ruff check .
mypy src/
pytest ingestion/tests/

# Schema-validate the bundle (no workspace round-trip)
databricks --profile free-edition bundle validate --target user_dev
```

Running dbt locally (against the Free Edition warehouse) requires
exporting `DBT_TOKEN=$(databricks --profile free-edition auth token \
| jq -r .access_token)` and then `cd dbt && dbt build --target user_dev`.
The committed `dbt/profiles.yml` is **only** used for this CLI path —
the `dbt_task` runtime in `job_dbt` ignores it and auto-generates a
`databricks_cluster` profile from `dbt_task.catalog/schema/warehouse_id`
(ADR-0010 §Validação empírica).

## CI

[`.github/workflows/ci.yml`](./.github/workflows/ci.yml) runs **ruff +
mypy (strict) + pytest with coverage** on every push to `main` and
every PR. It deliberately does **not** run `databricks bundle
validate`: the CLI always calls `/api/2.0/preview/scim/v2/Me` and
therefore needs a real workspace PAT, and Free Edition cannot use
service principals (CONTEXT.md "Não-objetivos"). DAB validation is
part of the local dev loop (`bundle validate` above) instead.

## Known limitations (Free Edition)

- **Serverless only.** No instance pools, no all-purpose clusters,
  no service principals. `bundle deploy` requires a real user PAT.
- **Single MANAGED catalog (`workspace`).** Multi-catalog routing is
  wired via `${var.catalog}` for future use but pinned to `workspace`
  here.
- **Schedules are paused everywhere.** Execution is manual via
  `bundle run`. The job YAMLs declare schedules with `pause_status:
  PAUSED` so the UI shows them as "scheduled but paused", which is
  one click away from being enabled.
- **No CI deploy.** Deploys to the workspace are operator-initiated
  from a machine that has the `free-edition` PAT.
- **Warehouse cold start (~20 s).** The Serverless Starter Warehouse
  used by `update_audit_task`, `refresh_monitoring_view_task`, the
  dbt task, and the dashboard sleeps when idle; the first query of
  a session incurs a one-time spin-up.

## Case statement

See [`docs/CASE.md`](./docs/CASE.md) for the original iFood prompt.
