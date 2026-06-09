---
status: ready-for-human
created: 2026-06-08
tags: [probe, hitl, blocker, dbt, dab]
blocks: [10-job-dbt-dab.md]
---

# 01 — Probe Opção B: validar `dbt_task` no DAB em serverless Free Edition

## What to build

Probe descartável que valide se o cenário real do projeto funciona:
**`dbt_task` declarado num `resources/job_*.yml` rodando dentro de
`databricks bundle run` em serverless Free Edition**.

O probe Opção A já validado (handoff pt4 + ADR-0010 §Validação
empírica) cobriu `dbt-databricks` adapter via CLI local apontando pro
SQL Warehouse. Isso **não cobre** o cenário do `job_dbt`: dbt sendo
invocado pelo DAB como `dbt_task`, em compute serverless,
empacotando o projeto dbt como part do bundle.

Escopo do probe (throwaway, fora dos diretórios definitivos):

- Mini-projeto dbt em `/tmp/kilo/dbt-probe-b/` com 1 seed + 1 model
  view trivial (mesmo schema `workspace.dbt_probe` do probe A).
- Mini-bundle DAB com 1 job único contendo apenas um `dbt_task`
  apontando pra esse mini-projeto.
- `databricks bundle deploy --target user_dev` + `bundle run <job>`.
- Observar: o job sobe? `dbt deps + seed + run` rodam? Logs ficam
  acessíveis via `bundle run --no-wait` + UI? Custos de cold start
  aceitáveis em Free Edition?

Saída do probe é **decisão arquitetural**, não código:

- **Se passar:** atualizar ADR-0010 §Validação empírica + ADR-0011
  marcando Opção B validada. Ticket #10 (`job_dbt` DAB) segue como
  planejado.
- **Se falhar:** atualizar ADR-0010 §Consequências invocando o
  fallback documentado ("Gold model dbt rodando via `dbt run` no
  CLI do avaliador"). Redefinir escopo do ticket #10 — `resources/
  job_dbt.yml` deixa de existir; runbook README passa a ser
  `bundle run job_ingestion && cd dbt && dbt run`.

## Acceptance criteria

- [ ] Perfil Databricks CLI configurado pro workspace Free Edition
      (pré-requisito; pode ser feito dentro deste ticket ou
      sinalizado como sub-bloqueador)
- [ ] Mini-projeto dbt + mini-bundle criados em `/tmp/kilo/dbt-probe-b/`
- [ ] `databricks bundle deploy` executado com sucesso
- [ ] `databricks bundle run <job>` executado, resultado registrado
      (PASS / FAIL com mensagem de erro completa)
- [ ] ADR-0010 §Validação empírica + ADR-0011 atualizados com
      resultado e data
- [ ] Se FAIL: ADR-0010 §Consequências reflete invocação do
      fallback; ticket #10 redefinido por nova issue ou edit
- [ ] Mini-projeto e mini-bundle apagados de `/tmp/kilo/`
- [ ] PAT usado no probe registrado pra revogação (entra no
      ticket #13)

## Blocked by

None — primeiro ticket, bloqueador dos demais relacionados a `job_dbt`.

## Notas operacionais

- HITL: requer humano rodar `bundle deploy` + interpretar logs +
  decidir entre seguir ou invocar fallback.
- Profile do Databricks CLI ainda não configurado (pendência
  operacional do handoff). Pode ser absorvido aqui ou virar
  sub-ticket — recomendado absorver pra não criar dependência
  trivial entre tickets.
- Não escrever código de implementação do case neste ticket —
  estritamente probe.
