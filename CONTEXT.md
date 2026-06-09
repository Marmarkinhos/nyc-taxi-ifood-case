# CONTEXT — nyc-taxi-case

> Vocabulário e contexto load-bearing do projeto. Skills consultam este arquivo.

## O que é

Pipeline de ingestão da TLC NYC Yellow Taxi (Jan–Maio 2023) implementado
em **monorepo** com **dois jobs DAB independentes**:

1. **`job_ingestion`** — Databricks Asset Bundle + Lakeflow Declarative
   Pipelines (DLT) + Auto Loader: download HTTP → Volume UC → Bronze →
   **Silver canônica**.
2. **`job_dbt`** — dbt-databricks consumindo Silver via `sources.yml`:
   **Gold + `dim_locations` + análises**.

Os dois jobs **não têm `depends_on` entre si**. `sources.yml` é o único
contrato. Espelha o padrão iFood (`ifp-data-ingestions` DLT-puro +
`pagob2b-dbt` dbt-puro). Schedule pausado nos dois; execução manual via
`bundle run`. Rodando em **Databricks Free Edition**.

## Vocabulário load-bearing

- **TLC** — NY Taxi & Limousine Commission (fonte dos parquets)
- **Yellow taxi** — categoria foco do case (não green, fhv, fhvhv)
- **Landing** — Volume UC onde o parquet TLC aterra **byte-a-byte**
  (md5 preservado) sob path Hive-partitioned `year=YYYY/month=MM/`.
  É sistema de arquivos, não tabela UC. O reshape é apenas no path;
  o conteúdo é idêntico ao download da TLC.
- **Landing mode** — `HTTP` (download via `requests.get` da TLC,
  caminho default validado empiricamente em 2026-06-08 com
  STATUS=200 em 0.10s) ou `VOLUME_PREEXISTING` (fallback
  documentado: parquets uploaded manualmente, landing notebook
  apenas valida presença). Probe HEAD de 5s no início de cada
  arquivo decide; resultado registrado no audit.
- **Pipeline DLT** — Lakeflow SDP com bronze + silver (Gold sai do
  DLT; vira modelo dbt — ver "Fronteira DLT↔dbt" abaixo)
- **Fronteira DLT↔dbt** — DLT termina na Silver canônica; dbt começa
  na Gold. dbt consome via `sources.yml` apontando pra
  `${prefix}nyc_taxi_silver.yellow_taxi_trips`. **Os dois lados não
  se conhecem por job** — só pelo contrato da tabela Silver no UC.
  Ver ADR-0010 (a ser criado em pt4).
- **Bronze** — Streaming Table Delta no UC
  (`${prefix}nyc_taxi_bronze.yellow_taxi_trips_raw`), populada pelo
  Auto Loader que lê os parquets da **Landing**. Preserva 100% das
  colunas da fonte (sem rename, sem cast, sem drop) e **adiciona**
  metadata por linha: `_metadata.file_path`,
  `_metadata.file_modification_time`, `_ingestion_ts`. É a primeira
  camada queriável via SQL.
- **Silver** — Materialized View Delta no UC canônica e tipada:
  preserva **todas** as colunas TLC (sem projeção), renomeadas para
  snake_case, tipadas, linhas inválidas dropadas via expectations,
  coluna derivada `pickup_year_month` adicionada. NÃO há agregação.
  Distinção vs Gold: Silver preserva todas as colunas; Gold projeta
  as 5 exigidas + derivadas. Distinção vs Bronze: Bronze é raw +
  metadata sem qualquer transformação; Silver aplica rename/cast/drop.
  Storage otimizado com `delta.autoOptimize.*` + ZSTD nível alto
  pra absorver custo das 14 colunas TLC ignoradas pelo case
  (ADR-0005). Layout físico via **Liquid Clustering** em
  `pickup_year_month` (não partição estática — ADR-0006).
- **Gold** — **modelo dbt** (`dbt/models/gold/yellow_taxi_trips_consumption.sql`)
  com as 5 colunas exigidas pelo case + derivadas (`pickup_year_month`,
  `pickup_hour`) **+ `pickup_borough` e `dropoff_borough`** (join com
  `dim_locations` via `ref('dim_locations')` — ADR-0009 + edit pt4),
  filtrada pela **Janela de ingestão** do último run registrado em
  `landing_audit` (ver ADR-0003). Materializada como view por default;
  pode virar `table` se métricas exigirem.
