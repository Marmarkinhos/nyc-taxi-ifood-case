# ingestion/sql/

## O que é

Headers de 6 linhas no topo de cada `.sql` deste diretório explicitam
contexto completo (File / Task / Runs after-before / Reads from /
Writes to / Why). Abrir o arquivo já responde "o que faz e onde
encaixa" sem precisar abrir o YAML de orquestração.

Dois arquivos SQL executados como tasks do `job_ingestion` DAB
(declarados em [`../../resources/job_ingestion.yml`](../../resources/job_ingestion.yml)):

- [`update_landing_audit.sql`](update_landing_audit.sql) — preenche
  `pipeline_update_id` na tabela `landing_audit` consultando
  `event_log(TABLE(<bronze_fqn>))` (ADR-0008).
- [`create_monitoring_view.sql`](create_monitoring_view.sql) — cria
  ou atualiza `gold_pipeline_observability`, view de saúde do
  pipeline sobre o event log do DLT.

Ambos rodam no SQL Warehouse serverless (`var.sql_warehouse_id` no
DAB).

## O que NÃO está aqui

- **Lógica analítica (Gold).** Vive em
  [`../../dbt/models/gold/`](../../dbt/models/gold/). Esses SQLs aqui
  são puramente de **operações do pipeline** (audit + monitoring),
  não respostas do case.
- **Definição de Bronze/Silver.** Vive em
  [`../dlt_pipeline.py`](../dlt_pipeline.py) (DLT declarativo).
- **Orquestração** (warehouse_id, ordem das tasks, retries). Vive em
  [`../../resources/job_ingestion.yml`](../../resources/job_ingestion.yml).

## Onde olhar a contraparte

- Job DAG: [`../../resources/job_ingestion.yml`](../../resources/job_ingestion.yml)
- Bronze/Silver definição: [`../dlt_pipeline.py`](../dlt_pipeline.py)
- Audit schema + builders: [`../../src/nyc_taxi_case/audit.py`](../../src/nyc_taxi_case/audit.py)
- Decisões: ADR-0008 (audit reconstrutibilidade), ADR-0012 (bootstrap).
