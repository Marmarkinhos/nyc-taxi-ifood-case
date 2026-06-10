# NYC Taxi Case (iFood) — Plano de execução

> 📜 **HISTÓRICO** — plano original pré-implementação. As decisões
> correntes vivem em [`docs/adr/`](adr/). ADRs supersedem este
> documento onde divergem (ex: ADR-0016 reverteu a decisão de
> dropar `passenger_count` fora do range; ADRs 0013–0015 evoluíram
> a estratégia de drift de schema TLC). Mantido para referência
> arqueológica do approach spec-driven.

> Plano gerado em sessão Architect (Kilo) replicando práticas do
> `ifp-data-ingestions` (escopo growth) num repo público no GitHub pessoal
> rodando em **Databricks Free Edition**.
>
> Case original: ver `.scratch/ifood-case.md` no mesmo diretório.
> Decisões load-bearing tomadas em ordem; cada uma justificada no README final.

---

## 1. Objetivo

Entregar o case técnico iFood (ingestão NYC Yellow Taxi Jan–Maio 2023 + 2
análises SQL) num repo novo, espelhando o padrão arquitetural do
`ifp-data-ingestions` (DAB + DLT + Auto Loader + landing notebook), com foco
em **observabilidade, escalabilidade e parametrização de janela temporal**.

Critérios de avaliação iFood (alinhados às decisões):

- Qualidade e organização do código → CI (ruff + mypy + bundle validate + pytest).
- Processo de análise exploratória → `analysis/01_eda.sql` + EDA usando event_log.
- Justificativa das escolhas técnicas → README documenta as 10 decisões abaixo.
- Criatividade na solução proposta → AI/BI dashboard versionado via DAB + audit table custom.
- Clareza na comunicação dos resultados → trio SQL + notebook + dashboard.

---

## 2. Arquitetura

```
TLC CloudFront (https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_YYYY-MM.parquet)
        |  landing notebook (spark_python_task)
        |  --start_year_month YYYY-MM  --end_year_month YYYY-MM
        v
Volume UC:
  /Volumes/<catalog>/raw_data/landing/nyc_taxi/yellow/year=YYYY/month=MM/yellow_tripdata_YYYY-MM.parquet
        |  Auto Loader (cloudFiles, trigger=AvailableNow, schemaEvolutionMode=addNewColumns)
        v
${prefix}nyc_taxi_bronze.yellow_taxi_trips_raw
  (streaming table — todas as colunas raw + _metadata.file_path + _metadata.file_modification_time + _ingestion_ts)
        |  @dlt.table (MV) + 7 expectations
        v
${prefix}nyc_taxi_silver.yellow_taxi_trips
  (materialized view — fiel à fonte, snake_case, tipada, PARTITIONED BY pickup_year_month)
        |  CREATE VIEW (dentro do mesmo pipeline DLT)
        v
${prefix}nyc_taxi_gold.yellow_taxi_trips_consumption
  (view — 5 colunas exigidas + pickup_year_month + pickup_hour)
        |
        +--> analysis/*.sql            (SQL Editor + SQL Warehouse 2X-Small)
        +--> analysis/answers.py       (notebook Databricks: display + matplotlib)
        +--> resources/nyc_taxi_dashboard.lvdash.json   (AI/BI dashboard via DAB)

Observabilidade (paralelo, fora do DLT):
  ${prefix}monitoring.landing_audit
    — escrita pelo landing notebook (1 linha por run; cobre o "pre-Bronze")
  ${prefix}monitoring.gold_pipeline_observability
    — view sobre event_log("<pipeline_id>"); SQL task pós-DLT no mesmo job
```

---

## 3. Decisões load-bearing (10)

