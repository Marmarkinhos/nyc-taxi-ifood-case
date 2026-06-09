"""nyc_taxi_case — pure helpers shared by ingestion job and dbt project.

This package contains side-effect-free logic that is unit-tested in CI
without requiring a Databricks runtime. Side-effectful Databricks code
(notebooks, DLT pipelines, dbt models) lives outside this package.
"""

from __future__ import annotations

__version__ = "0.1.0"
