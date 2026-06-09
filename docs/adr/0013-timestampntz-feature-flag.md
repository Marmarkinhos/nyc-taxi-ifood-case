# 0013: Habilitar `delta.feature.timestampNtz` em Bronze e Silver (preservar ADR-0001)

## Status

Accepted

## Context

Primeiro `bundle run job_ingestion` end-to-end com Fixes #2-#5 aplicados
(2026-06-09, depois do ADR-0012) destravou o `landing_task` mas expôs
o próximo blocker: `dlt_pipeline_task` falha na **criação da tabela
Bronze** com:

```
[DELTA_FEATURES_REQUIRE_MANUAL_ENABLEMENT] Your table schema requires
manually enablement of the following table feature(s): timestampNtz.
Current supported feature(s): appendOnly
```

Causa: o parquet TLC Yellow declara `tpep_pickup_datetime` /
`tpep_dropoff_datetime` como `timestamp[us]` **sem timezone** —
Arrow/Spark mapeiam esse tipo pra `TIMESTAMP_NTZ` (TIMESTAMP No Time
Zone). O Auto Loader, com `cloudFiles.inferColumnTypes=true`, respeita
o tipo do parquet. Resultado: o `@dlt.table` da Bronze tenta criar uma
Delta table com coluna `TIMESTAMP_NTZ`, e o Delta runtime do Free
Edition rejeita porque o table feature `timestampNtz` não está
habilitado por default (só `appendOnly` está).

Três opções foram consideradas:

**H1 — `cloudFiles.schemaHints` na Bronze.** Forçar Auto Loader a
inferir os dois campos como `TIMESTAMP` (com timezone) em vez de
`TIMESTAMP_NTZ`. Resolve o problema na origem, mas:

- **Viola ADR-0001.** Bronze é fiel à fonte: rename/cast/drop são
  proibidos. `TIMESTAMP_NTZ` é o tipo que o parquet TLC declara.
  Substituir por `TIMESTAMP-com-tz` é um cast disfarçado de hint.
- **Acopla a Bronze ao schema TLC.** Se TLC renomear ou remover esse
  campo num release futuro, o hint vira erro de runtime opaco.
- **Surface mais larga.** 2 hints explícitos + comment + cobertura
  no `test_tlc_schema.py` (que hoje é Spark-free e não conhece
  `cloudFiles.schemaHints`).

**H2 — `table_properties={"delta.feature.timestampNtz": "supported"}`
em cada `@dlt.table` decorator.** Habilita o feature no nível da
tabela. Mantém Auto Loader / inferência intactos.

- **Preserva ADR-0001.** Bronze continua escrevendo o tipo declarado
  pelo parquet TLC.
- **Mudança cirúrgica.** Uma linha em cada `table_properties`.
- **Natureza correta.** `delta.feature.timestampNtz` é configuração
  de runtime do Delta, equivalente em natureza aos
  `delta.autoOptimize.optimizeWrite` que já estão nos dois
  decorators (ADR-0005). Não é transformação semântica.
- **Sem acoplamento ao schema TLC.** Se TLC adicionar/remover
  qualquer coluna TIMESTAMP_NTZ amanhã, nada muda aqui.

**H3 — `spark.conf.set("spark.databricks.delta.properties.defaults.
feature.timestampNtz", "supported")` no topo do pipeline.** Aplica
pra todas as tabelas criadas no pipeline. Mesmo efeito de H2 mas com
blast radius maior (configura defaults globais em vez de declarar por
tabela). Pior auditabilidade: a propriedade não fica visível no
`DESCRIBE EXTENDED` da tabela.

## Decision

**H2.** Adicionar `"delta.feature.timestampNtz": "supported"` ao
`table_properties` dos **dois** `@dlt.table` decorators em
`ingestion/dlt_pipeline.py`:

```python
# Bronze (yellow_taxi_trips_raw)
table_properties={
    "delta.autoOptimize.optimizeWrite": "true",
    "delta.autoOptimize.autoCompact": "true",
    "delta.feature.timestampNtz": "supported",  # ADR-0013
},

# Silver (yellow_taxi_trips)
table_properties={
    "delta.autoOptimize.optimizeWrite": "true",
    "delta.autoOptimize.autoCompact": "true",
    "delta.tuneFileSizesForRewrites": "true",
    "delta.feature.timestampNtz": "supported",  # ADR-0013 (defensive)
},
```

