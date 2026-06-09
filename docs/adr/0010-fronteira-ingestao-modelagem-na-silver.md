# 0010: Fronteira ingestão↔modelagem na Silver canônica

## Status
Accepted

## Context
PLAN.md original (DLT-puro até Gold view) tratava ingestão e
modelagem como um único concern do pipeline, implementadas pela
mesma ferramenta (DLT) num único job. Revisitando isso pelas
lentes do padrão iFood real:

- **`ifp-data-ingestions`** é repo dedicado a ingestão pura
  (DLT + Auto Loader; produz tabelas Bronze/Silver no UC).
- **`pagob2b-dbt`** é repo dedicado a modelagem (dbt; consome
  tabelas Silver via `sources.yml`, produz Gold + dim + análises).
- Os dois nunca se referenciam por job — `pagob2b-dbt` não tem
  `depends_on` apontando pro DLT pipeline do `ifp-data-ingestions`
  em nenhum dos 30+ job YAMLs (verificado factualmente).
- A interface entre os dois é **exclusivamente a tabela Silver no
  Unity Catalog**, declarada via `sources.yml` do dbt.

Esse padrão reflete uma **fronteira de concern**, não uma escolha
de stack:

- **Ingestão** = trazer dados externos pra dentro do lakehouse,
  tipar, dropar lixo via expectations, deixar a tabela canônica
  pronta pra consumo. Time/repo de ingestão é dono dessa fronteira.
- **Modelagem** = projetar colunas relevantes, enriquecer com
  dimensões, agregar pra responder perguntas de negócio. Time/repo
  de modelagem é dono.

Manter os dois concerns num único pipeline DLT-puro perde o sinal
arquitetural que o padrão iFood codifica: **modelagem não conhece
ingestão**; só conhece o contrato de tabela.

## Decision
**Ingestão termina na Silver canônica. Modelagem começa na Silver
via `sources.yml`. A tabela Silver no Unity Catalog é o único
contrato entre os dois lados.**

Concretamente:

1. **Lado ingestão** entrega:
   - Landing notebook (download HTTP → Volume UC).
   - DLT pipeline (Bronze raw + Silver canônica tipada).
   - SQL task pós-DLT (`UPDATE landing_audit SET pipeline_update_id`).
   - Schemas: `${prefix}nyc_taxi_bronze`, `${prefix}nyc_taxi_silver`,
     `${prefix}monitoring`.

2. **Lado modelagem** entrega:
   - `sources.yml` declarando 2 sources: `silver.yellow_taxi_trips`
     (consumida pela Gold) e `monitoring.landing_audit` (consumida
     pelo filtro de janela — ADR-0003).
   - Seed `dim_locations` (ADR-0009 editado).
   - Modelo Gold + análises + dbt tests.
   - Schema: `${prefix}nyc_taxi_gold`.

3. **Invariantes mantidas:**
   - Lado modelagem **não escreve** em schema de ingestão.
   - Lado ingestão **não conhece** existência de Gold/dim/análises.
   - Mudança de contrato (rename de coluna na Silver) é breaking
     change cross-job, documentado no ADR e versionado via PR no
     `sources.yml` (não silenciosamente).

## Notas de implementação
Stack escolhida pra cada lado:

- **Ingestão = DLT + Auto Loader.** Razões:
  - Streaming Table + expectations + event_log nativos cobrem
    bronze/silver com pouco código.
  - `_metadata.file_path` do Auto Loader habilita ADR-0004
    (`file_year_month`) sem custo extra.
  - Padrão `ifp-data-ingestions` na iFood.

- **Modelagem = dbt-databricks.** Razões:
  - `ref()` + `sources.yml` codificam linhagem e contrato.
  - `dbt seed` é caminho idiomático pra dim_locations (ADR-0009).
  - dbt tests complementam expectations DLT em vetor distinto
    (ADR-0007).
  - Padrão `pagob2b-dbt` na iFood.

Alternativas de stack rejeitadas:

- **DLT-puro até Gold view** (plano original): perde sinal do
  padrão iFood (modelagem como concern separado); Gold view DLT
  fica acoplada ao pipeline de ingestão; futuras dim/análises
  exigem refator DLT em vez de adicionar modelo dbt.
- **dbt-puro do Bronze em diante**: perde Auto Loader + expectations
  DLT + event_log; dbt incremental é menos elegante que DLT
  Streaming Table pra ingestão de parquets versionados.
