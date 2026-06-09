# Domain Docs

Como as skills devem consumir a documentação de domínio deste repo
quando estiverem explorando o código.

## Antes de explorar, ler

- **`CONTEXT.md`** na raiz — vocabulário load-bearing (TLC, Bronze/Silver/Gold,
  pickup_year_month, Janela, Free Edition, Audit table, Trio de consumo, etc.)
- **`docs/adr/`** — ADRs que tocam a área onde você vai trabalhar
- **`docs/PLAN.md`** — plano de execução completo do case
- **`docs/CASE.md`** — enunciado original (fonte da verdade dos requisitos)

Se algum desses arquivos não existir (ex.: `docs/adr/` vazio no começo),
**prossiga silenciosamente**. Não sinalize a ausência nem sugira criar
upfront. A skill produtora (`/grill-with-docs`) cria ADRs lazy quando
termos ou decisões realmente se resolvem.

## Estrutura

Single-context:

```
/
├── CONTEXT.md
├── docs/
│   ├── PLAN.md
│   ├── CASE.md
│   └── adr/
│       ├── 0001-pickup-year-month-from-tpep.md
│       └── 0002-audit-table-pre-bronze.md
└── src/nyc_taxi_case/
```

Não é monorepo. Não terá `CONTEXT-MAP.md`.

## Use o vocabulário do glossário

Quando o output nomeia um conceito de domínio (título de issue, proposta
de refactor, hipótese, nome de teste), usa o termo como definido em
`CONTEXT.md`. Não driftar pra sinônimos que o glossário evita
explicitamente.

Exemplos load-bearing pra não esquecer:
- **Bronze / Silver / Gold** (não "raw / clean / curated")
- **pickup_year_month** derivado de `tpep_pickup_datetime`, NÃO do nome
  do arquivo
- **Yellow taxi** apenas (não green/fhv/fhvhv)
- **Free Edition** implica serverless-only, sem SP, outbound restrita

Se o conceito que você precisa ainda não está no glossário, é sinal —
ou você está inventando linguagem que o projeto não usa (reconsiderar),
ou tem gap real (anotar pra `/grill-with-docs`).

## Sinalize conflitos com ADRs

Se seu output contradiz um ADR existente, traga isso à tona ao invés
de silenciosamente sobrescrever:

> _Contradiz ADR-0003 (audit-table-pre-bronze) — mas vale reabrir
> porque…_

## Não-objetivos do case (declarados em CONTEXT.md)

Antes de propor algo, checar se cai num dos NÃO-objetivos:
- NÃO ingerir green/fhv/fhvhv
- NÃO deploy via CI (Free Edition não suporta SP)
- NÃO usar Genie / DuckDB como camada de consumo
