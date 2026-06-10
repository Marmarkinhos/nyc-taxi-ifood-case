# notebooks/

## O que é

Camada **interativa de exibição** sobre a Gold dbt. Único notebook:

- [`answers.py`](answers.py) — Q1 (média mensal de `total_amount`) +
  Q2 (média de `passenger_count` por hora em Maio) + EDA bônus
  (matriz de fluxo borough × borough, renderizada como heatmap via
  `display()`).

É uma das 3 surfaces do **Trio de consumo** (ver tabela no
[README raiz](../README.md#trio-de-consumo-cobertura-assim%C3%A9trica)).
Persona-alvo: analista que quer interagir, trocar visualização e
cross-checar números.

## O que NÃO está aqui

- **Lógica analítica.** As 4 Gold views (Q1, Q2, EDA, projeção
  consumível) vivem em [`../dbt/models/gold/`](../dbt/models/gold/) —
  SSoT. O notebook só executa `SELECT * FROM <gold_view>` e chama
  `display()`. Mudou o número? Mudou a Gold, não o notebook.
- **Dashboard executivo.** Lakeview AI/BI vive em
  [`../resources/nyc_taxi_dashboard.lvdash.json`](../resources/nyc_taxi_dashboard.lvdash.json),
  cobre só Q1 + Q2 (EDA não rende em Lakeview tão bem quanto no
  `display()` daqui).
- **Pipeline de ingestão.** Tudo em [`../ingestion/`](../ingestion/)
  + [`../resources/`](../resources/).

## Onde olhar a contraparte

- Gold dbt (SSoT da lógica): [`../dbt/models/gold/`](../dbt/models/gold/)
- Dashboard: [`../resources/nyc_taxi_dashboard.lvdash.json`](../resources/nyc_taxi_dashboard.lvdash.json)
- Trio de consumo (cobertura por persona): seção no [README raiz](../README.md#trio-de-consumo-cobertura-assim%C3%A9trica)
