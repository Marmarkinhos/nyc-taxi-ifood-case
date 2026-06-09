# AGENTS.md — nyc-taxi-case

Repositório do case técnico de Data Engineering: pipeline NYC Yellow Taxi
em Databricks Free Edition. **Monorepo com 2 jobs DAB independentes**:

- `job_ingestion` — DAB + DLT + Auto Loader (landing → bronze → silver).
- `job_dbt` — dbt-databricks (gold + dim_locations + análises),
  consumindo silver via `sources.yml`.

Schedule pausado nos dois; execução manual via `bundle run`. Sem
`depends_on` entre os jobs. Espelha padrões iFood: `ifp-data-ingestions`
(DLT-puro) + `pagob2b-dbt` (dbt-puro).

## Agent skills

### Issue tracker

Local markdown sob `.scratch/issues/<feature-slug>/` (sem GitHub Issues —
case solo). Ver `docs/agents/issue-tracker.md`.

### Triage labels

Vocabulário canônico (`needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`) declarado no frontmatter YAML de cada
`.md` em `.scratch/issues/`. Ver `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` na raiz + `docs/adr/` pra decisões
arquiteturais. Ver `docs/agents/domain.md`.

## Skills relevantes

- `setup-matt-pocock-skills` — já rodou; reexecutar só se mudar issue tracker
- `grill-with-docs` — refinar plano contra CONTEXT/ADRs
- `to-prd`, `to-issues`, `triage` — workflow de tickets locais
- `tdd` — pros helpers puros em `src/nyc_taxi_case/`
- `diagnose` — quando algo quebrar no Databricks
- `databricks-cli-debugging` — operação CLI Free Edition
- `commit-messages` — Conventional Commits

## Gotchas operacionais (Free Edition + DAB + serverless)

Acumulado dos primeiros runs end-to-end. Antes de "diagnosticar" algo
que se parece com um destes, confirme se já não é um deles.

- **DAB wheel artifact path** — `bundle deploy` sobe `type: whl`
  artifacts pra `${workspace.artifact_path}/.internal/<wheel>.whl`,
  NÃO pra `${workspace.file_path}/dist/`. `environments.spec.dependencies`
  (job) e `environment.dependencies` (Lakeflow pipeline) precisam
  apontar pro primeiro. Sintoma do mismatch:
  `Library installation failed ... ERROR_NO_SUCH_FILE_OR_DIRECTORY`
  apontando pra `files/dist/`. Ver ADR-0012.
- **`sys.exit` em notebook task = task FAILED** — mesmo `sys.exit(0)`.
  Notebook tasks esperam terminação natural via cell completion ou
  `dbutils.notebook.exit()`. Convenção do projeto: SUCCESS/PARTIAL
  cai fora do `if __name__` sem `sys.exit`; FAILED faz
  `raise RuntimeError(...)` pra surfar traceback. Ver ADR-0012.
- **Spark Connect (serverless) recusa schema inference em coluna
  fully-NULL** — `createDataFrame([row])` levanta
  `PySparkValueError: [CANNOT_DETERMINE_TYPE]` se qualquer coluna for
  `None` em **todas** as rows da batch. Workaround: passar `schema=`
  explícito (`StructType`). Caso real: `landing._write_audit_row`
  com `pipeline_update_id=None`.
- **Schema/Volume UC precisam existir antes do IO** — `os.makedirs`
  contra `/Volumes/<cat>/<schema>/<vol>/...` em schema/volume
  inexistente levanta `FileNotFoundError` opaco. Landing notebook
  resolve isso com `_ensure_landing_volume` no `main()` (ADR-0012).
  Outros notebooks futuros: seguir o mesmo pattern (`_ensure_*`
  idempotente no início).
- **`event_log("<id>")` espera pipeline_id, NÃO update_id** — query
  do `update_landing_audit.sql` usa
  `event_log(TABLE(<bronze_fqn>))` justamente pra sobreviver a
  delete+recreate do pipeline. Se for olhar errors de um update
  específico, use `/api/2.0/pipelines/<pipeline_id>/events`
  (REST), não `event_log("<update_id>")` (SQLSTATE 42K03).
- **`databricks --profile <p>` CLI ≠ Databricks SDK SQL** — não tem
  subcomando `sql` nem `statement-execution`. Pra rodar SQL ad-hoc,
  use `api post /api/2.0/sql/statements`. Warehouses serverless
  estão STOPPED por default — primeira query leva ~20s de cold start.
