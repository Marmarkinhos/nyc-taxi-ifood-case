# Issue tracker: Local Markdown

Issues e PRDs deste repo vivem como arquivos markdown em `.scratch/issues/`.

Decisão consciente: case solo, sem time, sem necessidade de GitHub Issues
público. Toda a conversa fica versionada junto com o código.

## Convenções

- Uma feature por diretório: `.scratch/issues/<feature-slug>/`
- PRD da feature: `.scratch/issues/<feature-slug>/PRD.md`
- Issues de implementação: `.scratch/issues/<feature-slug>/<NN>-<slug>.md`,
  numeradas a partir de `01`
- Estado de triagem fica no **frontmatter YAML** de cada `.md` (campo
  `status:` — ver `docs/agents/triage-labels.md` pros valores válidos)
- Comentários e histórico apendam no fim do arquivo sob `## Comments`

## Frontmatter mínimo

```yaml
---
status: needs-triage
created: 2026-06-08
---
```

Campos opcionais úteis: `parent:` (link pra PRD ou issue mãe), `blocks:`,
`blocked-by:`, `tags:`.

## Quando uma skill diz "publicar no issue tracker"

Cria um novo arquivo sob `.scratch/issues/<feature-slug>/` (criando o
diretório se necessário).

## Quando uma skill diz "buscar o ticket relevante"

Lê o arquivo no path referenciado. O user normalmente passa o caminho ou
o número da issue direto.
