# 0009: `dim_locations` dentro do escopo; Gold enriquecida com borough

## Status
Accepted

## Context
PLAN.md §8 ("Próximos passos") listou `dim_locations`
(PULocationID/DOLocationID enriquecidos via `taxi_zone_lookup.csv` da
TLC) como fora de escopo, com nota "útil pra análises de borough,
fora do escopo case". Revisitando custo vs sinal:

- **Custo real**: ~40 LOC + 1 CSV (~10 KB, 260 zonas). Tabela
  `${prefix}nyc_taxi_silver.dim_locations` populada por `@dlt.table`
  que lê `/Volumes/.../landing/nyc_taxi/zone_lookup/taxi_zone_lookup.csv`.
- **Sinal pro avaliador**: alto. Critério de avaliação iFood
  explícito é "criatividade na solução proposta". `dim_locations` é
  trazer modelagem dimensional clássica (fact + dim) pra um case que
  só pediu duas agregações simples — vai além do mínimo sem custo
  proibitivo.
- **Conexão com o case**: Pergunta 1 (`AVG(total_amount) GROUP BY
  pickup_year_month`) extensível pra "...por borough" sem mudar
  pipeline. EDA bônus em `analysis/04_eda_geographic.sql` demonstra
  a extensão.

Risco honesto: `dim_locations` é adicionada **sem que nenhuma das 2
perguntas obrigatórias do case use**. Resposta defensável: "Gold view
inclui `PULocationID`/`DOLocationID` (preserva projeção da Silver
canônica), e `dim_locations` é o resolver natural; sem ela, IDs são
opacos no resultado."

## Decision
Trazer `dim_locations` pra dentro do escopo, com três artefatos
concretos:

1. **Seed dbt** `dbt/seeds/taxi_zone_lookup.csv` materializado via
   `dbt seed` em `${prefix}nyc_taxi_gold.dim_locations`. CSV oficial
   TLC commitado no repo. Schema com tipos forçados via
   `dbt_project.yml`:

   ```yaml
   seeds:
     nyc_taxi_case:
       taxi_zone_lookup:
         +schema: nyc_taxi_gold
         +column_types:
           location_id: int
           borough: string
           zone: string
           service_zone: string
   ```

   Tipos forçados (não inferência automática) porque
   `location_id INT` precisa casar com `PULocationID`/`DOLocationID`
   do source Silver pro test `relationships` do ADR-0007 funcionar
   sem type mismatch.

2. **Gold model dbt enriquecido**
   (`dbt/models/gold/yellow_taxi_trips_consumption.sql`) — além das
   5 colunas exigidas + `pickup_year_month` + `pickup_hour`, projeta
   `pickup_borough` e `dropoff_borough` via
   `LEFT JOIN {{ ref('dim_locations') }}` (LEFT pra preservar linhas
   com `PULocationID`/`DOLocationID` desconhecidos ou NULL).

3. **EDA bônus** `dbt/models/analyses/eda_geographic.sql` —
   `AVG(total_amount) GROUP BY pickup_borough ORDER BY 2 DESC`.
   ~5 linhas SQL. README cita como "extensão natural habilitada pela
   `dim_locations`".

**Notas de implementação (consequência do ADR-0010):**
A mecânica original deste ADR era `@dlt.table` + Gold view DLT;
foi atualizada pra seed dbt + modelo dbt como consequência direta
do ADR-0010 (fronteira DLT↔dbt na Silver). A **decisão load-bearing**
(trazer dim pra escopo + enriquecer Gold) está preservada; só o
mecanismo mudou.

**Schema `gold` (não `silver`)** porque `job_dbt` só escreve em
`gold` por contrato de separação de donos (ADR-0011 — cada job
escreve só no seu schema). `job_ingestion` é dono de `bronze`,
`silver`, `monitoring`; `job_dbt` é dono de `gold`. Botar seed em
`silver` violaria a invariante.

Atualização paralela de docs:
- Remover `dim_locations` da seção 8 do PLAN.md / "Próximos passos"
  do README.
- Remover Liquid Clustering da mesma seção (já trazido pra dentro
  pelo ADR-0006).

Alternativas rejeitadas:
- **Manter `dim_locations` em "Próximos passos"**: cumpre o mínimo do
  case; perde oportunidade barata de marcar critério "criatividade na
  solução proposta".
- **Adicionar `dim_locations` mas sem enriquecer a Gold**: tabela
  isolada sem consumer no escopo do case — futuro leitor pergunta
  "por que existe?". Enriquecer a Gold dá propósito imediato.
- **Materializar dim em `silver` schema** (preserva semântica
  "Silver canônica" do dim de referência): rejeitado, viola
  separação de donos do ADR-0011 (dbt escreveria em schema do
  ingestion).
- **Inferência automática de tipos do CSV (sem `column_types`)**:
  rejeitado, risco de `location_id` inferido como `bigint` quebra
  `relationships` test do ADR-0007 por type mismatch silencioso.

## Consequences
**Positivas:** marca critério "criatividade na solução proposta" do
iFood com entrega concreta; `PULocationID`/`DOLocationID` na Gold
deixam de ser opacos; modelagem dimensional clássica demonstrada;
seção "Próximos passos" do README enxuga de 8 pra 6 itens (saem
Liquid Clustering e `dim_locations`). Padrão dbt-idiomático (seed +
`ref()`) é universalmente legível, sem custo de explicação.
**Negativas:** ~10 LOC dbt (seed config + Gold model join) + 1 CSV
+ 1 SQL análise + parágrafo README; +1 ponto de manutenção (se TLC
mudar formato do `taxi_zone_lookup.csv`, ajuste manual). **Refresh
manual via `dbt seed`** (não automático a cada `job_ingestion`
update); TLC raramente atualiza zone lookup (~1x/ano), aceitável.
Avaliador roda `bundle run job_dbt` que inclui `dbt seed` no DAG —
sem passo extra exposto.
**Neutras:** comportamento das 2 perguntas obrigatórias do case
idêntico (`dim_locations` só é referenciada na EDA bônus +
enriquecimento de Gold).
