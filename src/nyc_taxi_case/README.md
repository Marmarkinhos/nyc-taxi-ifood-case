# src/nyc_taxi_case/

## O que é

Pacote Python puro com helpers **side-effect-free**: zero Spark, zero
IO, zero dependência de cluster Databricks. Importável tanto pelos
notebooks (`landing.py`, `dlt_pipeline.py`) quanto pelos tests
unitários locais (`uv run pytest`).

Módulos:

- [`case_contract.py`](case_contract.py) — contrato externo do case
  (5 colunas obrigatórias, regex `FILE_YEAR_MONTH_PATTERN`,
  `extract_file_year_month`). Renomeado de `schema.py` pra
  desambiguar de `tlc_schema.py`.
- [`tlc_schema.py`](tlc_schema.py) — mapa de rename TLC → canônico +
  tipos Silver + `bronze_schema_hints()` (ADR-0014/0015).
- [`landing_paths.py`](landing_paths.py) — montagem de paths de
  Volume UC (`/Volumes/<cat>/<schema>/<vol>/<yyyy>/<mm>/`).
- [`tlc_urls.py`](tlc_urls.py) — URLs canônicas do CloudFront TLC.
- [`window.py`](window.py) — geração da janela de meses
  (`[MIN_MONTH..MAX_MONTH]` por default; override via env var).
- [`probe.py`](probe.py) — HEAD-probe HTTP defensivo (ADR-0002) pra
  detectar arquivos ainda não publicados.
- [`audit.py`](audit.py) — schema + builders do `landing_audit`
  (ADR-0008).

## O que NÃO está aqui

- **Código Spark.** PySpark/DLT vivem em
  [`../../ingestion/`](../../ingestion/). Os helpers daqui são
  chamados de lá mas não importam `pyspark`.
- **Tests.** Por restrição operacional (DAB sync precisa de
  `pyproject.toml` enxuto no path do bundle), os testes desses
  módulos vivem em [`../../ingestion/tests/`](../../ingestion/tests/).

## Onde olhar a contraparte

- Quem importa esses módulos: `../../ingestion/landing.py` e
  `../../ingestion/dlt_pipeline.py`.
- Tests: [`../../ingestion/tests/`](../../ingestion/tests/) — naming
  `test_<module>.py` espelha os módulos daqui.
