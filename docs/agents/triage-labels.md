# Triage Labels

As skills falam em termos de cinco roles canônicos de triagem. Este repo
usa os strings canônicos sem renomeação (case solo, sem labels legadas
pra acomodar).

| Role na skill     | Valor no campo `status:` | Significado                                      |
| ----------------- | ------------------------ | ------------------------------------------------ |
| `needs-triage`    | `needs-triage`           | Recém-criada, precisa avaliação                  |
| `needs-info`      | `needs-info`             | Aguardando mais contexto pra prosseguir          |
| `ready-for-agent` | `ready-for-agent`        | Fully specified, agent AFK pode pegar            |
| `ready-for-human` | `ready-for-human`        | Decisão humana necessária antes de implementar   |
| `wontfix`         | `wontfix`                | Descartada, não será actionada                   |

## Onde aplicar

No frontmatter YAML do arquivo `.md` em `.scratch/issues/`:

```yaml
---
status: ready-for-agent
created: 2026-06-08
---
```

## Transições válidas

```
needs-triage ──┬─→ ready-for-agent
               ├─→ ready-for-human
               ├─→ needs-info ──→ (volta a needs-triage quando respondida)
               └─→ wontfix
```

Quando uma skill mencionar um role (ex.: "aplica a label AFK-ready"),
substituir pelo valor da segunda coluna no `status:` do frontmatter.
