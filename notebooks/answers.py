# Databricks notebook source
# MAGIC %md
# MAGIC # NYC Yellow Taxi — case answers
# MAGIC
# MAGIC Notebook de consumo das 3 perguntas do case (Q1 mensal,
# MAGIC Q2 hora-do-dia em Maio, EDA geográfica bônus). Camada de
# MAGIC **exibição apenas** — toda a lógica analítica vive no dbt.
# MAGIC
# MAGIC ## Single source of truth
# MAGIC
# MAGIC Os 3 modelos consumidos aqui são definidos em
# MAGIC [`dbt/models/gold/`](../dbt/models/gold) (materialized views —
# MAGIC ver Resolution do ticket [#11](../.scratch/issues/case-implementation/11-dbt-analyses.md))
# MAGIC materializados em
# MAGIC `${catalog}.${catalog_prefix}nyc_taxi_gold` pelo job_dbt DAB
# MAGIC ([#10](../.scratch/issues/case-implementation/10-job-dbt-dab.md)):
# MAGIC
# MAGIC | Pergunta | Modelo Gold consumido |
# MAGIC | --- | --- |
# MAGIC | Q1: média mensal de `total_amount` | `monthly_avg_total_amount` |
# MAGIC | Q2: média de `passenger_count` por hora em Maio (ADR-0016) | `hourly_avg_passenger_count_may` |
# MAGIC | EDA: matriz borough × borough de fluxos | `eda_geographic` |
# MAGIC
# MAGIC **Este notebook NÃO recalcula** — só lê as tabelas via
# MAGIC `spark.read.table(...)` e renderiza com `display()` (que oferece
# MAGIC a UI de chart embutida da plataforma).
# MAGIC
# MAGIC Os números esperados (validados em 2026-06-09 contra o warehouse
# MAGIC `10ba36a843e45ac1`) estão no Resolution do ticket #11; o
# MAGIC avaliador pode cross-checar este render contra essa tabela.
# MAGIC
# MAGIC Para o consumidor visual paralelo (AI/BI dashboard versionado
# MAGIC via DAB), ver `resources/nyc_taxi_dashboard.lvdash.json`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Resolução do FQN das tabelas Gold
# MAGIC
# MAGIC Catalog + prefixo + schema vêm dos widgets do notebook (DAB
# MAGIC injeta os valores via `base_parameters` do task de leitura;
# MAGIC `resources/general_variables.yml` é a fonte canônica). Defaults
# MAGIC apontam pro `user_dev` da Free Edition para que o notebook rode
# MAGIC standalone na UI sem o job em volta.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "Unity Catalog catalog")
dbutils.widgets.text("catalog_prefix", "", "Optional schema prefix")
dbutils.widgets.text("gold_schema", "nyc_taxi_gold", "dbt-owned Gold schema")

catalog = dbutils.widgets.get("catalog")
catalog_prefix = dbutils.widgets.get("catalog_prefix")
gold_schema = dbutils.widgets.get("gold_schema")

gold_fqn_schema = f"{catalog}.{catalog_prefix}{gold_schema}"


def gold_table(model_name: str) -> str:
    """Build a 3-level FQN for a Gold analytics model.

    Centralised so every read uses the same catalog/prefix/schema
    resolution. Avoids string-concat scatter and keeps the only place
    that has to change if Unity Catalog layout shifts.
    """
    return f"{gold_fqn_schema}.{model_name}"