A Silver hoje **não precisa** do flag — `_build_silver_projection`
casta `tpep_*_datetime` pra `TIMESTAMP-com-tz` via
`canonical_type` (ver `nyc_taxi_case.tlc_schema`). Habilitamos
defensivamente pra:

1. Manter simetria de contrato Bronze/Silver (mesma capacidade Delta).
2. Sobreviver a uma adição futura de coluna `TIMESTAMP_NTZ` em
   `TLC_RENAME_MAP` que a Silver propague verbatim.

`tlc_schema.py` **não muda** — o tipo canônico da Silver continua
`TIMESTAMP` (com tz), porque essa é a escolha semântica do projeto
(ADR-0001: Silver canônica e tipada). O cast NTZ → TZ usa a session
timezone do Spark (UTC default no Free Edition), preservando o
instante.

### Alternativas rejeitadas

- **H1 (`cloudFiles.schemaHints`)** — viola ADR-0001 e acopla a
  Bronze ao schema TLC. Os benefícios ("evitar feature flag exótico"
  citados no handoff inicial) não se sustentam: `timestampNtz` é o
  tipo NATURAL do parquet TLC, não exótico. Habilitar respeita a
  fonte; forçar `TIMESTAMP-com-tz` na Bronze a contradiz.
- **H3 (`spark.conf.set`)** — perde auditabilidade por tabela e
  acopla a decisão ao runtime do pipeline em vez de à definição
  declarativa da tabela. `DESCRIBE EXTENDED` não mostra a propriedade.
- **Esperar Free Edition mudar o default** — fora do nosso controle;
  bloqueante imediato.

## Consequences

**Positivas:**

- `dlt_pipeline_task` destrava: Bronze é criada com `timestampNtz`
  habilitado e aceita o tipo inferido pelo Auto Loader.
- ADR-0001 preservado: Bronze continua 100 % fiel ao parquet TLC.
- `tlc_schema.py` inalterado: o mapa de tipos canônicos da Silver
  segue como única source-of-truth pra transformação tipada.
- Pattern reutilizável: qualquer Delta feature que o Free Edition
  não habilite por default e que a fonte requeira vai pelo mesmo
  caminho (`table_properties["delta.feature.<x>"] = "supported"`).
- Auditável: `DESCRIBE EXTENDED workspace.nyc_taxi_bronze.
  yellow_taxi_trips_raw` mostra a propriedade na seção `Table
  Properties`.

**Negativas:**

- Mais duas linhas de `table_properties` pra manter (uma na Bronze,
  uma na Silver). Custo desprezível, mas é mais um item no review
  surface das decisões DLT.
- Acopla o pipeline implicitamente ao Free Edition's default set
  de features Delta. Se rodarmos num workspace onde `timestampNtz`
  já está habilitado por default, o flag é redundante (sem dano —
  Delta ignora declarações de features já ativos).
- Não há regression test Spark-free pra essa decisão. A seam é o
  próprio `bundle run job_ingestion` (mesmo princípio do ADR-0012).

**Neutras:**

- ADR-0001 inalterado (Bronze fiel à fonte). Esta decisão
  *reforça* o ADR-0001 ao escolher a opção que não exige cast na
  Bronze.
- ADR-0005 inalterado (defensive tblproperties). Esta decisão
  segue o mesmo princípio (configuração de runtime, não
  transformação semântica) só que pra outra dimensão (feature
  enablement em vez de optimize hints).
- ADR-0012 inalterado (self-bootstrap). Independentes.

## Cross-references

- ADR-0001 — Silver canônica não "fiel à fonte" (Bronze é). Esta
  decisão protege ADR-0001 ao rejeitar H1.
- ADR-0005 — `tblproperties` defensivas na Silver. Padrão arquitetural
  reusado aqui.
- `.scratch/issues/case-implementation/06-job-ingestion-dab.md` Fix
  #6 — registro operacional desse fix (sintoma, diagnose, validação).
- `AGENTS.md` §"Gotchas operacionais" — entrada `timestampNtz`
  resolvida por este ADR.
