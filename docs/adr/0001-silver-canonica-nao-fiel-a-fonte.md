# 0001: Silver é "canônica e tipada", não "fiel à fonte"

## Status
Accepted

## Context
O plano original (PLAN.md §3, decisão #5) descreveu Silver como
"fiel à fonte". Quatro transformações aplicadas na Silver contradizem
o termo: rename para snake_case, casting de tipos, drop via
expectations, e adição de coluna derivada (`pickup_year_month`).
Adicionalmente, "fiel à fonte" colidia com a função real da Bronze
— que é, ela sim, fiel à fonte (raw + metadata, sem transformação).
Reservar "fiel" para Landing/Bronze e dar a Silver outro adjetivo
("canônica") elimina a colisão. Manter o termo "fiel" arrisca o
avaliador interpretar transformações legítimas como descuido.

## Decision
Silver é definida como **canônica e tipada**: preserva todas as
colunas TLC (sem projeção), normaliza nomes (snake_case), corrige
tipos, dropa linhas que violam contratos de validade declarados via
expectations, e adiciona derivadas de tempo. Distinção operacional
Silver vs Gold: **Silver preserva todas as colunas; Gold projeta
apenas as 5 + derivadas**. Apenas Landing (bytes byte-a-byte) e
Bronze (raw + metadata, sem rename/cast/drop) são fiéis à fonte.

## Consequences
**Positivas:** terminologia auditável; futuro leitor sabe o que
esperar; rename de "fiel" para "canônica" elimina paradoxo;
Bronze ganha peso explícito no vocabulário.
**Negativas:** divergência do PLAN.md original (resolvido: ADR
supersedes o plano onde diverge).
**Neutras:** comportamento do pipeline não muda; só a etiqueta.