| # | Decisão | Escolha | Justificativa-chave |
|---|---|---|---|
| 1 | Plataforma | **Databricks Free Edition** | Único caminho gratuito que suporta DAB + DLT + UC + Volumes; mantém honestidade com práticas iFood (Community Edition forçaria abandonar metade do stack). |
| 2 | Padrão de landing | **Notebook DLT-less (`spark_python_task`) → Volume UC** | Espelha growth (twilio/langfuse/oppy/blip). Separação de concerns; re-execução barata; landing audit limpa; alimenta Auto Loader. |
| 3 | Parametrização de janela | **`--start_year_month` + `--end_year_month`**, default = último mês fechado | Espelha Twilio (`--start_date/--end_date`). Cobre single (`start=end`), range, full load (`2009-01..now`) sem branches. Idempotente. |
| 4 | Leitura da Bronze | **Auto Loader (`cloudFiles`) + `trigger=AvailableNow`** | Padrão growth literal. Schema evolution grátis (`addNewColumns`). Escala pra full load. Re-run sem reprocessamento. Métricas via event_log. |
| 5 | Modelagem da Silver | **Fiel à fonte (todas as cols tipadas) + Gold view com as 5 exigidas** | Demonstra Medallion real. "podem ser ignoradas" ≠ "devem". Gold view absorve a especificidade do consumer; Silver reutilizável. |
| 6 | Particionamento Silver | **`PARTITIONED BY pickup_year_month`** (derivada de `tpep_pickup_datetime`) | Alinha 1:1 com grão da fonte. Pruning ótimo nas 2 perguntas. ~17M linhas/partição = sweet spot Delta. Sobrevive ao full load (~200 partições). |
| 7 | Expectations DLT | **7 regras: 4 `expect_or_drop`, 2 `expect`, 1 `expect_or_fail`** | Mix realista (sanitiza / observa / protege contrato). Material direto pra EDA via event_log. |
| 8 | Camada de consumo | **Trio: `.sql` + notebook + AI/BI dashboard (DAB)** | Cobre SQL-first, notebook-first e visual-first ao mesmo tempo. Custo marginal baixo. Dashboard versionado = "infra como código até a ponta". Genie e DuckDB descartados conscientemente (documentados no README). |
| 9 | Observabilidade | **event_log nativo + `landing_audit` table custom** | event_log começa na Bronze (não vê download HTTP). Audit fecha o gap pre-Bronze. ~20 linhas no landing notebook + 1 view SQL. |
| 10 | CI no GitHub | **ruff + mypy + `databricks bundle validate` + pytest (helpers puros)** | Espelha `.gitlab-ci.yml` do iFood (sem deploy — Free Edition não suporta service principal). Pytest cobre `window`, `tlc_urls`, `schema` (funções puras, ~20 testes, 100% coverage do que importa). |

### Detalhamento das 7 expectations (decisão #7)

Aplicadas na Silver, materializam-se em `event_log` (`expectation_metrics`):

| # | Regra | Coluna(s) | Severidade | Razão |
|---|---|---|---|---|
| 1 | `vendor_id IN (1, 2, 6, 7)` | `vendor_id` | `expect` | Dicionário TLC. Warning observa drift sem dropar. |
| 2 | `passenger_count BETWEEN 0 AND 9` | `passenger_count` | `expect_or_drop` | Pergunta 2 = média; lixo enviesa. |
| 3 | `total_amount >= 0` | `total_amount` | `expect_or_drop` | Pergunta 1 = média; refunds/negativos enviesam. |
| 4 | `tpep_pickup_datetime IS NOT NULL AND tpep_dropoff_datetime IS NOT NULL` | timestamps | `expect_or_drop` | Sem pickup → sem partição válida. |
| 5 | `tpep_dropoff_datetime >= tpep_pickup_datetime` | timestamps | `expect_or_drop` | Corrupção; dropa. |
| 6 | `pickup_year_month BETWEEN start_param AND end_param` | derivada | `expect` | Detecta linhas com pickup fora da janela (TLC tem ruído real: pickup em 2001/2087). Observa, não dropa — honestidade sobre lixo da fonte. |
| 7 | Contrato: 5 colunas exigidas presentes | nível tabela | `expect_or_fail` | Único `fail` justificado; protege contrato com o avaliador. |

### Schema de `monitoring.landing_audit` (decisão #9)

```
run_id              STRING       -- databricks job run id
job_start_ts        TIMESTAMP
job_end_ts          TIMESTAMP
start_year_month    STRING       -- argumento recebido
end_year_month      STRING
months_requested    ARRAY<STRING>
months_downloaded   ARRAY<STRING>
months_failed       ARRAY<STRING>
total_bytes         BIGINT
status              STRING       -- SUCCESS | PARTIAL | FAILED
error_message       STRING
```

---

## 4. Polimentos

**A) Naming:** padrão multi-target iFood replicado.

