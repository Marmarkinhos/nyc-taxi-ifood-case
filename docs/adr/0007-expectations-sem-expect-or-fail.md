# 0007: Expectations sem `expect_or_fail`; contrato de schema em teste unitário + warn

## Status
Accepted

## Context
PLAN.md §3 (decisão #7) propôs 7 expectations na Silver com mix
`4 expect_or_drop + 2 expect + 1 expect_or_fail`. A expectation #7
(`expect_or_fail` no contrato de 5 colunas exigidas) **aborta a
pipeline update inteira** quando viola. Em Free Edition:

- 1 pipeline DLT ativo, sem service principal, sem alertas externos.
- Cenário trigger da #7: TLC renomeia coluna no source (eles já
  fizeram mudanças antes — `airport_fee` adicionado em 2022).
- Resultado: pipeline FAILED silenciosa no UI, sem on-call, sem
  alerta. Demo do avaliador quebra com diagnóstico ruim.

Em produção iFood com on-call + alerta, `expect_or_fail` no contrato
é defensável: fail loud, fail fast. Em case sem alerta, é armadilha:
blast radius (pipeline inteira aborta) é maior que o do problema (TLC
mudar schema, evento raro e detectável por outros mecanismos).

Adicionalmente, contrato de schema pode ser garantido **mais cedo**
(teste unitário pré-deploy) e **mais barato** (warn na Bronze sem
abortar) que `expect_or_fail` na Silver.

## Decision
**Nenhuma expectation usa `expect_or_fail`.** Lista final:

| # | Regra | Camada | Severidade | Propósito |
|---|---|---|---|---|
| 1 | `vendor_id IN (1, 2, 6, 7)` | Silver | `expect` | Observa drift TLC; warn no event_log |
| 2 | `passenger_count BETWEEN 0 AND 9` | Silver | `expect_or_drop` | Protege Pergunta 2 (AVG passenger_count) |
| 3 | `total_amount >= 0` | Silver | `expect_or_drop` | Protege Pergunta 1 (AVG total_amount); refunds dropados — viés conhecido pra cima, documentado no README |
| 4 | timestamps NOT NULL | Silver | `expect_or_drop` | Sem pickup → sem `pickup_year_month` → sem partição válida |
| 5 | `dropoff >= pickup` | Silver | `expect_or_drop` | Corrupção pura |
| 6a | `pickup_year_month = file_year_month` | Silver | `expect` | Detecta ruído temporal (ADR-0003/0004) |
| 7-bronze | 5 colunas exigidas NOT NULL | **Bronze** | `expect` | Substitui antigo `expect_or_fail` por warn-only |

Contrato de schema (presença + tipos das 5 colunas exigidas) é
garantido por **três mecanismos não-bloqueantes em camadas distintas**:

1. **`ingestion/tests/test_schema.py::test_required_columns_present`** —
   fixture com schema TLC esperado (19 colunas + types). CI vermelho
   se schema mudar. Pega 100% dos casos onde **alguém atualizou o
   código local sem atualizar o contrato** (vetor: pré-deploy,
   mudança humana).
2. **Expectation `expect` warn-only na Bronze** (#7-bronze):
   `VendorID IS NOT NULL AND passenger_count IS NOT NULL AND
   total_amount IS NOT NULL AND tpep_pickup_datetime IS NOT NULL AND
   tpep_dropoff_datetime IS NOT NULL`. Aparece no `event_log` se
   **TLC mudar nomes** (vetor: runtime, mudança upstream). Pipeline
   continua rodando; warn visível.
3. **dbt tests no `job_dbt`** — rodam após `job_ingestion` produzir
   Silver. Cobrem o vetor "Silver tem dados sintaticamente ok mas
   semanticamente quebrados" (TLC adicionou `vendor_id=8` sem aviso,
   LocationID novo sem entrada no seed `dim_locations`, etc.).
   Inventário fixo:

   | Test | Onde | Equivale | Por quê |
   |---|---|---|---|
   | `not_null` em `tpep_pickup_datetime`, `passenger_count`, `total_amount`, `tpep_dropoff_datetime`, `vendor_id` | `_sources.yml` (Silver) | Hard-fail equivalente à #7-bronze, pós-Silver | Falha CI dbt se Silver propagar NULL em coluna exigida |
   | `accepted_values: [1, 2, 6, 7]` em `vendor_id` | `_sources.yml` (Silver) | **Redundância intencional** com expectation #1 (warn) | Warn na #1 chama atenção no event_log; hard-fail dbt impede Gold propagar valor desconhecido pro avaliador |
   | `relationships` Gold→`dim_locations` em `pickup_location_id` e `dropoff_location_id` | Gold model schema.yml | — | TLC adicionou zones em 2024; pega LocationID sem entrada no seed |
   | `not_null` em `pickup_year_month`, `pickup_borough`, `dropoff_borough` | Gold model schema.yml | — | Garante derivações + enriquecimento de borough funcionaram |

   `accepted_values` ser **redundante** com expectation #1 é decisão
   consciente: Silver (DLT) é warn-only por ADR-0005 (sem
   `expect_or_fail`); dbt vira o ponto onde "valor inesperado bloqueia
   propagação". Os 2 mecanismos cobrem o mesmo dado em momentos
   diferentes do pipeline.

Decisões internas:
- **`trip_distance >= 0` NÃO adicionada** (foi proposta como #8):
  não é usada em consulta nem em Gold; adicionar é YAGNI; mantém
  escopo enxuto.
- **Refunds dropados pela #3 — viés conhecido pra cima**: documentado
  explicitamente no README como decisão (não como erro), pra blindar
  contra avaliador perguntar "por que sua média de `total_amount` é
  maior que a do site da TLC?".

Alternativas rejeitadas:
- **Manter #7 como `expect_or_fail` na Silver**: blast radius (pipeline
  aborta) maior que o do problema (TLC mudar schema). Inaceitável em
  ambiente sem alerta.
- **`expect_or_fail` movida pra Bronze**: mesmo blast radius (toda
  pipeline aborta), só muda a camada — não resolve.

## Consequences
**Positivas:** blast radius máximo vira "Silver tem partição vazia
naquele dia se TLC mandar lixo total" — recuperável sem intervenção
manual. Contrato de schema protegido em **três camadas com vetores
de risco distintos**:

- **pytest CI** (pré-deploy, mudança humana de código local)
- **Bronze expectation warn-only** (runtime, mudança upstream de
  schema TLC — visível no event_log)
- **dbt tests** (pós-Silver runtime, hard-fail no `job_dbt` quando
  Silver propaga valor sintaticamente ok mas semanticamente quebrado)

Cada camada cobre um vetor que as outras não cobrem; rede de
segurança real, não duplicação. "7 expectations" continua sendo o
número pra contar no README (6 Silver + 1 Bronze) — dbt tests são
contados separados como "N dbt tests".

**Negativas:** se TLC fizer mudança grave de schema, `job_ingestion`
não para — Silver pode receber dados parcialmente corrompidos por
algumas horas antes de alguém ver o warn no event_log. Mitigado pela
#7-bronze ser visível na primeira inspeção do `event_log`. O
`job_dbt` falha hard nesse cenário (segunda linha de defesa) —
avaliador rodando `bundle run job_dbt` recebe erro acionável em vez
de Gold silenciosamente quebrada.

**Neutras:** comportamento downstream (Gold, consultas) idêntico
enquanto schema TLC estável. dbt tests adicionam ~30s ao `job_dbt`
em condições normais (testes passam silenciosamente).
