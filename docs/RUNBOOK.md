# RUNBOOK — nyc-taxi case

Comandos operacionais pra deploy, execução e validação local do
pipeline. Migrado 1:1 do README original (resultado-first) pra
desinflar a entrada principal.

## Pré-requisitos

- Workspace Databricks **Free Edition**.
- `~/.databrickscfg` com profile apontando pro PAT do workspace.
  Nome do profile é livre — abaixo uso `free-edition` por convenção,
  troque pelo seu se for outro:

      [free-edition]
      host  = https://<seu-workspace>.cloud.databricks.com
      token = <seu-PAT>

- Python 3.12 + [uv](https://docs.astral.sh/uv/) +
  [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html)
  na máquina do operador.
- **SQL warehouse id do seu tenant** (varia por workspace Free
  Edition). Descubra via:

      databricks warehouses list --profile free-edition

  e exporte como variável DAB pra todas as invocações abaixo:

      export BUNDLE_VAR_sql_warehouse_id=<id-do-comando-acima>

  Sem isso, `bundle validate` falha com `variable sql_warehouse_id
  has no value assigned`. Por que sem default: ver comentário em
  `databricks.yml` no bloco `user_dev.variables.sql_warehouse_id`.

O bundle **não** declara `workspace.host` no target `user_dev`: o
CLI resolve a partir do profile passado em `--profile`. Isto mantém
o bundle portátil cross-tenant (qualquer Free Edition funciona sem
editar YAML).

## Sequência canônica (deploy + run)

```bash
# 1) Schema-validate the bundle offline (no workspace round-trip)
databricks --profile free-edition bundle validate --target user_dev

# 2) Deploy artifacts (wheel + notebooks + SQL + DAB resources)
databricks --profile free-edition bundle deploy --target user_dev

# 3) Run ingestion: TLC parquet → Landing Volume → Bronze → Silver
#    (~5 min na primeira vez; ~3 min em runs incrementais)
databricks --profile free-edition bundle run job_ingestion --target user_dev

# 4) Run modelling: dbt deps + seed (dim_locations) + run (Gold) +
#    test (20 dbt tests)   (~1m30s)
databricks --profile free-edition bundle run job_dbt --target user_dev
```

## O que esperar depois

Após o passo 4:

- **Silver:** `workspace.nyc_taxi_bronze.yellow_taxi_trips` (~16.04 M
  rows pra Jan–Maio 2023).
- **Gold view:** `workspace.nyc_taxi_gold.yellow_taxi_trips_consumption`
  — projeção per-trip filtrada pela janela ativa de ingestão via
  `landing_audit` e enriquecida com borough/zone via `dim_locations`.
- **`dim_locations` seed:** `workspace.nyc_taxi_gold.dim_locations`
  (265 rows da TLC zone lookup).
- **Audit operacional:**
  `workspace.nyc_taxi_monitoring.landing_audit` +
  `workspace.nyc_taxi_monitoring.gold_pipeline_observability` (view
  sobre `event_log(TABLE(<bronze>))` filtrada a `flow_progress`,
  `expectation_metrics`, `pipeline_done`).
- **AI/BI dashboard:** `[user_dev] NYC Yellow Taxi — case answers`,
  queryable do menu Dashboards na UI do workspace.

## Override de janela de ingestão

Por default a janela é `2023-01` → `2023-05`. Pra rodar um mês
específico:

```bash
databricks --profile free-edition bundle run job_ingestion \
  --target user_dev \
  --params start_year_month=2023-03,end_year_month=2023-03
```

A Gold automaticamente refletirá a nova janela no próximo
`bundle run job_dbt` (filtragem via `landing_audit` — ver ADR-0003).

## Validação local sem Databricks

Requer Python 3.12, `uv` e o Databricks CLI com profile `free-edition`.

```bash
# Cria venv + instala package e dev tooling
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

# Roda os mesmos checks do CI (sem round-trip pro Databricks)
ruff check .
mypy src/
pytest ingestion/tests/

# Schema-validate o bundle (sem round-trip pro workspace)
databricks --profile free-edition bundle validate --target user_dev
```

## dbt local (opcional)

Rodar dbt localmente contra o warehouse Free Edition exige exportar
o PAT:

```bash
export DBT_TOKEN=$(databricks --profile free-edition auth token \
  | jq -r .access_token)
cd dbt && dbt build --target user_dev
```

O `dbt/profiles.yml` comitado é **usado apenas** pra esse caminho
CLI — o runtime `dbt_task` do `job_dbt` ignora-o e auto-gera um
profile `databricks_cluster` a partir de `dbt_task.catalog/schema/
warehouse_id` (ver ADR-0010 §Validação empírica).

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) roda **ruff
+ mypy (strict) + pytest com cobertura** em todo push pra `main` e em
todo PR. Deliberadamente **não** roda `databricks bundle validate`:
o CLI sempre chama `/api/2.0/preview/scim/v2/Me` e portanto precisa
de um PAT real do workspace, e Free Edition não suporta service
principal (CONTEXT.md "Não-objetivos"). Validação DAB é parte do
loop local (`bundle validate` acima).
