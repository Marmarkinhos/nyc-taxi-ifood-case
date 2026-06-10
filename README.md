# NYC Yellow Taxi: iFood data engineering case

NYC TLC Yellow Taxi · Databricks Free Edition · DAB + DLT + dbt

Sou consultor de DE no iFood há 8 meses. Construir esse case de
ingestão sem utilizar DAB + DLT + dbt seria deixar passar uma
oportunidade de implementar uma stack que eu uso diariamente e venho
me aperfeiçoando. Esse repo tenta simular o que eu considero necessário
em projetos de ETL.

Feito em 2 dias usando spec-driven development com workflow agêntico,
garantindo ADRs, testes e observabilidade.

## Como esse repo foi construído

70 commits em 2 dias, autor único, distribuídos em 15 tickets
versionados em `.scratch/issues/case-implementation/`. Cinco desses
tickets rodaram em paralelo via git worktrees, com agentes
independentes implementando cada vertical slice e a sessão principal
fazendo merge linear (commits `merge: <branch> (#NN)` no log).

Cada decisão load-bearing virou ADR antes de virar código: 17 ADRs
em `docs/adr/`, indexadas em `docs/adr/README.md`, cobrindo storage,
fronteira ingestão↔modelagem, drift de schema TLC, severidade de
expectations e mais. Gotchas operacionais descobertos durante a
implementação (16 fixes documentados) foram acumulados em
[AGENTS.md](AGENTS.md) pra que qualquer agente (humano ou IA)
continue o trabalho a partir daqui.

O ciclo foi spec-driven: PRD em [docs/PLAN.md](docs/PLAN.md) → tickets
como vertical slices → implementação test-first quando aplicável →
ADR quando a decisão divergiu do plano original (caso de
[ADR-0016](docs/adr/0016-passenger-count-warn-em-vez-de-drop.md), que
reverteu uma decisão do PLAN.md). README, CONTEXT.md e RUNBOOK.md são
consequência desse ciclo, não pré-requisito.

## As respostas do case

![Dashboard AI/BI com Q1 (line) e Q2 (bar)](docs/img/01-dashboard.png)

O dashboard é deployado pelo bundle como `[user_dev] NYC Yellow Taxi
case answers` (resource `resources/nyc_taxi_dashboard.lvdash.json`).
Em qualquer Free Edition: `bundle deploy --target user_dev` →
Workspace UI → menu Dashboards → abrir → o print acima é o resultado.

- **Q1, média mensal de `total_amount` (Jan–Mai 2023):** sobe
  monotonicamente de **USD 27.44** em Jan a **USD 29.46** em Mai
  (~7.3 % no window; Maio também é o pico de volume).
  - Cálculo é `AVG(total_amount) GROUP BY mês`, média não-ponderada
    por viagem. O parquet TLC 2023 não traz identidade de táxi
    (campos `medallion`/`hack_license` foram removidos do schema
    pós-2016) e `VendorID` indica o fornecedor TPEP do taxímetro,
    não o táxi (3 valores em 2023: 1, 2, 6). Sem chave de táxi na
    fonte, "média por táxi da frota" não é calculável; "média por
    viagem da frota Yellow" é a leitura defensável.
- **Q2, média de `passenger_count` por hora em Maio 2023:** pico de
  **~1.44** passageiros/trip às **03h** (madrugada / aeroporto),
  mínimo de **~1.24** às **06h** (commute solo). NULLs nativos TLC
  (~2.95 % das rows de Maio) ficam fora do denominador, ver
  [ADR-0016](docs/adr/0016-passenger-count-warn-em-vez-de-drop.md).

EDA bônus (matriz de fluxo borough × borough) vive no notebook
exploratório, ver Print 5 mais abaixo.

## Como cheguei aqui

Ingestão e modelagem dbt rodam em momentos diferentes. Ingestão
quando chega arquivo novo, dbt quando alguém mexe num modelo. Juntar
os dois num job só obriga um a saber da existência do outro.
Separando, o contrato fica só na tabela Silver (via `sources.yml` do
dbt) e cada job evolui sozinho. No iFood o mesmo split vive em
`ifp-data-ingestions` + `pagob2b-dbt` (repos separados); aqui é
monorepo só por UX do avaliador. Detalhe em
[ADR-0010](docs/adr/0010-fronteira-ingestao-modelagem-na-silver.md) +
[ADR-0011](docs/adr/0011-orquestracao-dois-jobs-dab-independentes.md).

**`job_ingestion`:** Landing (Volume UC) → Bronze (Streaming Table
Delta) → Silver (Materialized View canônica). 4 tasks atômicas
(download HTTP, DLT pipeline com 7 expectations warn-only, audit
backfill, monitoring view refresh), ~5 min:

![job_ingestion DAG verde, 4 tasks](docs/img/02-job-ingestion-dag.png)

**`job_dbt`:** Silver → Gold via dbt-databricks. 1 task, ~1m30s:
`dbt deps → seed (dim_locations, 265 zonas) → run (4 Gold views) →
test (20 dbt tests hard-fail)`.

