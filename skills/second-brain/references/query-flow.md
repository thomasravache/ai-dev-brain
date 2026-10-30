# Fluxo de consultar

O `SKILL.md` define os quatro passos (buscar, ler e seguir links, responder, oferecer salvar); aqui estão os detalhes do `context` e do tipo `answer`. O `context` só lê o vault: nada é escrito, nada sai da máquina.

## Exemplo: preparar para a P2 de Cálculo II

```bash
brain.py context "integrais derivadas" --context college --json
# notas: mocs/college.md (moc), projects/college/Integrais por partes.md (search:4.2),
#        resources/Regra do produto.md (link:1) ...
brain.py links "Integrais por partes" --json        # se faltar algo: seguir links de uma nota central
# resposta citando [[Integrais por partes]] e [[Regra do produto]]; lacunas apontadas
# com o sim da pessoa:
brain.py new-note --type answer --title "P2 de Cálculo II" --context college --json
# {"path": "projects/college/P2 de Cálculo II.md"}  → escreva a pergunta, a resposta e as lacunas
brain.py relate "P2 de Cálculo II" "Integrais por partes" --why "cita" --both
brain.py relate "P2 de Cálculo II" "Regra do produto" --why "cita" --both
brain.py index --context college
```

## `context QUERY`

```text
brain.py context QUERY [--context C] [--hops N=1] [--limit N=8] [--max-chars N=40000] [--json]
```

1. **Busca:** `search QUERY` (filtrada por `--context` quando dado), até `--limit` notas, com o motivo `search:<pontos>`.
2. **MOC:** com `--context`, o MOC do contexto (`<layout.mocs>/<contexto>.md`) entra primeiro, com o motivo `moc`. Ele nunca é atravessado na expansão (traria o contexto inteiro): nem é ponto de partida, nem caminho; uma nota alcançável só pelo MOC (outra nota do contexto, o `index.md`) não entra como `link:N`. Sem `--context`, o MOC é uma nota comum: pode vir da busca ou como vizinho, e é atravessado como qualquer outra.
3. **Vizinhos:** a partir das notas da busca (sem passar pelo MOC, com `--context`), os links de saída e os backlinks, em largura, até `--hops` passos (0 a 2), com o motivo `link:<distância>`. Uma nota nunca se repete: vale o primeiro motivo (MOC, depois busca, depois a menor distância).
4. **Ordem:** MOC, resultados da busca pela pontuação, vizinhos pela distância e depois pelo título.
5. **Tamanho (pula e continua):** na ordem acima, cada nota entra inteira (o arquivo todo, com o frontmatter) se ainda couber em `--max-chars` (soma do conteúdo das que já entraram); a que não cabe vai para `omitted` só com caminho, título e motivo, e as seguintes continuam sendo tentadas — uma nota grande bem ranqueada não empurra as pequenas para fora. `notes` e `omitted` mantêm a ordem de prioridade. Para ler uma omitida, abra o arquivo ou rode de novo com `--max-chars` maior ou `--hops` menor.
6. **Links quebrados:** os links das notas do pacote (incluídas e omitidas) que não resolvem são listados em `broken` (`{"note", "target"}`), sem erro.

Saída `--json`:

```json
{"query": "integrais", "notes": [{"path": "mocs/college.md", "title": "College", "reason": "moc", "content": "..."}],
 "omitted": [{"path": "...", "title": "...", "reason": "link:2"}],
 "broken": [{"note": "projects/college/Integrais por partes.md", "target": "Nota que sumiu"}], "warnings": []}
```

Saída texto: para cada nota `=== <caminho> (<motivo>) ===` e o conteúdo; no fim `Omitidas:` e `Links quebrados:`, quando há o que listar. Avisos de notas com frontmatter inválido ou que não são UTF-8 vão para `warnings` (no texto, para a saída de erro).

- **Nada encontrado** pela busca: "Nenhuma nota encontrada para: QUERY" e exit 0 (no JSON, `notes` vazio). Sem resultado da busca o pacote fica vazio, mesmo com `--context` (o MOC não vem sozinho).
- `--hops` fora de 0..2, `--limit` ou `--max-chars` menor que 1: exit 2.
- Desempenho: menos de 2 s num vault de 5.000 notas com `--hops 2`.

### `context add` ou consulta?

Se a primeira palavra depois de `context` é exatamente `add`, o comando é o `context add NOME --folder PASTA` (cria um contexto). Qualquer outro texto é uma consulta. Para buscar a própria palavra add, ponha uma opção antes dela: `brain.py context --json add` (ou `brain.py context --hops 1 -- add`; depois do `--` tudo é consulta).

## Responder

- Cada afirmação vinda do vault cita a nota: `[[Título da nota]]`.
- O que vier de conhecimento geral (fora do vault) é marcado como tal, ex.: "(conhecimento geral, não está no vault)".
- Lacunas: diga o que a pergunta pede e o vault não tem — é o que vale guardar depois.
- Use também `omitted` e `broken`: uma nota omitida pode ter a resposta; um link quebrado pode ser uma nota que falta.

## Salvar a resposta (`answer`)

Só com o sim da pessoa. `new-note --type answer` cria a nota a partir de `assets/templates/answer.md` (ou do `templates/answer.md` do vault) com `question` e `cites` no frontmatter e as seções `## Question`, `## Answer`, `## Gaps` e `## Relations`. Preencha `question` com a pergunta, `cites` com os títulos das notas citadas e o corpo; depois `relate ... --why "cita" --both` com cada nota citada e `index --context C` para o MOC listar a resposta. Vaults já configurados antes desta versão não têm `templates/answer.md` (o `init` não o copia para eles): o `new-note` usa o modelo de resposta da skill até a pessoa copiar `assets/templates/answer.md` para a pasta `templates/` do vault (e personalizá-lo lá). Tipos de nota: `references/note-types.md`.
