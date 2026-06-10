# Notes que não viraram ADR

Decisões conscientes documentadas porque são surpreendentes ou
fáceis de second-guess de fora, mas não passam no filtro de ADR
(não são hard-to-reverse + surpreendentes + trade-off real, todas
as três simultaneamente).

## Sem convenção `_int_` / `_fin_` nos modelos dbt

Quatro Gold views + uma seed total — taxonomias de prefixo de
modelo (`_stg_`, `_int_`, `_fin_`) pagam a partir de ≥10 modelos.
Rejeitado como over-engineering pra este escopo.

## Monorepo em vez de 2 repos GitHub

Splittar em formato `ifp-data-ingestions` + `pagob2b-dbt` é um
`git filter-repo` one-shot (`ingestion/` + metade de `resources/` →
ingestion repo; `dbt/` → modelling repo). Manter junto durante o
case mantém grep / commit history / ADRs todos no mesmo lugar — UX
do avaliador. A separação operacional já está garantida pelos 2
jobs DAB independentes (ADR-0011).

## `uv.lock` é gitignored

Dependências vivem em `pyproject.toml`; forçar todo contribuidor a
usar `uv` via lock comitado é fricção sem payoff nesta escala.

## `yellow_tripdata_*.parquet` no root é gitignored

Uma cópia local vive lá de uma sessão one-off de inspeção de schema
no início do projeto; o pipeline só lê parquets do Volume UC após
o download HTTP. Manter o gitignore evita commit acidental dos
~50 MB por mês.
