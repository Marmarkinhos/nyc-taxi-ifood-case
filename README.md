# NYC Taxi Case

iFood data engineering case — ingestion pipeline for NYC Yellow Taxi
trips (Jan–May 2023) running on **Databricks Free Edition**.

> Status: 🚧 **work in progress.** Tickets #02–#03 are done: repo
> skeleton, pure helpers, CI, and the Landing notebook + audit row.
> DLT pipeline, dbt project and AI/BI dashboard arrive in the
> subsequent slices (`.scratch/issues/case-implementation/`).

## Architecture in one paragraph

Monorepo with **two independent DAB jobs** that do *not* declare any
cross-job `depends_on`:

1. **`job_ingestion`** — Databricks Asset Bundle + Lakeflow Declarative
   Pipelines (DLT) + Auto Loader: TLC parquet → Volume UC (**Landing**)
   → **Bronze** Streaming Table → **Silver** canonical Materialized View.
2. **`job_dbt`** — `dbt-databricks` consuming Silver via `sources.yml`,
   producing **Gold** + `dim_locations` seed + analyses.

The single contract between the two jobs is the Silver table in Unity
Catalog. Mirrors the iFood pattern (`ifp-data-ingestions` DLT-pure +
`pagob2b-dbt` dbt-pure). See ADR-0010 and ADR-0011.

For the load-bearing vocabulary (Landing, Bronze, Silver, Gold,
`pickup_year_month`, `file_year_month`, Janela de ingestão, etc.) read
[`CONTEXT.md`](./CONTEXT.md). For the historical plan and full ADR
chain, read [`docs/PLAN.md`](./docs/PLAN.md) and
[`docs/adr/`](./docs/adr/).

## Repository layout

```
.
├── databricks.yml              # Root DAB bundle
├── resources/
│   └── general_variables.yml   # Shared catalog/schema/volume vars
├── src/nyc_taxi_case/          # Pure Python helpers (Spark-free)
│   ├── window.py               # Ingestion window parsing/expansion
│   ├── tlc_urls.py             # TLC CloudFront URL builder
│   ├── schema.py               # 5-column contract + filename regex
│   ├── landing_paths.py        # Volume UC Hive-partitioned layout
│   ├── probe.py                # ADR-0002 HEAD probe classifier
│   └── audit.py                # ADR-0008 landing_audit row + DDL
├── ingestion/
│   ├── landing.py              # Spark entry point: HTTP -> Volume + audit
│   └── tests/                  # pytest unit suite for src/ + landing.py
├── docs/
│   ├── PLAN.md                 # Historical execution plan
│   ├── CASE.md                 # Original case statement
│   └── adr/                    # Accepted decisions (0001-0011)
├── .scratch/issues/            # Local issue tracker (see AGENTS.md)
└── .github/workflows/ci.yml    # Lint + types + pytest (no bundle job: see CI section)
```

The DLT pipeline definition, the dbt project, and the per-job
resource YAMLs (including the `job_ingestion` DAB that submits
`ingestion/landing.py`) are added by tickets #04–#12.

## Local development

Requires Python 3.12 and the [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html).
Auth profile in `~/.databrickscfg` named `free-edition`.

```bash
# 1) Create venv + install package and dev tooling
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

# 2) Run the same checks CI runs
ruff check .
mypy src/
pytest ingestion/tests/

# 3) Schema-validate the bundle (no workspace round-trip)
databricks --profile free-edition bundle validate --target user_dev
```

## CI

The GitHub Actions workflow runs **ruff + mypy (strict) + pytest with
coverage** on every push to `main` and every pull request. It does
**not** run `databricks bundle validate`: the CLI always calls
`/api/2.0/preview/scim/v2/Me` and therefore needs a real workspace
PAT, and Free Edition cannot use service principals (CONTEXT.md
"NÃO-objetivos"). DAB validation is part of the local dev loop
instead — run the `bundle validate` step above before pushing any
DAB change.

## Project rules (see `AGENTS.md`)

- Every `databricks` CLI command in this repo uses
  `--profile free-edition`.
- `dbt/profiles.yml` is **never** committed — the serverless `dbt_task`
  generates it at runtime.
- DAB schedules are paused in every target; runs are manual via
  `bundle run`.
- Conventional Commits, wrap at 72 columns, *why* over *what*.

## Case statement

See [`docs/CASE.md`](./docs/CASE.md) for the original prompt.
