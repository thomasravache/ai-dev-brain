# Tipos de nota

Os sete tipos da v1 e o `answer` do fluxo de consultar. Cada um tem um modelo em `assets/templates/<tipo>.md`, que o `init` copia para `templates/` do vault; o `new-note` usa o modelo do vault (a pessoa pode alterá-lo) e cai no da skill quando o do vault não existe.

## Frontmatter comum

As chaves ficam sempre em inglês; o conteúdo, no idioma da pessoa.

| Chave | Valor |
|---|---|
| `type` | `note`, `lecture`, `source`, `video`, `document`, `link`, `moc` ou `answer` |
| `title` | o título da nota (o nome do arquivo é o título sem `/ \ : * ? " < > \| # ^ [ ]`) |
| `context` | o nome do contexto do `brain-config.yml`; ausente quando a nota não tem contexto |
| `created` | data de criação, `AAAA-MM-DD` |
| `tags` | lista, ex.: `[calculo, integrais]` |
| `source` | `"[[raw/<nota de fonte>]]"` ou uma URL; ausente quando não há fonte |
| `files` | lista de caminhos relativos à pasta `files` (arquivos pesados, fora do vault); ausente quando não há |

A nota de fonte criada pelo `ingest` tem também `source_url` quando a fonte é um link.

Todo modelo tem `# {title}`, `## Summary` (menos o `answer`), as seções do tipo e, no fim, `## Relations` (linhas `- [[Nota]] — motivo`, escritas pelo `relate`). Os marcadores `{title}`, `{date}`, `{context}` e `{source}` são preenchidos pelo `new-note`.

## `note`

Anotação livre ou ideia própria. Seções: `## Summary`, `## Relations`. Modelo: `assets/templates/note.md`.

## `lecture`

Aula ou palestra. Seções: `## Summary`, `## Key points`, `## Questions`, `## Relations`. Modelo: `assets/templates/lecture.md`.

## `source`

Nota de fonte: o bruto de um arquivo ou link, em `raw/`, criada pelo `ingest` (com `files` ou `source_url` e o texto sob `## Extracted text`). Seções: `## Summary`, `## Extracted text`, `## Relations`. Modelo: `assets/templates/source.md`.

## `video`

Vídeo (gravação de aula, palestra online). Seções: `## Summary`, `## Timestamps`, `## Relations`. Modelo: `assets/templates/video.md`.

## `document`

PDF, artigo ou documento longo. Seções: `## Summary`, `## Highlights`, `## Relations`. Modelo: `assets/templates/document.md`.

## `link`

Página da web guardada pelo link. Seções: `## Summary`, `## Relations`. Modelo: `assets/templates/link.md`.

## `moc`

Mapa de conteúdo de um contexto (`mocs/<contexto>.md`). A região `<!-- brain:begin notes -->` é regenerada pelo `index` com as notas do contexto agrupadas por `type`; o texto fora dela é da pessoa. Seções: `## Summary`, `## Relations`. Modelo: `assets/templates/moc.md`.

## `answer`

Resposta a uma pergunta feita ao segundo cérebro, salva no fim do fluxo de consultar (`references/query-flow.md`) só com o sim da pessoa. Frontmatter extra: `question` (a pergunta, como a pessoa fez) e `cites` (lista com os títulos das notas citadas, ex.: `[Integrais por partes, Regra do produto]`). Seções: `## Question`, `## Answer` (com `[[nota]]` em cada afirmação vinda do vault), `## Gaps` (o que a pergunta pede e o vault não tem), `## Relations` (uma linha `- [[Nota]] — cita` por nota citada, escrita pelo `relate`). Modelo: `assets/templates/answer.md`.
