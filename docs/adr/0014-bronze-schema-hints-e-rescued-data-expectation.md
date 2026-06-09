# 0014: Bronze `cloudFiles.schemaHints` + expectation `bronze_no_rescued_data` para detectar drift TLC

## Status

**Superseded em parte por [ADR-0015](0015-bronze-type-widening-e-silver-rescued-recovery.md)** (2026-06-09).

- §Decision items 1 e 4 (hints cobrindo 19 cols; tipos source-side
  pros 19) ficam OBSOLETOS — ADR-0015 reduz a 14 cols hinted e move
  o cast de `passenger_count`/`RatecodeID` pra Silver via
  `_rescued_data` recovery.
- §Decision items 2, 3, 5 e §"Follow-up correction" (`readerCaseSensitive=false`)
  permanecem **válidos e em produção**.

Histórico mantido aqui pra rastrear como o diagnose chegou em ADR-0015
(hipótese "100% case-mismatch" → fix → empirical evidence → hipótese
"type drift" → ADR-0015).

## Context

Primeiro `bundle run` end-to-end com Fix #6 (ADR-0013) aplicado
(2026-06-09) mostrou DLT pipeline rodando até o fim, mas a Silver
caiu 81.5 % das rows na expectation `passenger_count_in_range`
(13.19M rows dropped). Investigação SQL revelou:

```sql
SELECT file_month, total, rescued
  FROM (
    SELECT regexp_extract(_source_file_path,
                          'yellow_tripdata_(\d{4}-\d{2})', 1) AS file_month,
           COUNT(*) AS total,
           SUM(CASE WHEN _rescued_data IS NOT NULL THEN 1 ELSE 0 END) AS rescued
      FROM workspace.nyc_taxi_bronze.yellow_taxi_trips_raw
    GROUP BY 1
  );

-- 2023-01:  3,066,766 / 0          rescued (0.0%)
-- 2023-02:  2,913,955 / 2,913,955  rescued (100%)
-- 2023-03:  3,403,766 / 3,403,766  rescued (100%)
-- 2023-04:  3,288,250 / 3,288,250  rescued (100%)
-- 2023-05:  3,513,649 / 3,513,649  rescued (100%)
```

E o `_rescued_data` típico de fev-mai:

```json
{"VendorID": 2, "passenger_count": 1, "RatecodeID": 1,
 "PULocationID": 238, "DOLocationID": 42, "Airport_fee": 0.0,
 "_file_path": "..."}
```

### Root cause

Validação local com pyarrow nos 5 parquets TLC Yellow 2023:

| Mês | Nome do campo "airport fee" |
|---|---|
| 2023-01 | `airport_fee` (lowercase) |
| 2023-02 a 2023-05 | `Airport_fee` (CamelCase) |

**TLC renomeou silenciosamente o campo entre janeiro e fevereiro
de 2023.** Os outros 18 campos são byte-idênticos entre todos os
meses.

Mecanismo da queima:

1. Auto Loader processou o primeiro arquivo (jan/2023) e cravou o
   schema com `airport_fee` lowercase em `cloudFiles.schemaLocation`.
2. Arquivos fev-mai chegam com `Airport_fee` (CamelCase). Spark default
   é `spark.sql.caseSensitive=false`.
3. Parquet vectorized reader detecta `Airport_fee` no arquivo vs
   `airport_fee` no schema cacheado. Case-insensitive match positivo,
   mas case-different. O reader entra num path de safety conservador
   e **descarta o row group inteiro** que contém o campo ambíguo —
   despejando 6 colunas no `_rescued_data` por row, mesmo as 5
   (`VendorID`, `passenger_count`, `RatecodeID`, `PULocationID`,
   `DOLocationID`) que não tinham case-mismatch.
4. Bronze grava NULL nessas 6 colunas pra rows fev-mai. Silver
   projection retorna NULL pra `passenger_count`. Expectation
   `passenger_count BETWEEN 0 AND 9` é NULL → FALSE → DROP.
5. Resultado: 81.5 % de drop loss na Silver, originado por **uma
   única letra** que TLC mudou no nome de um campo.

### Por que isso não foi pego antes

