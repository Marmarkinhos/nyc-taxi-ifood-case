---
status: done
created: 2026-06-08
closed: 2026-06-09
tags: [skeleton, helpers, ci, tdd]
blocks: [03-landing-notebook.md, 06-job-ingestion-dab.md]
commits: [d13d6ac, 1fed2b6, c9e78dc]
---

# 02 — Repo skeleton + helpers puros + CI

## What to build

Esqueleto do monorepo + helpers Python puros + CI no GitHub
Actions. Primeira fatia AFK; estabelece base pra todas as demais.

**Estrutura mínima:**

- `databricks.yml` raiz com targets (`user_dev`, etc.) e include
  de `resources/`.
- `resources/general_variables.yml` (catalog prefix, paths de
  Volume, schemas — variáveis usadas pelos 2 jobs depois).
- `src/nyc_taxi_case/` como package Python instalável (ou via
  `--include-py` no DAB) contendo:
  - `window.py` — parse e validação de `--start_year_month` /
    `--end_year_month`, geração da lista de meses inclusivos.
  - `tlc_urls.py` — builder de URLs CloudFront da TLC
    (`https://d37ci6vzurychx.cloudfront.net/trip-data/
    yellow_tripdata_YYYY-MM.parquet`).
  - `schema.py` — definição do contrato de schema mínimo das 5
    colunas exigidas pelo case + helper de validação chamado
    pelo CI.
- `ingestion/tests/` com pytest cobrindo os 3 módulos acima
  (TDD red-green-refactor; ver skill `tdd`).
- `pyproject.toml` (ou setup.cfg) com ruff + mypy + pytest
  configurados.
- `.github/workflows/ci.yml` rodando:
  - `ruff check .`
  - `mypy src/`
  - `pytest ingestion/tests/`
  - `databricks bundle validate --target user_dev` (com
    autenticação stub — sem deploy)

**Não inclui** notebooks de landing, DLT pipeline, dbt project,
ou jobs YAMLs concretos — esses entram nos slices seguintes.

## Acceptance criteria

- [ ] `databricks.yml` valida com `databricks bundle validate`
      (mesmo vazio de jobs)
- [ ] `src/nyc_taxi_case/window.py` parseia `YYYY-MM`, rejeita
      formatos inválidos, gera lista inclusiva de meses (incluindo
      range `2023-01..2023-05` = 5 itens)
- [ ] `src/nyc_taxi_case/tlc_urls.py` gera URL TLC correta pra
      qualquer `YYYY-MM` válido
- [ ] `src/nyc_taxi_case/schema.py` define as 5 colunas exigidas +
      helper que valida presença
- [ ] pytest cobre os 3 módulos (~80%+ coverage do que importa)
- [ ] Regex `file_year_month` (parse de
      `yellow_tripdata_YYYY-MM.parquet`) implementado e testado
      em `schema.py` ou módulo dedicado (ADR-0004)
- [ ] GitHub Actions CI verde em PR + main
- [ ] `ruff check .` e `mypy src/` passam sem erros
- [ ] README mínimo no root explicando estrutura (será expandido
      no ticket #13)

## Blocked by

None.

## Resolution (2026-06-09): ✅ DONE

Entregue nos commits `d13d6ac`, `1fed2b6`, `c9e78dc` (ver
`commits:` no frontmatter). Skeleton do monorepo + helpers puros
TDD + CI rodando contra `uv run ruff check .` e `uv run pytest -q`
estabelecido como gate; todas as ondas subsequentes de tickets
herdaram esses gates como precondição de merge.

Cobertura concreta entregue:

- `databricks.yml` raiz + `resources/general_variables.yml`
- Package `src/nyc_taxi_case/` com helpers puros
  (`window.py`, `tlc_urls.py`, `schema.py`) + tests
- CI GitHub Actions verde
- `uv` lockfile (`uv.lock`) commitado pra reprodutibilidade

Validado de cabo a rabo pelos 12 tickets seguintes — todo merge
desta feature passou pelos gates definidos aqui.

## Notas

- Pattern iFood: `pagob2b-dbt` + `ifp-data-ingestions` separam
  `dbt/` + `ingestion/` + `resources/` + `src/`. Replicar.
- Skill `tdd` recomendada pros helpers puros — testes primeiro,
  implementação depois.
- Variável `${var.catalog_prefix}` em `general_variables.yml` deve
  permitir override por target (user_dev usa prefix do user;
  produção hipotética usaria empty string).
