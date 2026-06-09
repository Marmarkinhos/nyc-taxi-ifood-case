# 0011: Orquestração — 2 jobs DAB independentes sem `depends_on`

## Status
Accepted

## Context
ADR-0010 fixou ingestão e modelagem como concerns separados,
costurados pela tabela Silver via `sources.yml`. Resta a decisão
de orquestração: como expor esses dois concerns como cargas
executáveis no Databricks?

Três alternativas naturais:

- **(X) 1 job DAB único** com `pipeline_task` (DLT) → `dbt_task`,
  ligados por `depends_on`. dbt roda automaticamente após DLT.
- **(Y) 2 jobs DAB**, mas `job_dbt` com `depends_on` apontando pro
  `pipeline_task` do `job_ingestion`.
- **(Z) 2 jobs DAB completamente independentes**, sem `depends_on`
  cross-job. Contrato implícito via `sources.yml`.

Padrão iFood real (verificado factualmente no `pagob2b-dbt`):
nenhum dos 30+ job YAMLs tem `pipeline_task` (DLT) como
`depends_on` de `dbt_task`. dbt confia no `sources.yml` (que aponta
pra tabela Delta no UC) e roda quando quiser. **Quem produz a
fonte não conhece quem consome.**

A tentação inicial é (X) — 1 job único é "mais conveniente" porque
o avaliador roda 1 comando em vez de 2. Mas isso reintroduz o
acoplamento que ADR-0010 explicitamente removeu: `job_ingestion`
passaria a conhecer existência de `dbt_task`, ou `job_dbt`
dependeria do run específico de um pipeline DLT.

## Decision
**2 jobs DAB completamente independentes, sem `depends_on`
cross-job.** Alternativa (Z).

Concretamente:

- `resources/job_ingestion.yml` — contém landing notebook task +
  DLT pipeline task + SQL task pós-DLT (`UPDATE landing_audit`).
  Não menciona dbt em lugar nenhum.
- `resources/job_dbt.yml` — contém `dbt_task` standalone com
  `commands: [dbt deps, dbt seed, dbt run, dbt test]`. Não menciona
  pipeline DLT, landing notebook, nem schemas de ingestão.
- Schedule **pausado** nos 2 jobs em todos os targets.
- Execução manual via `databricks bundle run <job>`.

**Runbook canônico (README):**

```
databricks bundle deploy --target user_dev
databricks bundle run job_ingestion   # ~5min, popula até Silver
databricks bundle run job_dbt         # ~2min, popula Gold + análises
```

**Comportamento do `job_dbt` se `job_ingestion` nunca rodou:**
- `dbt seed` cria `dim_locations` (não depende de Silver).
- `dbt run` do Gold falha hard via `{{ exceptions.raise_compiler_error(...) }}`
  porque `landing_audit` está vazia (ADR-0003 editado). Mensagem
  explícita: "nenhum run de ingestão registrado em landing_audit;
  rode `bundle run job_ingestion` primeiro".
- Avaliador recebe erro acionável, não tabela vazia silenciosa.

## Notas de implementação

**Sobre monorepo vs 2 repos:** o código vive no mesmo repo GitHub
por **UX do avaliador** (1 clone + 1 `bundle deploy` + 2
`bundle run`), com pastas separadas (`ingestion/` + `dbt/` +
`resources/`). Em produção iFood seriam 2 repos
(`ifp-data-ingestions` + `pagob2b-dbt`). **Essa escolha de
organização de código não altera a decisão de orquestração**:
mesmo no monorepo, os 2 jobs não se referenciam por
`depends_on`. Documentado em detalhe no README seção "Estrutura
do repo".

**Sobre não-uso de `pipeline_task` no `job_dbt`:** dbt-databricks
não conhece DLT pipelines; conhece tabelas Delta no UC. Tentar
expressar dependência via `pipeline_task` no `job_dbt` seria gambiarra
e quebraria o ponto do ADR-0010.

**Sobre repetição de configurações:** ambos os jobs precisam de
`environment_settings`, `cluster_key`, etc. Repetidos via
`resources/general_variables.yml` + `${var.xxx}` em vez de
herança/`extends`. Padrão `pagob2b-dbt` na iFood.

## Alternativas rejeitadas

- **(X) 1 job DAB único com `depends_on`**: reintroduz acoplamento
  removido pelo ADR-0010; `job_ingestion` passa a "saber" que existe
  modelagem; mudança no `job_dbt` (ex.: adicionar `dbt test` extra)
  exigiria editar o job de ingestão. Conveniência (1 comando)
  paga preço arquitetural alto.
- **(Y) 2 jobs com `depends_on` cross-job**: tecnicamente possível
  (Databricks suporta), mas hacky — quebra a invariante "produtor
  não conhece consumidor" e mistura concerns de schedule entre os
  jobs. Não tem precedente no `pagob2b-dbt`.

## Consequences
**Positivas:**
- Espelha exatamente o padrão `pagob2b-dbt` da iFood (verificado:
  30+ job YAMLs, zero `depends_on` pipeline_task em `dbt_task`).
- Cada job é evoluível independentemente; mudança em um não
  bloqueia o outro.
- Contrato cross-job (`sources.yml`) é explícito e versionável.
- "Quem produz não conhece quem consome" — invariante
  arquitetural codificada na configuração, não só no código.

**Negativas:**
- Avaliador roda 2 comandos em vez de 1 (mitigado por runbook
  README de 4 linhas).
- Não há sinal automático "ingestion done → dbt should run".
  Aceitável no contexto do case (1 execução manual por avaliador);
  em produção iFood seria mitigado por scheduling independente
  (ingestão hourly + dbt hourly desacoplado) ou por Workflows
  externos.
- Reuso de variáveis entre os 2 job YAMLs exige discipline
  (mitigado por `general_variables.yml` centralizado).

**Neutras:**
- Schemas, comportamento DLT e dbt independentes da escolha de
  orquestração — esta decisão é puramente sobre quem aciona quem.

## Relação com outros ADRs
- **ADR-0010** é o ADR fundador deste; consequência direta da
  separação de concerns ingestão↔modelagem.
- **ADR-0003** (editado) define o failure mode "first run"
  quando `job_dbt` roda antes de `job_ingestion`.
- **ADR-0008** define o schema `landing_audit` que é o canal
  implícito de sinal de "ingestão done" pro `job_dbt` (via
  filtro de janela do ADR-0003).
