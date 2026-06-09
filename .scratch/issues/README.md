# .scratch/issues/

Issue tracker local em markdown. Convenção completa em
`docs/agents/issue-tracker.md`.

## Layout

```
.scratch/issues/
├── <feature-slug>/
│   ├── PRD.md                ← PRD da feature (gerado por /to-prd)
│   ├── 01-<slug>.md          ← issue 01 (gerada por /to-issues)
│   ├── 02-<slug>.md
│   └── ...
└── <outra-feature-slug>/
    └── ...
```

## Frontmatter mínimo

```yaml
---
status: needs-triage
created: YYYY-MM-DD
---
```

Status válidos: ver `docs/agents/triage-labels.md`.