- **Fronteira no Bronze (dbt assume Silver)**: matar DLT na prática
  (Bronze sozinho não justifica DLT); a transformação canônica
  (rename/cast/drop/derive) é trabalho de ingestão por definição.

## Consequences
**Positivas:**
- Espelha padrão iFood real (`ifp-data-ingestions` + `pagob2b-dbt`),
  marca critério "criatividade" sem inventar nada.
- Concerns separados são auditáveis: lendo o `sources.yml` o
  avaliador entende o contrato sem ler código.
- Futura dim (ex.: `dim_vendor`, `dim_payment_type`) entra como
  novo seed/modelo dbt sem tocar em DLT.
- Futura troca de ferramenta de modelagem (dbt → SQLMesh, etc.)
  não exige refator de ingestão.

**Negativas:**
- Avaliador precisa rodar 2 `bundle run` em vez de 1 (mitigado
  por README com runbook explícito + ADR-0011).
- Coordenação de breaking change na Silver exige PR cross-pasta
  no monorepo (mitigado: monorepo torna isso trivial; em produção
  iFood seriam 2 repos com PR cross-repo).
- Adapter dbt-databricks adiciona dependência (mitigado: probe
  empírico validou funcionamento — ver §"Validação empírica").

**Neutras:**
- Schema da Silver não muda; mecânica Auto Loader/DLT não muda.
- Comportamento das 2 perguntas obrigatórias do case idêntico.

## Validação empírica

### Probe A — `dbt-databricks` via CLI local (2026-06-08, pt4 grilling)

| Etapa | Resultado |
|---|---|
| `dbt debug` (Warehouse Free Edition + PAT) | ✅ Connection ok |
| `dbt seed` em `workspace.dbt_probe` | ✅ INSERT 3, 16s |
| `dbt run` (view com `ref(seed)`) | ✅ OK, 2.6s |

`dbt-databricks` 1.12 funciona no workspace alvo via SQL Warehouse
2X-Small + PAT.

### Probe B — `dbt_task` no DAB em serverless Free Edition (2026-06-08, ticket #01)

Risco residual de Probe A (`dbt_task` no DAB) validado empiricamente:

| Etapa | Resultado |
|---|---|
| `databricks bundle validate` (1 job, 1 `dbt_task`, env serverless) | ✅ OK |
| `databricks bundle deploy --target user_dev` | ✅ OK |
| `databricks bundle run job_dbt_probe` (job_id 171245947083102, run_id 1038370540326389) | ✅ TERMINATED SUCCESS em ~2min |
| `dbt deps + seed + run` dentro do task | ✅ PASS=2 ERROR=0 |
| Profile resolution | runtime injeta profile `databricks_cluster` automaticamente quando `dbt_task.catalog/schema/warehouse_id` estão setados |
| Library install | `environments.spec.dependencies: [dbt-databricks>=1.10,<2]` resolveu `dbt-databricks 1.12.0` + `dbt 1.11.8` em serverless client 3 |
| Cold start | ~30s entre task start e primeiro comando dbt; aceitável |

**Opção B validada.** `dbt_task` em DAB serverless Free Edition é
viável. Ticket #10 (`job_dbt` DAB) segue conforme planejado.

**Lições pro projeto real:**
- Não passar `--target` nos `commands` do `dbt_task` — usar o profile
  `databricks_cluster` auto-gerado pelo runtime.
- Não comitar `dbt/profiles.yml` no repo — runtime ignora.
- Omitir `+schema` no `dbt_project.yml` se quiser que `dbt_task.schema`
  vire schema final (sem concat duplo); ou aceitar `<task_schema>_<config_schema>`.
- Declarar `dbt-databricks` como `pypi` em `environments.spec.dependencies`,
  não `libraries:` (libraries é pra clusters tradicionais, não serverless).

## Relação com outros ADRs
- **ADR-0011** (monorepo + 2 jobs DAB independentes) é
  consequência direta deste ADR.
- **ADR-0003** (editado) implementa o lado dbt deste ADR: Gold
  como modelo dbt lendo Silver + audit via `sources.yml`.
- **ADR-0007** (editado) adiciona dbt tests como camada
  complementar habilitada por este ADR.
- **ADR-0009** (editado) realoca `dim_locations` pro lado
  modelagem (seed dbt em schema gold).