- `test_tlc_schema.py` valida o helper Spark-free. Não tem como
  ele saber que TLC trocou `airport_fee` por `Airport_fee` em fev/2023
  porque o schema validado empiricamente foi o de jan/2023 (validado
  contra `yellow_tripdata_2023-01.parquet` — está nos comments do
  helper).
- A expectation Bronze existente (`bronze_required_columns_not_null`,
  ADR-0007) **passou** porque ela checa as 5 mandatórias (incluindo
  `passenger_count`) — mas no Bronze, `passenger_count` está NULL,
  então a expectation **deveria** ter falhado. Vou abrir um
  follow-up: por que não falhou? Provável: ela só corre pro batch
  pequeno do Spark Streaming e os 81.5 % falhos não atingiram o
  threshold default. Independente da resposta, a expectation
  existente não foi o sinal certo pra esse drift.
- Não havia nenhuma expectation pra `_rescued_data`. O sinal mais
  óbvio (campo `_rescued_data` populado) estava sem instrumento.

### Alternativas consideradas

**S1 — schemaHints na Bronze (escolhida).** Auto Loader aceita
`cloudFiles.schemaHints` com formato Spark SQL DDL
(`"name type, name type, ..."`). Esse hint **anchora**
name+type pra cada coluna declarada: parquet reader sabe que
`Airport_fee` no arquivo bate com `airport_fee` no schema
(case-insensitive match com anchor explícito, sem ambiguidade),
e o cast é trivial (mesmo tipo source).

**S2 — Só Silver case-insensitive lookup.** Resolver `F.col(...)`
contra `{c.lower(): c for c in bronze.columns}` na Silver. **Rejeitada**
porque o problema é upstream: a Bronze já está com NULL e
`_rescued_data` populado — o lookup case-insensitive na Silver olha
pra Bronze que **não tem** os dados, só tem o JSON rescuado. Pra
recuperar via S2, a Silver teria que parsear `_rescued_data` como
JSON, o que (a) é caro em runtime, (b) viola fronteira
ingestão↔modelagem (ADR-0010), e (c) introduz mais ambiguidade que
resolve.

**S3 — `spark.sql.caseSensitive=true`.** Force Spark a tratar
`Airport_fee` e `airport_fee` como colunas distintas. **Rejeitada**:
quebra TODO o ecossistema downstream (dbt, queries ad-hoc, dim
modelo) que assume default Spark. Blast radius gigante pra
resolver um problema localizado.

**S4 — `cloudFiles.schemaEvolutionMode="rescue"` permanente.** Aceita
que tudo vai pro rescued e responsabiliza a Silver por extrair de
lá. **Rejeitada**: vira um schema-less data lake disfarçado de
Medalhão. Anula o valor da Bronze tipada.

### Sobre a relação com ADR-0001 ("Bronze fiel à fonte")

ADR-0001 declara que Bronze é "fiel à fonte: raw + metadata, sem
rename/cast/drop". `schemaHints` parece à primeira vista violar isso
("estou ditando que `airport_fee` é DOUBLE"). Mas há uma distinção
load-bearing:

| Operação | Categoria | ADR-0001 |
|---|---|---|
| `F.col("X").cast(Y)` | **transformação** semântica | proibido na Bronze |
| `schemaHints` "X TYPE" | **contrato de schema** declarativo | permitido — descreve o que esperamos da fonte |

`schemaHints` não transforma dado. Ele declara: "se esse arquivo
parquet tiver um campo cujo nome bate (case-insensitive) com `X`, e
tipo bate (com cast trivial) com `TYPE`, anchore como `X` de tipo
`TYPE` no schema da tabela". Se o arquivo não tiver `X`, a Bronze
fica sem essa coluna (não força criação). Se tiver `X` com tipo
incompatível, o cast falha e a row vai pro `_rescued_data` (loud).

Isso é semanticamente equivalente a `REQUIRED_TLC_COLUMNS` em
`nyc_taxi_case.schema`, que já é load-bearing e declarativo, só
que ao nível do schema Spark/parquet.