- **Free Edition Delta default não tem `timestampNtz`** — Auto Loader
  infere TIMESTAMP_NTZ pros campos `tpep_*_datetime` da TLC, mas
  Delta default rejeita com `DELTA_FEATURES_REQUIRE_MANUAL_ENABLEMENT`.
  Resolvido por **ADR-0013**: `table_properties={"delta.feature.
  timestampNtz": "supported"}` no `@dlt.table` da Bronze (e Silver,
  defensive). H1 (cast/schemaHints na Bronze) rejeitada por violar
  ADR-0001. Padrão reusável pra qualquer feature Delta que Free
  Edition não habilite por default e a fonte requeira.
- **TLC renomeia campos silenciosamente** (case mismatch causa mass
  rescue) — TLC trocou `airport_fee` (jan/2023) por `Airport_fee`
  (fev-mai/2023). Spark default `caseSensitive=false` + parquet
  vectorized reader = quando o reader vê case-different no schema
  cacheado, ele despeja o **row group inteiro** no `_rescued_data`,
  incluindo colunas que não tinham mismatch. Sintoma: 81.5 % drop
  na Silver via expectation `BETWEEN 0 AND 9` (passa por NULL).
  Resolvido por **ADR-0014**: `cloudFiles.schemaHints` anchorando
  nome+tipo source-side pros 19 campos TLC, gerado programaticamente
  por `tlc_schema.bronze_schema_hints()`. Expectation warn-only
  `bronze_no_rescued_data` cobre drift residual. Step extra: precisa
  `--full-refresh` no pipeline pra invalidar schema cacheado. Gaps
  reconhecidos (drift estrutural, métricas) → ticket #14.