print(f"Reading Gold analytics from: {gold_fqn_schema}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Q1 — Média mensal de `total_amount`
# MAGIC
# MAGIC Pergunta literal do case: "Qual a média mensal de `total_amount`?".
# MAGIC O modelo dbt `monthly_avg_total_amount` agrega por
# MAGIC `pickup_year_month` (5 linhas, Jan–Mai 2023; ver
# MAGIC [`dbt/models/gold/monthly_avg_total_amount.sql`](../dbt/models/gold/monthly_avg_total_amount.sql)
# MAGIC para a SQL e a justificativa de `COUNT(*)` × `COUNT(total_amount)`).
# MAGIC
# MAGIC **Resultado esperado** (Resolution #11): a média sobe
# MAGIC monotonicamente de Jan (USD 27.44) a Mai (USD 29.46) — ~7.3 %
# MAGIC de crescimento no window, com Maio também sendo o pico de
# MAGIC volume.
# MAGIC
# MAGIC No `display()` abaixo selecione **Visualization → Line chart**,
# MAGIC X = `pickup_year_month`, Y = `avg_total_amount`.

# COMMAND ----------

monthly_df = spark.read.table(gold_table("monthly_avg_total_amount")).orderBy(
    "pickup_year_month"
)
display(monthly_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Q2 — Média de `passenger_count` por hora em Maio
# MAGIC
# MAGIC Pergunta literal do case: "Qual a média de `passenger_count` por
# MAGIC hora do dia, considerando todas as viagens de Maio?". O modelo
# MAGIC dbt `hourly_avg_passenger_count_may` materializa 24 linhas
# MAGIC (horas 0–23) já com o tratamento ADR-0016 aplicado:
# MAGIC
# MAGIC * filtro explícito `passenger_count IS NOT NULL` —
# MAGIC * `COUNT(passenger_count)` (não `COUNT(*)`) no denominador.
# MAGIC
# MAGIC O motivo está em
# MAGIC [`dbt/models/gold/hourly_avg_passenger_count_may.sql`](../dbt/models/gold/hourly_avg_passenger_count_may.sql)
# MAGIC + [ADR-0016](../docs/adr/0016-passenger-count-warn-em-vez-de-drop.md):
# MAGIC ~102K rows de Maio (~2.95 %) têm `passenger_count` NULL nativo
# MAGIC TLC e ficaram na Silver porque dropar a row corromperia as
# MAGIC outras respostas (Q1 e EDA).
# MAGIC
# MAGIC **Resultado esperado** (Resolution #11):
# MAGIC
# MAGIC * pico de média na hora **03** (~1.437 passageiros/trip) —
# MAGIC   madrugada, grupos / aeroporto;
# MAGIC * mínimo de média na hora **06** (~1.235 passageiros/trip) —
# MAGIC   commute matinal solo;
# MAGIC * pico de volume na hora **18** (~242K trips) — rush-hour.
# MAGIC
# MAGIC No `display()` abaixo selecione **Visualization → Bar chart**,
# MAGIC X = `pickup_hour`, Y = `avg_passenger_count`.

# COMMAND ----------

hourly_df = spark.read.table(gold_table("hourly_avg_passenger_count_may")).orderBy(
    "pickup_hour"
)
display(hourly_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## EDA bônus — Fluxo geográfico borough × borough
# MAGIC
# MAGIC EDA criativa (Decisão #8 do plano, eixo "criatividade" do case
# MAGIC + uso da `dim_locations` seed). O modelo dbt `eda_geographic`
# MAGIC retorna 63 combinações `pickup_borough × dropoff_borough` com
# MAGIC `trip_count` e `avg_total_amount`; ver
# MAGIC [`dbt/models/gold/eda_geographic.sql`](../dbt/models/gold/eda_geographic.sql).
# MAGIC
# MAGIC **Resultado esperado** (Resolution #11):
# MAGIC
# MAGIC * **82.5 %** das viagens são intra-Manhattan (13.2M / 16M);
# MAGIC * tarifas médias mais altas em pares com aeroporto: Manhattan→EWR
# MAGIC   (~USD 125, Newark NJ), Queens→Manhattan (~USD 80, JFK/LGA →
# MAGIC   centro);
# MAGIC * ~0.8 % do volume cai em buckets NULL/Unknown — preservados
# MAGIC   propositalmente pela analysis (sinal de EDA), filtrável na
# MAGIC   apresentação.
# MAGIC
# MAGIC No `display()` abaixo selecione **Visualization → Heatmap**,
# MAGIC X = `pickup_borough`, Y = `dropoff_borough`, Color = `trip_count`
# MAGIC (ou Pivot table com `avg_total_amount` se preferir números).

# COMMAND ----------

from pyspark.sql import functions as F

eda_df = spark.read.table(gold_table("eda_geographic")).orderBy(F.col("trip_count").desc())
display(eda_df)