Esse mesmo raciocínio foi aplicado **na direção inversa** no Fix #6
(ADR-0013): lá rejeitamos `schemaHints` pra `tpep_*_datetime` porque
o objetivo era trocar `TIMESTAMP_NTZ` por `TIMESTAMP-com-tz` — uma
transformação semântica. Aqui o hint preserva o tipo original
(DOUBLE pra `passenger_count`, BIGINT pra `VendorID`) e só anchora
o nome. ADR-0013 e ADR-0014 são consistentes: hints como **anchor
defensivo** OK; hints como **cast disfarçado** não OK.

### Sobre defesa em camadas

O fix de schemaHints sozinho resolve o caso desse Fix #7. Mas TLC
vai drifftar de novo. Vou cobrir os 3 tipos prováveis de drift
futuro com mecanismos independentes:

| Drift TLC | Comportamento com S1 + expectation |
|---|---|
| Rename de case (ex: `Airport_fee` → `AIRPORT_FEE`) | hints absorvem (case-insensitive match com anchor); sem rescued; sem ação humana |
| Coluna nova adicionada | `addNewColumns` materializa na Bronze; Silver ignora porque `TLC_RENAME_MAP` não a conhece. Sem alarme programático — **gap conhecido**, ticket #14. |
| Mudança de tipo (ex: `total_amount` STRING) | Cast falha → `_rescued_data` populado → expectation `bronze_no_rescued_data` warn dispara no `event_log`. **Sinal claro.** |
| Coluna removida | Bronze fica sem ela; Silver projeta NULL. Expectation `bronze_required_columns_not_null` pega as 5 mandatórias; outras 14 viram NULL silente. **Gap parcial**, ticket #14. |

## Decision

1. **Bronze ganha `cloudFiles.schemaHints`** derivado programaticamente
   de `BRONZE_SCHEMA_HINT_TYPES` em `nyc_taxi_case.tlc_schema`. Hints
   declaram name+source-side type pra cada um dos 19 campos TLC. Função
   `bronze_schema_hints()` é o único ponto de geração; teste pytest
   garante parity com `TLC_RENAME_MAP`.

2. **Bronze ganha expectation warn-only `bronze_no_rescued_data`:**
   `_rescued_data IS NULL`. Dispara no `event_log` quando qualquer
   row tem dado rescuado. Não dropa, não falha — o sinal é mais
   valioso que as rows que ele protege (mesmo princípio do ADR-0007).

3. **Pipeline DLT precisa `--full-refresh`** depois do deploy. Sem
   isso, o schema cacheado em `cloudFiles.schemaLocation` (com
   `airport_fee` cravado pelo jan/2023) persiste e os hints novos não
   reinferem nada. Comando exato no Fix #7 do ticket #06.

4. **Tipos do hint são source-side, NÃO canônicos da Silver.**
   `passenger_count` é DOUBLE no hint (matches parquet) e BIGINT em
   `TLC_COLUMN_TYPES` (canonical da Silver). A Silver projection é
   onde acontece o cast pra BIGINT — Bronze continua fiel à fonte.

5. **Gaps reconhecidos** (drift estrutural / % rescued métrica /
   alerting) ficam pra **ticket #14 (`bronze-drift-metrics`)**,
   registrado no `.scratch/issues/` mas não implementado neste fix.

### Alternativas rejeitadas

Ver §Context. Resumo:

- **S2 (Silver lookup case-insensitive)** — não acessa os dados
  rescuados; trata sintoma na camada errada.
- **S3 (`spark.sql.caseSensitive=true`)** — blast radius gigante.
- **S4 (`rescue` mode permanente)** — anula o valor da Bronze tipada.

## Consequences

**Positivas:**

- Recupera 13.12M rows perdidas (fev-mai/2023) após
  `bundle run --full-refresh`.
- Resolve **autonomamente** o tipo de drift TLC mais comum (case
  rename) — não precisa de PR pra esse caso voltar.
- Cria sinal claro pra outros tipos de drift (cast failure / dtype
  mudou): `event_log` da DLT mostra `bronze_no_rescued_data` warn
  com contagem de failed_records, queryable via REST API.
- `bronze_schema_hints()` + `BRONZE_SCHEMA_HINT_TYPES` + 6 testes
  novos = single source of truth pro schema TLC + cobertura
  programática contra drift entre helper e DLT.