- 1 catalog (default Free Edition: `workspace`, parametrizado em `general_variables.yml`).
- Schemas: `${schema_prefix}nyc_taxi_bronze`, `${schema_prefix}nyc_taxi_silver`, `${schema_prefix}nyc_taxi_gold`, `${schema_prefix}monitoring`.
- `schema_prefix` por target: `user_dev` → `dev_<short_name>_`; `dev` → `dev_`; `prod` → `""`.

**B) Path deste plano:** `.scratch/nyc-taxi-case-ifood-plan.md` (lado do `ifood-case.md`).

---

## 5. Estrutura proposta do repo novo

```
nyc-taxi-ifood-case/
├── .github/workflows/ci.yml
├── .pre-commit-config.yaml
├── databricks.yml                      # bundle + 3 targets (user_dev, dev, prod)
├── resources/
│   ├── general_variables.yml           # catalog, schema_prefix, tags
│   ├── nyc_taxi_landing_job.yml        # job mensal (spark_python_task) + SQL task observability
│   ├── nyc_taxi_dlt_pipeline.yml       # pipeline DLT (bronze + silver + gold view)
│   └── nyc_taxi_dashboard.lvdash.json  # AI/BI dashboard versionado
├── src/
│   └── nyc_taxi_case/                  # package Python (wheel artifact do DAB)
│       ├── __init__.py
│       ├── window.py                   # parse/validate de --start_year_month / --end_year_month
│       ├── tlc_urls.py                 # builder URLs TLC + paths Volume
│       └── schema.py                   # snakefy_columns + tipagem
├── notebooks/
│   ├── landing/nyc_taxi_yellow_landing.py        # downloader → Volume + audit insert
│   ├── bronze/nyc_taxi_yellow_bronze.py          # @dlt.table streaming, Auto Loader
│   ├── silver/nyc_taxi_yellow_silver.py          # @dlt.table MV, 7 expectations, partição
│   ├── gold/nyc_taxi_yellow_gold.py              # @dlt.view consumption (5 cols + derivadas)
│   └── monitoring/gold_pipeline_observability.sql # SQL task pós-DLT
├── analysis/
│   ├── 01_eda.sql                                # exploratória (nulls, distros, drop rate)
│   ├── 02_question_1_avg_total_by_month.sql      # P1: avg(total_amount) GROUP BY pickup_year_month
│   ├── 03_question_2_avg_passengers_by_hour_may.sql  # P2: avg(passenger_count) GROUP BY hour, filter=2023-05
│   └── answers.py                                # notebook: display() dos 3 + 1 bar chart matplotlib
├── tests/
│   ├── test_window.py                  # bordas: --start 2023-13, start > end, default = last closed month
│   ├── test_tlc_urls.py                # builder estável; renomear pega no CI
│   └── test_schema.py                  # snakefy_columns
├── pyproject.toml                      # uv + ruff + mypy + pytest
├── uv.lock
├── README.md                           # justificativas + runbook + screenshots
└── requirements.txt                    # exigido pelo case (espelha pyproject)
```

---

## 6. Checklist de execução (ordem)

1. Setup Free Edition + criar Volume `/Volumes/workspace/default/raw_data/landing/nyc_taxi/yellow/`.
2. Scaffold do repo + `databricks.yml` (3 targets) + `general_variables.yml` (catalog, schema_prefix, tags `service-name`/`owner-layer-slug`/`data-domain-layer-slug`/`environment`).
3. Helpers puros em `src/nyc_taxi_case/` + testes pytest (TDD aqui faz sentido — funções puras, retorno determinístico).
4. Landing notebook (`notebooks/landing/...py`) + `monitoring.landing_audit` (CREATE TABLE IF NOT EXISTS na primeira execução) + YAML do job (1 task `spark_python_task` + parameters opcionais).
5. Bronze notebook (`@dlt.table` streaming, Auto Loader `cloudFiles` lendo do Volume) + YAML do pipeline DLT.
6. Silver notebook (`@dlt.table` MV, 7 expectations, `partition_cols=["pickup_year_month"]`) — anexada ao mesmo pipeline.
7. Gold view (`@dlt.view`) com 5 colunas exigidas + `pickup_year_month` + `pickup_hour` — anexada ao mesmo pipeline.
8. SQL task pós-DLT (`notebooks/monitoring/gold_pipeline_observability.sql`) anexada ao job principal com `depends_on` do DLT, escrevendo a view de observability lendo de `event_log("<pipeline_id>")`.
9. `analysis/*.sql` (3 arquivos) + `analysis/answers.py` (notebook orquestrador) + `resources/nyc_taxi_dashboard.lvdash.json` (2 widgets: avg total_amount/mês, avg passengers/hora maio).
10. `.github/workflows/ci.yml` (4 jobs paralelos: lint, typecheck, test, validate) + `.pre-commit-config.yaml` (ruff + mypy + bundle validate offline).
11. README com:
    - Diagrama de arquitetura (mesmo da seção 2).
    - Justificativa de cada uma das 10 decisões (1 parágrafo cada — referenciar esta sessão).
    - Runbook: 4 comandos (`bundle deploy` / `bundle run landing` / `bundle run dlt` / abrir `answers.py`).
    - Screenshots: DLT graph, event_log, dashboard renderizado.
    - Seção "Próximos passos" listando o que ficou fora de escopo.
    - Badge de CI verde no topo.