- **dim_locations** — **seed dbt** (`dbt/seeds/taxi_zone_lookup.csv`)
  materializada via `dbt seed` em `${prefix}nyc_taxi_gold.dim_locations`.
  Tipos forçados via `+column_types` (`location_id: int`) pra casar
  com source Silver no `relationships` test. Resolve
  `PULocationID`/`DOLocationID` em `borough`/`zone` (260 zonas, ~10
  KB). Schema `gold` (não `silver`) por separação de donos: `job_dbt`
  só escreve em `gold` (ADR-0011, pt4). Refresh manual via `dbt seed`
  (parte do `bundle run job_dbt`); TLC atualiza zone lookup ~1x/ano,
  aceitável. Usada pelo enriquecimento da Gold e pelo modelo
  `analyses/eda_geographic.sql`. Ver ADR-0009 (editado).
- **pickup_year_month** — STRING `YYYY-MM` derivada de
  `tpep_pickup_datetime`. **Pode divergir** do mês declarado no arquivo
  TLC (fonte tem ruído: pickups em 2001/2087). Silver preserva o
  ruído via expectation `expect` (#6a); Gold filtra pela janela do run.
- **file_year_month** — STRING `YYYY-MM` derivada de
  `_metadata.file_path` (parse de `yellow_tripdata_YYYY-MM.parquet`).
  Representa o mês **declarado** pelo arquivo TLC. Comparação
  `pickup_year_month = file_year_month` é a expectation #6a — detecta
  pickups fora do mês do arquivo.
- **Janela de ingestão** — par `--start_year_month` +
  `--end_year_month` (inclusivo) que decide **quais arquivos TLC
  processar**. NÃO se confunde com **validade temporal das linhas**
  (essa é o `file_year_month` por linha, verificada pela expectation
  #6a).
- **Free Edition** — Databricks gratuito, serverless-only, sem SP, outbound restrita
- **Audit table** — `${prefix}monitoring.landing_audit`, cobre gap pre-Bronze
- **Self-bootstrap** — princípio do landing notebook (ADR-0012): garante
  todas as suas pré-condições UC via `CREATE SCHEMA IF NOT EXISTS` +
  `CREATE VOLUME IF NOT EXISTS` idempotentes (`_ensure_audit_table` +
  `_ensure_landing_volume` no `main()`). Zero setup HITL num workspace
  fresh — `bundle run` é one-shot.
- **Notebook task exit protocol** — notebook tasks tratam **qualquer**
  `sys.exit(N)` (mesmo `0`) como workload failure. Convenção do projeto:
  SUCCESS/PARTIAL termina naturalmente via `main()` (sem `sys.exit`);
  FAILED faz `raise RuntimeError(error_message)` pra surfar traceback
  no UI. Detalhe em ADR-0012.
- **DAB artifact paths** — duas localizações distintas no workspace
  após `bundle deploy`, fácil de confundir:
  - `${workspace.file_path}/` — source tree (`sync.include`), onde
    notebooks `.py` e SQL files aterram.
  - `${workspace.artifact_path}/.internal/` — `type: whl` / `type: jar`
    artifacts. Wheel do `nyc_taxi_case` vive aqui; `dependencies` nos
    blocos `environments` / `environment` precisam apontar pra cá
    (não pra `file_path/dist/`). ADR-0012.
- **Trio de consumo** — modelos dbt em `dbt/models/analyses/` (SSoT) +
  notebook `answers.py` (orquestra `display()` dos modelos via
  `spark.read.table`) + AI/BI dashboard `.lvdash.json` (referencia
  mesmas tabelas materializadas pelo dbt). **Modelo dbt é single
  source of truth**; notebook e dashboard apenas exibem (ver README
  seção "Camada de consumo").
- **Expectations** — 7 total (6 na Silver + 1 na Bronze); **nenhuma**
  é `expect_or_fail` em Free Edition (blast radius > sinal — ADR-0007).
  Contrato de schema TLC é protegido por `ingestion/tests/test_schema.py`
  (CI) + warn-only na Bronze.
- **dbt tests** — testes idiomáticos dbt rodando no `job_dbt`,
  inventário fixo (ADR-0007 §Decision item 3):
  - `not_null` em 5 colunas exigidas do **source Silver**
    (hard-fail equivalente à #7-bronze, mas pós-Silver).
  - `accepted_values: [1, 2, 6, 7]` em `vendor_id` do source Silver —
    **redundância intencional** com expectation #1 (warn). dbt vira
    o ponto onde valor desconhecido bloqueia propagação pra Gold.
  - `relationships` Gold→`dim_locations` em `pickup_location_id`
    e `dropoff_location_id` (pega LocationID novo sem entrada no seed).
  - `not_null` em `pickup_year_month`, `pickup_borough`,
    `dropoff_borough` da Gold (garante derivações + enriquecimento).

  Complementam (não substituem) as expectations DLT da Silver. Rede
  de segurança em 3 camadas com vetores distintos: pytest CI
  (pré-deploy/código), Bronze warn (runtime/schema TLC), dbt hard
  (runtime/semântica).

## NÃO-objetivos (explícitos)

- NÃO ingerir green/fhv/fhvhv (escopo case = yellow only)
- NÃO fazer deploy via CI (Free Edition não suporta service principal)
- NÃO usar Genie / DuckDB como camada de consumo (decisão consciente)
- NÃO declarar `depends_on` job-level entre `job_ingestion` e
  `job_dbt` — separação de concerns é mantida pelo contrato
  `sources.yml` da Silver, igual produção iFood (ADR-0011, pt4).
- NÃO separar o repo em 2 GitHubs distintos — monorepo escolhido
  por UX do avaliador, com 2 jobs DAB independentes simulando os
  2 repos (ADR-0011, pt4).

## Flagged ambiguities

- "fiel à fonte" foi usado pra descrever Silver — resolvido: termo
  trocado por "canônica e tipada" (ADR-0001). Apenas **Landing** e
  **Bronze** são fiéis à fonte (Landing byte-a-byte; Bronze
  linha-a-linha sem transformação, só adiciona metadata).
- "Landing" e "Bronze" são camadas distintas neste projeto: Landing é
  sistema de arquivos (Volume UC), Bronze é tabela Delta. Auto Loader
  é a ponte entre os dois.
- "janela" foi usado pra dois conceitos distintos — resolvido:
  **Janela de ingestão** = quais arquivos processar (parâmetro do job);
  **validade temporal de linha** = `pickup_year_month` vs
  `file_year_month` (verificada por expectation #6a). Não confundir.

## Decisões load-bearing

Ver `docs/PLAN.md` seção 3 (histórico) e `docs/adr/` 0001–0011
(decisões correntes; ADRs **supersedem** o plano onde divergem).

Mudanças do plano original consolidadas nos ADRs (pt2 + pt4):
- ADR-0005: Silver mantida canônica com ajustes defensivos de quota
- ADR-0006: partição → Liquid Clustering
- ADR-0007: 0 `expect_or_fail`; contrato vai pra teste unitário +
  warn + dbt tests (editado pt4)
- ADR-0008: `landing_audit` ganha `pipeline_update_id`, `months_skipped`,
  `bytes_downloaded` vs `bytes_total_in_volume`, `job_run_id`, `job_url`
- ADR-0009: `dim_locations` como seed dbt em schema gold (editado pt4)

Reorientação arquitetural pt3 materializada em ADRs (pt4):
- **ADR-0010:** fronteira ingestão↔modelagem na Silver canônica.
  Ingestão (DLT + Auto Loader) termina na Silver; modelagem (dbt)
  começa na Silver via `sources.yml`.
- **ADR-0011:** orquestração via 2 jobs DAB independentes
  (`job_ingestion` + `job_dbt`), sem `depends_on` cross-job.
  Contrato implícito via `sources.yml`. Monorepo é decisão de UX
  do avaliador (nota README), não decisão arquitetural.

Aprendizado operacional pós-primeiro run end-to-end (pt5):
- **ADR-0012:** landing notebook é self-bootstrap (cria seu schema +
  Volume idempotentes; respeita exit protocol do notebook task;
  `dependencies` da env apontam pra `${workspace.artifact_path}/.internal/`
  e não pra `${workspace.file_path}/dist/`). Consolida Fixes #2-#5
  do ticket #06.

Recovery de drift TLC (sessão pós-Fix #9):
- **ADR-0013:** `delta.feature.timestampNtz` em Bronze e Silver
  (TLC ship TIMESTAMP_NTZ; Free Edition Delta não habilita default).
- **ADR-0014:** Bronze `cloudFiles.schemaHints` + `readerCaseSensitive=false`
  pra fixar `Airport_fee`/`airport_fee` case rename TLC (Fix #7 + #8).
  **Superseded em parte por ADR-0015.**
- **ADR-0015:** Bronze `addNewColumnsWithTypeWidening` + Silver
  `_rescued_data` recovery via `coalesce(typed, get_json_object(...))`
  pra `passenger_count`/`RatecodeID` (type drift DOUBLE↔INT64 sem path
  de widening). Silver 2.97M → 15.62M rows (Fix #9).
