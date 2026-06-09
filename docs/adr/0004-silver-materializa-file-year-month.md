# 0004: Silver materializa file_year_month derivada do nome do arquivo TLC

## Status
Accepted

## Context
Expectation #6a (ADR-0003) compara `pickup_year_month` com o mês
declarado no nome do arquivo TLC pra detectar ruído temporal. O nome
está disponível via `_metadata.file_path` (trazido pela Bronze do Auto
Loader). Computar regex em toda expectation/consulta é custoso e
poluído.

## Decision
Silver adiciona coluna `file_year_month STRING` materializada via
`regexp_extract(_metadata.file_path, 'yellow_tripdata_(\d{4}-\d{2})\.parquet', 1)`.
Computada uma vez no `@dlt.table` da Silver. Disponível pra
expectations, EDA e Gold sem reparse.

## Consequences
**Positivas:** expectation #6a vira `pickup_year_month = file_year_month`
(simples, sem regex inline); EDA pode comparar "arquivo declarado vs
pickup real" trivialmente; coluna stable como dimensão de auditoria.
**Negativas:** acoplamento ao formato do nome de arquivo TLC — se TLC
mudar pra `yellow_2023_01.parquet`, a regex quebra e
`file_year_month` vira NULL silenciosamente; mitigado por teste em
`tests/test_schema.py` que valida a regex contra fixture do nome
oficial.
**Neutras:** +1 coluna na Silver (custo storage desprezível,
8 chars STRING).