12. Validação manual end-to-end no Free Edition (ver caveat outbound na seção 7) + `git push`.

---

## 7. Caveats operacionais

### Outbound restrita do Free Edition

Free Edition restringe outbound do compute a "trusted domains". `d37ci6vzurychx.cloudfront.net` (CDN da TLC) **provavelmente não está na lista**.

- **Plano A**: testa `requests.get(url)` no landing notebook diretamente — se funcionar, segue.
- **Plano B (documentar no README, sempre)**: avaliador baixa os 5 parquets localmente (curl/wget) e faz upload via UI no Volume `/Volumes/.../landing/nyc_taxi/yellow/year=2023/month=MM/`. **Pipeline DLT continua idêntico** — Auto Loader não distingue origem do arquivo. README documenta ambos os caminhos como "produção real seria S3 + Auto Loader nativo; case usa Volume + download manual quando outbound bloqueada".

### Limites de quota Free Edition (atuais — verificar antes de demo)

- 1 SQL Warehouse 2X-Small (suficiente pra 85M linhas com partição).
- 1 pipeline DLT ativa por tipo (suficiente — só temos 1).
- 5 task jobs concorrentes (suficiente).
- Sem service principal → CI **não pode** fazer deploy automatizado (decisão #10 já endereçou).
- Compute serverless apenas (sem cluster custom — o DAB ignora `pipeline_cluster_config` e usa serverless por default em Free Edition).

### Adaptação do `general_variables.yml` (vs iFood original)

- Remover: `policy_id`, `instance_profile_arn`, `pipeline_cluster_config*` (Free Edition é serverless-only).
- Manter: `catalog`, `schema_prefix`, `project_custom_tags`, `gov_table_property_*`, `timeout_seconds`.
- Adicionar: `tlc_base_url` (CloudFront), `landing_volume_path` (base path), `sql_warehouse_id` (pro dashboard apontar).

---

## 8. Fora de escopo (registrar no README como "Próximos passos")

- Deploy automatizado via OIDC + service principal (incompatível Free Edition).
- Lakehouse Monitoring nativo na Silver (consumo agressivo de quota Free).
- SQL alerts + webhook Slack (sem destino real em Free Edition).
- Genie Space (consciente: case pede SQL determinístico autoral).
- DuckDB como camada de consumo (consciente: preferi coesão UC; documentar como alternativa pra ambiente sem Databricks).
- Liquid Clustering como alternativa ao particionamento (mencionar como "futuro" — feature mais nova, ganha ponto sem custo).
- Green / FHV / FHVHV datasets da TLC (escopo do case = yellow only).
- Tabela `dim_locations` (PULocationID/DOLocationID enriquecidos com `taxi_zone_lookup.csv`) — útil pra análises de borough, fora do escopo case.

---

## 9. Próximo passo

Plano concluído em modo Architect. **Implementação requer mudar pra um modo
com permissão de escrita** (Code) — este modo só escreve arquivos de plano.

Quando retomar, executar o checklist da seção 6 na ordem, no repo novo
(GitHub pessoal), criando o scaffold do zero (não fork do `ifp-data-ingestions`).
