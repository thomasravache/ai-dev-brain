# Busca e relações entre notas

`brain.py search`, `related` e `links` leem todas as notas `.md` do vault a cada execução, em memória, sem índice
persistente e sem rede (SPEC-0018, ADR-0007). Nada é escrito no vault. Num vault de 5.000 notas de 1 KB cada comando
termina bem abaixo de 2 s.

## O que é lido

- **Pastas ignoradas:** `.obsidian/`, `.trash/` (e qualquer outra pasta oculta, que o Obsidian também não indexa), a
  pasta `layout.templates` e todo arquivo que não termina em `.md`.
- **Frontmatter:** o bloco YAML entre a primeira linha `---` e o próximo `---`. Frontmatter inválido vira `{}`; arquivo
  que não é UTF-8 é lido com caracteres substituídos. Os dois casos aparecem em `warnings` no `--json` (e como
  `aviso:` no stderr da saída em texto) e o comando continua.
- **Título:** `title` do frontmatter, senão o primeiro `# Título`, senão o nome do arquivo sem `.md`.
- **Tags:** `tags` do frontmatter (lista ou texto) e cada `#tag` do texto, sem `#` e em minúsculas. Não contam `#` em
  blocos de código, em código inline, em títulos (`# Título`) nem o `#seção` de um wikilink.
- **Links:** `[[Nota]]`, `[[Nota|apelido]]`, `[[Nota#seção]]` e `![[anexo]]` → o alvo sem seção nem apelido.
- **Contexto:** `context` do frontmatter, senão o contexto do `brain-config.yml` cuja pasta contém a nota.
- **Tipo:** `type` do frontmatter.
- **Termos:** palavras em minúsculas e sem acentos (`integração` = `integracao`), sem stopwords em português e em
  inglês. A busca é por termos, não semântica.

## Resolução de links (como o Obsidian)

- Alvo sem `/` → a nota com o mesmo nome de arquivo, sem diferenciar maiúsculas (`[[nota]]` acha `a/Nota.md`).
- Alvo com `/` → caminho relativo ao vault, com ou sem `.md` (`[[b/c/Nota]]`); vale também o final do caminho.
- Vários candidatos → o de caminho mais curto. Nenhum → link quebrado (anexos fora do vault aparecem como quebrados).

## search

`search QUERY [--context C] [--type T] [--tag G] [--limit N=10] [--json]`

Pontuação de cada nota: para cada termo da consulta, `tf × idf`, onde `tf` soma as ocorrências com peso **3 no
título**, **2 nas tags** e **1 no corpo**, e `idf = ln(1 + N / df)` (`N` notas no vault, `df` notas com o termo). Só
entram notas com pontuação maior que zero, em ordem decrescente. Os filtros são aplicados depois da contagem do `idf`:

- `--context C`: só notas do contexto `C`;
- `--type T`: só notas com `type: T` no frontmatter;
- `--tag G`: só notas com a tag `G` (com ou sem `#`).

Cada resultado traz `path`, `title`, `score`, `context`, `type` e um `snippet` de até 160 caracteres do corpo em
volta do primeiro termo encontrado. Sem resultados: `Nenhuma nota encontrada para: QUERY`, exit 0.

## related

`related (--note CAMINHO | --text TEXTO) [--limit N=10] [--json]`

Pontuação, de 0 a 1:

| Peso | Componente | Motivo em `reasons` |
|---|---|---|
| 0,5 | similaridade de termos: cosseno entre os vetores TF-IDF (título, tags e corpo) | `termos: a, b` (até 5, os que mais pesam) |
| 0,2 | tags em comum: Jaccard (em comum ÷ todas as tags das duas notas) | `tags: x, y` |
| 0,1 | mesmo contexto | `mesmo contexto` |
| 0,2 | vizinhança de links, em qualquer sentido: 1 se link direto, 0,5 se a dois passos | `link direto` ou `link a dois passos` |

A própria nota não aparece. Com `--text`, as tags (`#tag`) e os `[[links]]` do texto também contam, e não há
contexto. `--note` aceita o caminho ou o nome da nota; inexistente sai com 2 (`nota não encontrada: CAMINHO`).

## links

`links NOTA [--json]` → `{"outgoing": [{"target", "path" | null}], "backlinks": [caminhos], "broken": [alvos]}`.
`NOTA` é o caminho ou o nome (resolvido como um link); inexistente sai com 2.
