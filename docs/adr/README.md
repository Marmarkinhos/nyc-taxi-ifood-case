# Architecture Decision Records

Decisões arquiteturais load-bearing do case, em ordem cronológica.

## Convenção

- Nome: `NNNN-slug-kebab-case.md` (numeração de 4 dígitos a partir de `0001`)
- Template mínimo abaixo
- Status: `proposed` | `accepted` | `superseded by ADR-XXXX` | `rejected`

## Template

```markdown
# ADR-NNNN: <título imperativo curto>

- **Status:** accepted
- **Date:** YYYY-MM-DD
- **Decisores:** <quem>

## Contexto

<o problema, restrições, alternativas consideradas>

## Decisão

<o que decidimos fazer, em uma frase>

## Consequências

<positivas, negativas, neutras — o que muda daqui pra frente>
```

## ADRs

| # | Tema | Status |
|---|---|---|
| [0001](./0001-silver-canonica-nao-fiel-a-fonte.md) | Silver canônica não "fiel à fonte" | Accepted |
| [0002](./0002-landing-http-com-probe-defensivo.md) | Landing HTTP + probe HEAD defensivo | Accepted |
| [0003](./0003-gold-filtra-janela-silver-preserva-ruido.md) | Gold filtra janela; Silver preserva ruído (editado pt4) | Accepted |
| [0004](./0004-silver-materializa-file-year-month.md) | Silver materializa `file_year_month` | Accepted |
| [0005](./0005-silver-canonica-ajustes-defensivos-quota.md) | Silver canônica + tblproperties defensivas | Accepted |
| [0006](./0006-silver-liquid-clustering-em-vez-de-particao.md) | Liquid Clustering em vez de partição | Accepted |
| [0007](./0007-expectations-sem-expect-or-fail.md) | Expectations sem `expect_or_fail` + dbt tests (editado pt4) | Accepted |
| [0008](./0008-landing-audit-schema-reconstruibilidade.md) | `landing_audit` schema reconstruível | Accepted |
| [0009](./0009-dim-locations-dentro-do-escopo.md) | `dim_locations` como seed dbt (editado pt4) | Accepted |
| [0010](./0010-fronteira-ingestao-modelagem-na-silver.md) | Fronteira ingestão↔modelagem na Silver canônica | Accepted |
| [0011](./0011-orquestracao-dois-jobs-dab-independentes.md) | Orquestração: 2 jobs DAB independentes sem `depends_on` | Accepted |
| [0012](./0012-landing-notebook-self-bootstrap.md) | Landing notebook self-bootstrap (schema + Volume + exit protocol) | Accepted |
| [0013](./0013-timestampntz-feature-flag.md) | Habilitar `delta.feature.timestampNtz` em Bronze e Silver | Accepted |
| [0014](./0014-bronze-schema-hints-e-rescued-data-expectation.md) | Bronze `cloudFiles.schemaHints` + expectation `bronze_no_rescued_data` | Superseded em parte por ADR-0015 |
| [0015](./0015-bronze-type-widening-e-silver-rescued-recovery.md) | Bronze `addNewColumnsWithTypeWidening` + Silver `_rescued_data` recovery | Accepted |
