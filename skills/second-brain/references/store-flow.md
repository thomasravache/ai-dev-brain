# Fluxo de guardar

O `SKILL.md` define os seis passos; aqui estão os detalhes de cada comando. Toda escrita do `brain.py` acrescenta uma linha no fim do `log.md`: `- AAAA-MM-DD HH:MM <comando> <caminho> [<detalhe>]`, com o caminho relativo ao vault. Comando que falha ou não muda nada não escreve no log. Nenhum comando sobrescreve ou apaga arquivo.

## Exemplo: guardar os slides de uma aula

```bash
brain.py ingest slides.pdf --context college --text-file /tmp/slides.txt --json
# {"raw": "raw/2026-10-30-slides.md", "file": "college/2026/slides.pdf", "url": null}
brain.py related --text "integração por partes, regra do produto da derivada" --json
brain.py new-note --type lecture --title "Integrais por partes" --context college --source raw/2026-10-30-slides.md --json
# {"path": "projects/college/Integrais por partes.md"}  → escreva o corpo sintetizado neste arquivo
brain.py relate "Integrais por partes" "Regra do produto" --why "aplica" --both
brain.py index --context college
```

## `ingest FONTE`

- **Arquivo:** copiado para `<files>/<contexto ou inbox>/<AAAA>/<nome>`. Nome que já existe vira `<nome>-1`, `-2`... — a cópia anterior nunca muda. A cópia acontece antes da nota de fonte: pasta `files` inexistente ou sem permissão sai com 1 e nada é criado no vault.
- **URL (http/https):** nada é copiado nem baixado; a nota guarda `source_url`. Ler a página é com você, se tiver ferramenta para isso.
- **Nota de fonte:** `raw/AAAA-MM-DD-<slug>.md` (`-1`, `-2`... no mesmo dia), `type: source`, com o texto de `--text-file` sob `## Extracted text`, ou `_(pending)_`.
- Fonte inexistente sai com 2 (`fonte não encontrada: FONTE`).

## `new-note`

- Caminho: `<pasta do contexto ou resources>/<título sanitizado>.md`; `/ \ : * ? " < > | # ^ [ ]` viram espaço. Pasta que sairia do vault é recusada (exit 2).
- Nota que já existe: exit 2 `nota já existe: CAMINHO`, sem mudar nada. Escolha outro título ou complemente a nota existente (só acrescentando).
- Tipo desconhecido ou contexto inexistente: exit 2 com a lista válida.
- `--source` aceita o caminho da nota de fonte (vira `"[[raw/...]]"`) ou uma URL.

## `relate DE PARA --why "motivo" [--both]`

- DE e PARA são o nome ou o caminho da nota (resolvidos como links do Obsidian); inexistente sai com 2.
- Acrescenta `- [[PARA]] — motivo` no fim da seção `## Relations` de DE (cria a seção no fim se faltar); com `--both`, o mesmo em PARA apontando para DE.
- A mesma linha já presente: nada muda e o comando diz `relação já existe`.
- Motivos úteis: "aplica", "contradiz", "exemplo de", "pré-requisito de", "complementa".

## `index [--context C]`

- `mocs/<contexto>.md`: região `notes` com as notas do contexto agrupadas por `type` (`### lecture`, `### note`...), ordenadas por título. MOC ausente é criado do modelo `moc`; MOC sem a região ganha a região no fim.
- `index.md`: região `contexts` (link para cada MOC e o total de notas) e região `recent` (as 20 notas mais recentes pelo `created`).
- Texto fora das regiões nunca muda. Com `--context C`, só o MOC de C (e o `index.md`) é regenerado.
- Num vault de 5.000 notas termina em menos de 3 s (o limite garantido).
- Marcadores de região quebrados (begin sem end, end antes do begin, região duplicada) ou um MOC que é link simbólico para fora do vault fazem o `index` parar com erro nomeando o arquivo, sem escrever nada.