- Pattern reutilizável: qualquer próxima fonte com drift de case/dtype
  segue o mesmo template (hints declarativo + expectation `_rescued_data`).

**Negativas:**

- **Mais uma fonte declarativa** pro schema TLC: agora são
  `TLC_RENAME_MAP`, `TLC_COLUMN_TYPES`, `BRONZE_SCHEMA_HINT_TYPES`.
  Mitigação: pytest test_hint_types_cover_every_renamed_column
  garante parity entre os 3.
- **Schema cached da Bronze precisa ser invalidado** com `--full-refresh`.
  Esquecer isso = hints sem efeito + diagnose confusa. Documentado
  como step explícito no Fix #7.
- **Gap conhecido na cobertura de drift estrutural** (coluna adicionada
  / removida). Documentado, com follow-up no ticket #14. Não bloqueia
  esse fix.
- **`schemaHints` formato é Spark SQL DDL** — frágil a mudanças no
  parser do Auto Loader. Mitigação: smoke test em pytest valida
  formato.

**Neutras:**

- ADR-0001 preservado em espírito (hint é anchor, não transformação).
- ADR-0013 (timestampNtz feature flag) inalterado e complementar:
  hint pin `TIMESTAMP_NTZ` source-side, table feature permite Delta
  escrever o tipo.
- ADR-0007 inalterado: expectations continuam zero `expect_or_fail`;
  a nova é warn-only.
- `_build_silver_projection` **inalterado** — continua usando o
  helper canonical, e agora recebe Bronze com colunas populadas em
  vez de NULL.

## Follow-up correction: schemaHints anchora nome, mas precisa de `readerCaseSensitive=false`