- **`cloudFiles.schemaHints` anchora nome, NÃO faz merge de
  case-different** (Fix #8 / ADR-0014 follow-up correction) — hints
  fazem o reader **escolher** o nome canônico que queremos
  (`airport_fee`), mas se o parquet ship `Airport_fee`, o reader
  ainda dumpa esse field no `_rescued_data` mesmo com match
  case-insensitive. Docs Databricks explicam o comportamento e o
  fix em [Schema inference and evolution §Change case-sensitive
  behavior](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/schema#change-case-sensitive-behavior):
  precisa **adicionalmente** setar `.option("readerCaseSensitive",
  "false")`. ATENÇÃO: option key é **format-specific**
  (DataFrameReader Parquet/JSON/CSV/Avro/XML), NÃO `cloudFiles.*`
  namespace — a forma `cloudFiles.readerCaseSensitive` quebra com
  `CF_UNKNOWN_OPTION_KEYS_ERROR`. Sintoma sem o flag: hints
  aplicados (Bronze schema com `airport_fee` lowercase), mas
  `_rescued_data` 100 % populado em todos os meses que ship
  `Airport_fee` CamelCase. Investigação completa em ADR-0014
  §"Follow-up correction".
- **`or_drop` é decisão de severidade, NÃO de "qualidade pura"** (Fix
  #10 / ADR-0016) — drop fazia sentido quando a regra capturava
  corrupção real (refunds em métrica de receita, timestamps NULL).
  Não fazia pra `passenger_count BETWEEN 0 AND 9`: 428K rows tinham
  `passenger_count` NULL nativo TLC (driver entry omission, ~2.6% do
  dataset, não recuperáveis nem via `_rescued_data` porque o JSON
  também está vazio nessas rows). Dropar a row inteira destruía
  fare/distance/location válidos pras outras perguntas do case (Q1,
  Q3, Q4). Critério reusável: **drop só quando manter a row corromperia
  uma resposta**; warn quando o problema é ortogonal às outras colunas.
  Query de validação que prova "não recuperável" (NULL na col E no JSON):
  `SUM(CASE WHEN passenger_count IS NULL AND (get_json_object(_rescued_data, '$.passenger_count') IS NULL OR get_json_object(_rescued_data, '$.passenger_count') = 'null') THEN 1 ELSE 0 END)`.
  Pattern de armadilha em diagnose: ao investigar drops de
  expectation que casa com `_rescued_data` populado, **sempre** rode
  essa query antes de assumir "tem bug no coalesce" — pode ser NULL
  nativo da fonte.
- **`cloudFiles.schemaHints` DESABILITA type widening na coluna
  hinted; LONG↔DOUBLE não é widening em nenhum lugar** (Fix #9 /
  ADR-0015) — hipótese original do ADR-0014 ("rescue feb-mai é tudo
  case-mismatch") estava errada. Diff de schema pyarrow nos 5 parquets
  TLC 2023 mostrou que TLC mudou os TIPOS FÍSICOS de 6 colunas entre
  jan e fev: `VendorID/PULocationID/DOLocationID` INT64→INT32,
  `passenger_count/RatecodeID` DOUBLE→INT64, `airport_fee`→`Airport_fee`.
  Hints estavam pinando o tipo de jan, daí rescue feb-mai. Fix: trocar
  evolution mode pra `addNewColumnsWithTypeWidening`, adicionar
  `delta.enableTypeWidening: "true"` no `table_properties`, **remover
  os 5 cols type-drifting do hint map** (resolvem via widening
  automático no reader). Catch operacional: a tabela
  [Auto Loader type widening — Supported type changes](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/type-widening#supported-type-changes)
  lista `long → decimal` (não `long → double`) e `double` nem
  aparece como source. Então `passenger_count`/`RatecodeID`
  (DOUBLE jan ↔ INT64 feb-mai) **não tem path de widening em direção
  nenhuma**. Pattern: para colunas que rescuam sem path de widening,
  recuperar na Silver via `F.coalesce(typed_col, F.get_json_object(
  F.col("_rescued_data"), "$.<source>").cast(canonical_type))`.
  Mantém ADR-0001 (Bronze permanece com rescue registrado) e ADR-0010
  (recovery acontece na camada de modelagem). Diff de schema TLC
  cross-month é passo OBRIGATÓRIO antes de qualquer hipótese sobre
  rescue mass.

## Contexto rápido

- Plano completo: `docs/PLAN.md`
- Enunciado original do case: `docs/CASE.md`
- Decisões emergentes: `docs/adr/`
- Vocabulário load-bearing: `CONTEXT.md`
- Histórico de fixes operacionais: `.scratch/issues/case-implementation/06-job-ingestion-dab.md`
  (Resolution + Fix #1-#5)

## Worktree agents (Agent Manager spawned sessions)

Quando um agente é spawned via Agent Manager num worktree
(`.kilo/worktrees/<branch>/`), ele lê este `AGENTS.md` ao iniciar.
Esta seção formaliza o contrato com esses agentes pra evitar
retrabalho na sessão principal ao fazer merge.

### Closeout obrigatório (antes de reportar "done")

A regra global "não comite sem pedido explícito do user" vale pra
**push** e pra **branches já mergeadas em main**. Dentro de um
worktree próprio, criado pra um ticket específico, o agente **deve**
comitar atomicamente antes de reportar conclusão. Sem isso, a sessão
principal não consegue dar Apply / merge limpo.

Sequência obrigatória ao terminar a implementação:

1. Rodar gates locais: `uv run ruff check .` e `uv run --extra dev
   pytest -q` (ou `uv run --with pytest pytest -q` se o `--extra dev`
   não estiver disponível no env do worktree).
2. Marcar o ticket como `done` com Resolution detalhada (incluir
   números, output, ou comandos que provem os acceptance criteria).
3. **Sincronizar o `.md` do ticket no worktree** — `.scratch/` no
   worktree (`.kilo/worktrees/<branch>/.scratch/...`) é arquivo
   **distinto** de `.scratch/` na main repo. Se a edição foi feita
   no path da main por engano, `cp` o conteúdo pro path do worktree
   antes de `git add`.
4. Comitar atomicamente seguindo conventional commits:
   - 1 commit pra implementação (`feat(scope)` / `fix(scope)` /
     `test(scope)` lowercase + body com why, wrap 72)
   - 1 commit separado pro closeout do ticket
     (`docs(issues): close ticket #NN (<short>)`)
   - separar concerns: implementação ≠ documentação
5. **NÃO** fazer `git push` (continua sendo manual do user).
6. **NÃO** mexer em `.scratch/issues/case-implementation/README.md`
   — a sessão principal consolida status dos múltiplos worktrees
   de uma vez após o merge, pra evitar 3-way conflicts triviais.

### O que reportar no final

A mensagem final do agente pra sessão principal deve listar:

- Hashes + subjects dos commits criados
- Arquivos tocados (incluindo o `.md` do ticket)
- Gates rodados + resultado
- Qualquer desvio do spec do ticket + justificativa (com link pra
  ADR se aplicável)

### Padrão de merge na sessão principal

Sessão principal aplica via `git merge --no-ff <branch> -m "merge:
<branch> (#NN)"` (não via Apply da UI), na ordem que escolher. Zero
overlap entre worktreas é precondição pro paralelo — se houver
overlap, o agente deve sinalizar no prompt inicial e a sessão
principal serializa.

### Lições aprendidas (rodada 09+11+15, 2026-06-09)

- **Gap real do "não comite sem pedido":** agente do #09 implementou
  + escreveu Resolution mentalmente + parou sem comitar nada do
  ticket `.md`. Sessão principal teve que recriar o closeout commit
  manualmente. Esta seção existe pra fechar esse gap.
- **`.scratch/` worktree vs main:** agente do #11 editou a Resolution
  no path da main repo, não no path do worktree. Detectou no
  pre-commit, fez `cp`, comitou. Documentado no passo 3 acima.
- **`README.md` de tickets:** zero agente mexeu (instrução explícita
  no prompt funcionou) → manter o padrão.
