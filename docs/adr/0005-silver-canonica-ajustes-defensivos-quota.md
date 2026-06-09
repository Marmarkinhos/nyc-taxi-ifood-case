# 0005: Silver canônica preservada com ajustes defensivos de quota Free Edition

## Status
Accepted

## Context
ADR-0001 fixou Silver como "canônica e tipada" preservando todas as 19
colunas TLC + derivadas. Case explicita "outras colunas podem ser
ignoradas" — 14 colunas (`payment_type`, `RatecodeID`,
`store_and_fwd_flag`, `PULocationID`, `DOLocationID`, `fare_amount`,
`extra`, `mta_tax`, `tip_amount`, `tolls_amount`,
`improvement_surcharge`, `congestion_surcharge`, `airport_fee`,
`trip_distance`) não são lidas por nenhuma consulta do case nem
validadas por expectations. Estimativa de storage para Jan–Maio 2023
(~85M linhas): Silver canônica ~3–4 GB Delta vs Silver enxuta ~800 MB.
Free Edition tem quota de storage apertada e não-publicada; risco de
throttling no meio de demo do avaliador é real.

## Decision
Manter Silver canônica (decisão de ADR-0001), com três ajustes
defensivos pra mitigar custo de quota sem comprometer o argumento
arquitetural:

1. **Tblproperties Delta agressivas na Silver:**
   - `delta.autoOptimize.optimizeWrite = true`
   - `delta.autoOptimize.autoCompact = true`
   - Compressão ZSTD nível alto (default DLT é ZSTD level 1; subir
     pra level 9+ via `spark.databricks.delta.optimizeWrite.compression.codec`
     se DLT permitir override; fallback aceita default).
   - Esperado: storage real ~1.2 GB pós-compaction (vs 3–4 GB sem
     ajustes), próximo ao custo da Silver enxuta.

2. **Justificativa explícita no README** (parágrafo dedicado, não
   bullet enterrado): "Silver canônica não é luxo arquitetural; é a
   única camada que permite ao avaliador rodar uma consulta
   exploratória sobre `tip_amount` ou `payment_type` sem repipeline —
   e a Gold view garante que o consumo oficial (Pergunta 1 e 2) não
   paga esse custo na leitura."

3. **Plano de contingência documentado** em "Próximos passos" do
   README: "Silver enxuta é alternativa válida se a quota Free Edition
   apertar — mudança é dropar projeção no `@dlt.table` da Silver;
   Bronze e Gold continuam idênticos."

Alternativas rejeitadas:
- **Silver enxuta (5 colunas + derivadas):** mata o argumento
  "Medallion real reutilizável" e remove capacidade de EDA sobre
  colunas TLC ignoradas. Economiza ~30% storage por preço de
  expectation #7 (contrato de schema) virar trivial — não vale.
- **Silver canônica sem ajustes:** confia em quota não-publicada;
  risco de throttling no momento errado (demo do avaliador) é
  inaceitável para custo de 30 LOC de defesa.

## Consequences
**Positivas:** argumento arquitetural ("Medallion real") fica blindado
contra a pergunta "por que 14 colunas que ninguém usa?"; quota Free
Edition deixa de ser risco silencioso; plano de contingência
explícito sinaliza maturidade operacional pro avaliador.
**Negativas:** ~30 LOC a mais entre `tblproperties` dict e README;
acoplamento a comportamento específico de auto-compaction Delta (se
DLT mudar default, ajustes podem virar no-op silencioso — mitigado
documentando no commit que introduzir os tblproperties).
**Neutras:** schema da Silver não muda; comportamento downstream
(Gold, expectations) idêntico.