Data: 2026-06-09 (mesmo dia do ADR original, post Fix #7 deploy).

### Sintoma pós-deploy

Após `bundle deploy` + full-refresh (update_id
`76e62ba1-33a7-41bf-a54d-88da2be9b47e`, confirmado COMPLETED com
`full_refresh: true` via REST), repetimos a query de validação e o
resultado foi **idêntico ao pré-fix**:

```
2023-01:  3,066,766 / 0          rescued (0.0%)
2023-02:  2,913,955 / 2,913,955  rescued (100%)
2023-03:  3,403,766 / 3,403,766  rescued (100%)
2023-04:  3,288,250 / 3,288,250  rescued (100%)
2023-05:  3,513,649 / 3,513,649  rescued (100%)
```

A hipótese central do ADR ("hints fazem case-insensitive match com
anchor explícito, sem ambiguidade, resolvendo o rescue") **não se
confirmou em runtime**. O `DESCRIBE` da Bronze pós-fix mostra UMA
coluna `airport_fee` (lowercase) — então os hints ANCORARAM
corretamente o nome (sem o hint a inferência teria escolhido
`Airport_fee`, dominante em 4 dos 5 arquivos). Mas o rescue persistiu.

### Root cause real

Documentação oficial do Auto Loader
([Schema inference and evolution — Change case-sensitive behavior](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/schema#change-case-sensitive-behavior)):

> "When [rescued data column] is enabled, Auto Loader loads fields
> named in a case other than that of the schema to the `_rescued_data`
> column. Change this behavior by setting the `readerCaseSensitive`
> option to false, in which case Auto Loader reads data in a
> case-insensitive way."

Ou seja, o comportamento é **by design**:

1. Hints anchoram o nome canônico (✅ funcionou — Bronze tem
   `airport_fee` lowercase).
2. Mas o `_rescued_data` recebe **fields named in a case other than
   that of the schema** mesmo quando esse field tem match
   case-insensitive com uma coluna do schema.
3. Pra fazer o reader resolver `Airport_fee` → `airport_fee` em vez
   de rescuar, precisa **adicionalmente** setar
   `cloudFiles.readerCaseSensitive=false`.

Hints sozinhos = **anchor** do schema (necessário, pra não inferir
`Airport_fee` como nome). `readerCaseSensitive=false` = **merge** dos
dados rescuados de volta pro nome anchorado (necessário, pra não
dumpá-los no `_rescued_data`). São duas opções complementares.

### Correção

Adicionado `.option("readerCaseSensitive", "false")` na chamada do
`cloudFiles` reader em `ingestion/dlt_pipeline.py`, adjacente à
linha de `schemaHints`. Comentário no código aponta pra URL exata
da doc Databricks que descreve o comportamento + o fix.

**Detalhe operacional crítico (descoberto post-deploy):**
`readerCaseSensitive` é uma opção **format-specific** do
DataFrameReader (Parquet, JSON, CSV, etc.) — NÃO do `cloudFiles.*`
namespace. Tentativa inicial com `cloudFiles.readerCaseSensitive`
quebrou o pipeline com
`[CF_UNKNOWN_OPTION_KEYS_ERROR] Found unknown option keys: cloudFiles.readercasesensitive`
(o Auto Loader lowercaseia option keys desconhecidos antes de
reportar). A documentação do Auto Loader sobre §"Change
case-sensitive behavior" fala em "readerCaseSensitive option" sem
prefixo, e a Spark API reference §Parquet confirma: a tabela de
opções Parquet inclui `readerCaseSensitive` como format-level. Doc
do `cloudFiles.*` namespace **não** lista esse key.

Esta é uma **adição**, não um supersede:

- §Decision item 1 (hints) continua válido — sem eles, a inferência
  cravaria `Airport_fee` CamelCase (4 dos 5 arquivos), e quando
  jan/2023 chegasse, **o jan** iria pro `_rescued_data`. Hints
  garantem que escolhemos o nome certo.
- §Decision item 2 (expectation `bronze_no_rescued_data`) continua
  válido — o role do `_rescued_data` agora vira drift detector de
  verdade (cast failure, dtype change, coluna nova), não mais
  poluído por case mismatch que era pra ter sido resolvido upstream.
- Itens 3, 4, 5 (full-refresh, source-side types, gaps no ticket #14)
  inalterados.

### Por que ADR-0014 errou essa parte

A documentação do Auto Loader sobre schemaHints foca em
**type override** ("a column is of a specific data type"). A linha
sobre **case** está numa seção separada ("Change case-sensitive
behavior") que eu **não conectei** com o comportamento esperado dos
hints. Lição: doc do Auto Loader é segmentada por feature, não por
sintoma; investigação de rescue exige ler AMBAS as seções (`schemaHints`
e `readerCaseSensitive`).

### Alternativa que considerei e rejeitei pós-correção

**Migrar pra `.schema(StructType)` explícito** (era a hipótese B3 do
handoff): também resolveria, mas com mais blast radius —
`schemaEvolutionMode` default vira `none` quando schema é provido
(perdemos addNewColumns gratuito), e a duplicação `BRONZE_SCHEMA_HINT_TYPES`
+ `StructType` seria mais uma fonte declarativa. `readerCaseSensitive=false`
é a fix mínima, documentada, e mantém todo o resto da decisão original.

### Validação

Após esta correção:

- `bundle deploy` + full-refresh devem mostrar `rescued=0` em **todos**
  os 5 meses.
- Silver volta ao ~16.18M rows esperado.
- Expectation `bronze_no_rescued_data` continua warn-only, mas agora
  só dispara em drift REAL (cast failure, coluna nova, dtype change).

## Cross-references

- ADR-0001 — Silver canônica vs Bronze fiel à fonte. Esta decisão
  reforça a distinção: hint é contrato de schema, não transformação.
- ADR-0007 — expectations sem `expect_or_fail`. A nova expectation
  segue o padrão warn-only.
- ADR-0010 — fronteira ingestão↔modelagem. Esta decisão **respeita**
  a fronteira: o fix está inteiramente em ingestão (Bronze), Silver
  segue pura projeção tipada.
- ADR-0013 — `delta.feature.timestampNtz`. Complementar: hint declara
  tipo source-side; table feature permite Delta materializar.
- `.scratch/issues/case-implementation/06-job-ingestion-dab.md`
  Fix #7 — registro operacional (sintoma, diagnose, validação,
  comando de full-refresh).
- `.scratch/issues/case-implementation/14-bronze-drift-metrics.md`
  (novo) — follow-up pra drift estrutural + % rescued métrica +
  alerting de job-level.
- `AGENTS.md` §"Gotchas operacionais" — entrada nova: case mismatch
  + parquet vectorized reader rescue behavior.
