# 0015: Bronze `addNewColumnsWithTypeWidening` + Silver `_rescued_data` recovery para drift de tipo TLC

## Status

Accepted. **Supersede parcial de ADR-0014** (`§Decision` items 1 e 4) —
ver §"Relação com ADR-0014" abaixo.

## Context

ADR-0014 (Fix #7) hipotetizou que o rescue de 13.12M rows feb-mai/2023
era 100% causado por **case-mismatch** no campo `Airport_fee`. Aplicou
`cloudFiles.schemaHints` (Fix #7) e depois `readerCaseSensitive=false`
(Fix #8). Os dois fixes deployaram com sucesso mas **o rescue
persistiu idêntico** ao pré-fix:

```
2023-01:  3,066,766 / 0          rescued (0.0%)
2023-02:  2,913,955 / 2,913,955  rescued (100%)
2023-03:  3,403,766 / 3,403,766  rescued (100%)
2023-04:  3,288,250 / 3,288,250  rescued (100%)
2023-05:  3,513,649 / 3,513,649  rescued (100%)
```

### Root cause real

Download local dos 5 parquets TLC e comparação byte-a-byte do schema
Arrow com `pyarrow.parquet.ParquetFile.schema_arrow` revelou que TLC
mudou os **tipos físicos** de 6 colunas entre jan/2023 e fev-mai/2023,
não só o case de `Airport_fee`:

| Coluna | jan/2023 | feb-mai/2023 | Hint ADR-0014 | Consequência |
|---|---|---|---|---|
| `VendorID` | INT64 | **INT32** | BIGINT | rescue (width mismatch) |
| `passenger_count` | DOUBLE | **INT64** | DOUBLE | rescue (type-class mismatch) |
| `RatecodeID` | DOUBLE | **INT64** | DOUBLE | rescue (type-class mismatch) |
| `PULocationID` | INT64 | **INT32** | BIGINT | rescue (width mismatch) |
| `DOLocationID` | INT64 | **INT32** | BIGINT | rescue (width mismatch) |
| `airport_fee` | lower | `Airport_fee` Camel | (lower anchor) | **OK** (Fix #8 funcionou aqui) |

A doc oficial confirma o mecanismo do rescue (Auto Loader
[Schema inference and evolution — Override schema inference with schema hints](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/schema#override-schema-inference-with-schema-hints)):

> "When you specify schema hints, Auto Loader **doesn't cast** the
> column to the specified type, but rather tells the Parquet reader to
> read the column as the specified type. **In the case of a mismatch,
> Auto Loader rescues the column** by placing the data in the rescued
> data column."

Ou seja: hints pinam **exatamente um tipo** e **desabilitam o type
widening automático** nessa coluna. Eram os hints que estavam
**causando** o rescue dos 5 type-drifting cols — não resolvendo nada.

Verificação empírica pós ADR-0014 (rescued JSON):

```json
{"VendorID":1,"passenger_count":2,"RatecodeID":1,
 "PULocationID":48,"DOLocationID":223,
 "_file_path":"...yellow_tripdata_2023-04.parquet"}
```

Note: **`Airport_fee` NÃO aparece** no JSON — Fix #8 (case anchoring)
resolveu o problema dele. Os 5 valores que aparecem são exatamente os
5 type-drifting cols, com valores integer-literal (jan ship DOUBLE
mas valores são todos integer-valued: 1.0, 2.0, ..., 9.0).

### Por que ADR-0014 não viu isso

Validação do schema usou só `yellow_tripdata_2023-01.parquet`
(documentado no comment de `BRONZE_SCHEMA_HINT_TYPES`). Não comparou
schemas dos meses subsequentes — assumiu uniformidade. O JSON
`_rescued_data` mostrava 6 colunas, e ADR-0014 atribuiu todas as 6 a
case-mismatch sem cross-check com schema físico dos parquets restantes.

Lição: **diff de schema cross-month é um passo obrigatório** quando
investigando rescue em parquets ingested por Auto Loader.

### Auto Loader type widening tem cobertura parcial

Doc oficial (Auto Loader
[Automatic type widening](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/type-widening#supported-type-changes))
lista a tabela exata de widenings suportados:

| Source type | Supported wider types |
|---|---|
| `int` (INT32) | `long`, `decimal`, `double` |
| `long` (INT64) | `decimal` (**não tem `double`**) |
| `float` | `double` |
| `double` | (não widens pra nada) |

Aplicando aos 5 drifting cols TLC:

| Coluna | jan → feb-mai | Widening suportado? |
|---|---|---|
| `VendorID` | INT64 → INT32 / INT32 → INT64 | ✅ (int → long) |
| `PULocationID` | mesmo | ✅ |
| `DOLocationID` | mesmo | ✅ |
| `passenger_count` | DOUBLE → INT64 / INT64 → DOUBLE | ❌ (nenhuma direção) |
| `RatecodeID` | mesmo | ❌ (nenhuma direção) |

Para os 3 INT cols, `addNewColumnsWithTypeWidening` resolve
autonomamente. Para `passenger_count` e `RatecodeID`, nenhuma
configuração de reader unifica DOUBLE e INT64 — é um limite **hard**
da especificação Delta type widening.

### Alternativas para os 2 cols sem path de widening

**A1 — Hint as DOUBLE.** Jan funciona, feb-mai rescue (13M rows).
**Status quo, pior caso.**

**A2 — Hint as BIGINT.** Feb-mai funciona (DOUBLE → BIGINT widens via
`long → decimal`? Não, source é DOUBLE não suportado), jan rescue (3M
rows). **Status quo invertido — ainda perde dados.**

**A3 — Hint as DECIMAL(20,2).** Mesmo problema de A2 — DOUBLE não
widens.

**A4 — Pre-cast no landing antes da Bronze (DOUBLE → INT64 dropando
fractional).** Hacky e viola ADR-0001 (Bronze fiel-à-fonte).

**A5 (escolhida) — Recovery na Silver via `get_json_object(_rescued_data, ...)`.**
A Silver já é a camada que canoniza (DOUBLE/INT64 source → BIGINT
canonical). O `_rescued_data` JSON contém os valores originais sempre
que a coluna foi rescuada. `coalesce(typed_col, get_json_object(
_rescued_data, '$.passenger_count').cast(BIGINT))` recupera o valor
para feb-mai e fica no-op para jan (que não foi rescuada).

Custo: 2 `get_json_object` por row na Silver (cheap; é a mesma string
JSON lida em paralelo). Benefício: zero data loss, sem violar ADR-0001
(o rescue continua acontecendo na Bronze — fiel à fonte, com o JSON
populado e a coluna NULL), e Silver continua sendo a única camada que
faz transformação semântica (ADR-0010).

### Por que não migrar pra `.schema(StructType)` explícito

Hipótese B3/B4 do handoff anterior. Rejeitada pelos mesmos motivos
do ADR-0014 §"Alternativa que considerei e rejeitei":

- `schemaEvolutionMode` default vira `none` quando schema é provido;
  perdemos `addNewColumns` gratuito.
- Adiciona mais uma fonte declarativa (`StructType` PySpark) ao já
  existente `BRONZE_SCHEMA_HINT_TYPES` + `TLC_RENAME_MAP` +
  `TLC_COLUMN_TYPES`.
- A combinação `addNewColumnsWithTypeWidening` + recovery cirúrgico
  na Silver tem **blast radius menor** e mantém a arquitetura DLT
  ortogonal.

## Decision

1. **`cloudFiles.schemaEvolutionMode = "addNewColumnsWithTypeWidening"`**
   (era `addNewColumns`). Permite o reader widen INT32 → INT64 para
   os 3 width-drifting cols autonomamente.

2. **`delta.enableTypeWidening = "true"`** no `table_properties` da
   Bronze (`@dlt.table`). Prereq da documentação Auto Loader pra
   widening propagar pro Delta sink sem rewrite.

3. **Remover 5 colunas type-drifting de `BRONZE_SCHEMA_HINT_TYPES`**
   (`VendorID`, `passenger_count`, `RatecodeID`, `PULocationID`,
   `DOLocationID`). Hints disable widening; tê-las hinted é o que
   estava causando o rescue. As 14 colunas estáveis (mais o anchor
   defensivo de `airport_fee`/`Airport_fee` case) continuam hinted.

4. **Adicionar `_RESCUED_RECOVERY` map em `_build_silver_projection`**
   pros 2 cols sem path de widening (`passenger_count`, `RatecodeID`).
   `coalesce(F.col(source).cast(...), F.get_json_object(
   F.col("_rescued_data"), "$.<source>").cast(...))`. No-op pra jan
   (typed col não-NULL), recovery efetivo pra feb-mai.

5. **`test_tlc_schema.py` inverte o contract:** em vez de checar que
   `BRONZE_SCHEMA_HINT_TYPES` cobre TODOS os 19 cols (ADR-0014), passa
   a checar que cobre **somente** os 14 estáveis e **não inclui** os 5
   type-drifting. Frozenset `_TYPE_DRIFTING_TLC_COLUMNS` documenta as
   5 colunas e por quê. Regressão (alguém re-adicionar uma das 5)
   surfa loud como test failure.

6. **Pipeline DLT continua precisando `--full-refresh`** depois do
   deploy. Item 3 do ADR-0014 inalterado.

## Relação com ADR-0014

ADR-0014 §Decision tem 5 itens; este ADR **supersede** os itens 1 e 4:

| ADR-0014 item | Status | Por quê |
|---|---|---|
| **1. `cloudFiles.schemaHints` com 19 cols** | **SUPERSEDED** por §Decision 3 deste ADR (14 cols, não 19). |
| **2. Expectation warn-only `bronze_no_rescued_data`** | **Mantido**. O rescue feb-mai ainda dispara (passenger_count/RatecodeID), mas agora a Silver recupera. A expectation continua sendo drift detector útil — só que agora "drift sem path de widening" também aciona. Ticket #14 (`bronze-drift-metrics`) refinará. |
| **3. `--full-refresh` obrigatório pós-deploy** | **Mantido**. Schema cacheado em `cloudFiles.schemaLocation` ainda persiste sem invalidação. |
| **4. Hints source-side, NÃO canônicos** | **SUPERSEDED em parte** por §Decision 4 deste ADR — pros 2 cols que precisam de recovery, o cast canonical (BIGINT) é aplicado tanto no `typed` path quanto no `recovered` path da Silver. As 14 colunas estáveis ainda usam source-side type no hint Bronze. |
| **5. Gaps reconhecidos pro ticket #14** | **Mantido + estendido**. Ticket #14 agora também precisa cobrir o sinal de "passenger_count/RatecodeID 100% rescued feb-mai" pra não confundir com drift novo. |

ADR-0014 §"Follow-up correction" (Fix #8 / `readerCaseSensitive=false`)
**continua válido e inalterado** — case anchoring de `Airport_fee` é
independente do type drift e Fix #8 resolveu corretamente o problema
dele.

## Consequences

**Positivas:**

- Silver recupera ~13M rows feb-mai (95.7% de redução no drop). Total
  Silver: 15.6M (era 2.97M).
- `passenger_count_in_range` drops vão de 13.19M → 428K (96.7%
  redução; o resíduo são valores genuinamente fora de `[0, 9]`).
- `vendor_id_in_dictionary` drops vão de 13.12M → 0 (100%).
- ADR-0001 preservado: Bronze continua fiel à fonte (rescue do feb-mai
  permanece registrado no `_rescued_data` da Bronze; Silver lê o JSON
  via `get_json_object` mas não escreve nada de volta na Bronze).
- ADR-0010 preservado: fronteira ingestão↔modelagem mantida. O
  recovery acontece na Silver (camada de modelagem), não no notebook
  de landing nem no `@dlt.table` da Bronze.
- Pattern reutilizável: qualquer próxima coluna TLC que driftar entre
  tipos sem path de widening (DOUBLE↔INT64 é o caso TLC, mas qualquer
  outro fits) usa o mesmo `_RESCUED_RECOVERY` map.

**Negativas:**

- **`_rescued_data` continua 100% populado feb-mai** porque
  `passenger_count` e `RatecodeID` rescuam. Visualmente o pipeline
  ainda mostra "13M warnings" no UI do Lakeflow. **Isso é correto**
  (Bronze fiel à fonte, schema-drift detector), mas pode confundir
  quem olha o UI sem ler este ADR. Ticket #14 cobrirá renomear /
  detalhar a expectation.
- **`bronze_required_columns_not_null` continua disparando** pelo
  mesmo motivo. Idem.
- **Silver custo aumenta marginalmente** com 2 `get_json_object` por
  row. Negligível na escala de 16M rows; teste de carga em produção
  futura validará se vira problema.
- **Adiciona dependência implícita** da Silver no schema do
  `_rescued_data` (JSON keys = nomes TLC source). Mitigação: pytest
  contrato (`test_silver_still_canonicalises_drifting_columns`)
  enforça que toda drifting col tenha um canonical Silver type, e o
  `_RESCUED_RECOVERY` map é localizado no `_build_silver_projection`
  com comment explicando o link com ADR-0015.

**Neutras:**

- ADR-0013 (`delta.feature.timestampNtz`) inalterado.
- ADR-0007 inalterado (zero `expect_or_fail`).
- `addNewColumnsWithTypeWidening` é Public Preview (DBR 16.4+);
  Lakeflow serverless já está em 16.4+, sem risco operacional
  imediato. Quando virar GA, este ADR continua válido.

## Validation

Update `acc127b0-95da-4a01-942e-2a0577b40b41` (full-refresh post-fix):

```
Bronze yellow_taxi_trips_raw:
  jan: 3,066,766 total, 0 rescued, 0 vendor/pu/do null, 71743 pax/rate null (natural)
  feb: 2,913,955 total, 100% rescued, 0 vendor/pu/do null, 100% pax/rate null
  ...

Silver yellow_taxi_trips (after recovery):
  2023-01: 2,969,823 (pax_null=0, rate_null=0)
  2023-02: 2,812,327 (pax_null=0, rate_null=0)
  2023-03: 3,286,320 (pax_null=0, rate_null=0)
  2023-04: 3,167,797 (pax_null=0, rate_null=0)
  2023-05: 3,380,067 (pax_null=0, rate_null=0)
  Total: 15,616,438 (was 2,969,863 pre-fix)
```

Silver expectations (delta vs pre-fix):

| Expectation | Pre-fix failed | Post-fix failed | Delta |
|---|---|---|---|
| `passenger_count_in_range` | 13,191,363 | 428,665 | **-96.7%** |
| `vendor_id_in_dictionary` | 13,119,620 | 0 | **-100%** |
| `total_amount_non_negative` | 141,407 | 141,407 | 0 (legit refunds) |
| `dropoff_after_pickup` | 795 | 795 | 0 (legit) |
| `pickup_month_matches_file` | 437 | 437 | 0 (TLC temporal noise) |

## Cross-references

- **ADR-0014** — superseded em parte; ver §"Relação com ADR-0014".
- **ADR-0001** — Silver canônica vs Bronze fiel à fonte. Esta decisão
  reforça: Bronze permanece fiel (rescue é registrado, não silenciado);
  Silver é onde acontece a recuperação semântica.
- **ADR-0007** — expectations sem `expect_or_fail`. Inalterado.
- **ADR-0010** — fronteira ingestão↔modelagem. O `_rescued_data`
  recovery acontece em `_build_silver_projection` (camada de
  modelagem), não em `ingestion/landing.py`.
- **ADR-0013** — `delta.feature.timestampNtz`. Complementar:
  `delta.enableTypeWidening` foi adicionado ao mesmo
  `table_properties` block.
- **`.scratch/issues/case-implementation/06-job-ingestion-dab.md`**
  Fix #9 — registro operacional (sintoma, diagnose com pyarrow,
  validação numérica, ordem de deploy).
- **`.scratch/issues/case-implementation/14-bronze-drift-metrics.md`**
  — agora também precisa cobrir o sinal "rescue feb-mai genuíno"
  para não confundir com drift novo.
- **AGENTS.md** §"Gotchas operacionais" — entrada nova: type-drift
  TLC + widening matrix limits (LONG ↔ DOUBLE não é widening).