![job_dbt DAG verde + 20 tests passing](docs/img/03-job-dbt-dag.png)

## Stack e por que assim

- **Orquestração:** Databricks Asset Bundles (DAB), 2 jobs com
  schedule pausado (execução manual via `bundle run`).
- **Ingestão:** Lakeflow Declarative Pipelines (DLT) + Auto Loader
  (`cloudFiles.schemaHints` + `addNewColumnsWithTypeWidening`, ADRs
  0014/0015).
- **Storage:** Unity Catalog, Delta tables, Liquid Clustering em
  `pickup_year_month` na Silver.
- **Modelagem:** dbt-databricks, 4 Gold views + 1 seed
  (`dim_locations` da TLC zone lookup).
- **Consumo:** AI/BI (Lakeview) dashboard + notebook `display()` +
  SQL direto (ver "Trio de consumo" abaixo).
- **Observabilidade:** `landing_audit` (gap pré-Bronze) + view
  `gold_pipeline_observability` sobre `event_log(TABLE(bronze))`.

Resultado final, Gold filtrada pela janela ativa de `landing_audit`:

![SELECT COUNT(*) na Gold view retornando ~16M](docs/img/04-gold-count.png)

Pipeline em ASCII:

    TLC parquet ──HTTP──▶ Landing (Volume UC)
                                 │
                                 ▼  Auto Loader (Bronze ST → Silver MV)
                          ┌──────────────┐
                          │ job_ingestion│  4 tasks, ~5min
                          └──────┬───────┘
                                 │
                          Silver (UC table)  ◀── único contrato cross-job
                                 │           (dbt/models/sources.yml)
                                 ▼
                          ┌──────────────┐
                          │   job_dbt    │  1 task, ~1m30s
                          └──────┬───────┘
                                 │
                          Gold (4 views)
                        ┌────────┼─────────┐
                        ▼        ▼         ▼
                     Notebook  Dashboard  SQL ad-hoc

**Por que Free Edition?** É o ambiente que o case (e qualquer
candidato fora do iFood) consegue reproduzir gratuitamente. Custo:
sem service principal (então sem CI deploy, `bundle deploy` requer
PAT de usuário real), serverless-only (sem instance pools, sem
all-purpose clusters), warehouse com cold start ~20s. Cada uma
dessas restrições aparece como decisão consciente nos ADRs (ver
"Limitações" na seção Apêndices ou direto em `docs/adr/`).

## Trio de consumo (cobertura assimétrica)

Três surfaces de leitura sobre o **mesmo** Gold dbt (SSoT). Cobertura
diferente por persona, intencionalmente:

| Surface | Path | Cobertura | Persona |
|---|---|---|---|
| **dbt Gold models** | `dbt/models/gold/*.sql` | Q1 + Q2 + EDA (4 views materializadas) | Engenheiro/SQL: abre o `.sql`, vê a lógica, roda `dbt compile` |
| **Notebook** | `notebooks/answers.py` | Q1 + Q2 + EDA (com heatmap interativo) | Analista: explora `display()`, troca visualização, cross-checa números |
| **AI/BI dashboard** | `resources/nyc_taxi_dashboard.lvdash.json` | Q1 + Q2 apenas | Avaliador/executivo: abre URL, vê as 2 respostas literais do case |

EDA não está no dashboard porque a forma rica dela é heatmap, não
table, e heatmap em Lakeview ficou pior que `display()` no notebook:

![Notebook answers.py com heatmap borough × borough renderizado](docs/img/05-notebook-heatmap.png)

Adicionar uma 4ª surface (Power BI, Streamlit, `/api/2.0/sql/statements`,
…) significa adicionar uma query contra `workspace.nyc_taxi_gold.*`,
não duplicar lógica analítica. SSoT em um lugar só.

## Apêndices

- **[docs/RUNBOOK.md](docs/RUNBOOK.md):** comandos completos de
  deploy/run/troubleshoot pra reproduzir o pipeline numa Free
  Edition limpa.
- **[CONTEXT.md](CONTEXT.md):** vocabulário load-bearing (Landing,
  Bronze, Silver, Gold, Janela de ingestão, Trio de consumo).
- **[docs/adr/](docs/adr/):** 17 ADRs aceitas que sustentam as
  decisões load-bearing (storage, expectations, fronteira ingestão↔
  modelagem, drift TLC, ...).
- **[docs/CASE.md](docs/CASE.md):** enunciado original iFood.
- **[notebooks/answers.py](notebooks/answers.py):** notebook
  exploratório (mesmo conteúdo do Print 5, mas interativo).
- **[docs/notes.md](docs/notes.md):** decisões conscientes sem ADR.

### Limitações Free Edition

Serverless-only (sem instance pools, sem all-purpose clusters); sem
service principal (então sem CI deploy); single MANAGED catalog
(`workspace`); schedules pausados (execução manual via `bundle run`);
warehouse cold start ~20s. Cada uma é justificada nos ADRs ou em
`docs/RUNBOOK.md`.
